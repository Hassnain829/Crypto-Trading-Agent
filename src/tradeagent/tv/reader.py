"""Signal Reader: reads the closed candle of every AGENT chart on schedule and stores snapshots."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from typing import Any

from tradeagent import resources
from tradeagent.config import Settings
from tradeagent.journal import log_event
from tradeagent.market.clock import ServerClock
from tradeagent.tv import js
from tradeagent.tv.catalog import Catalog
from tradeagent.tv.cdp import CDPError, ChartPage, TradingViewCDP
from tradeagent.tv.schedule import TF_SECONDS, TV_INTERVAL, closing_at, last_closed_bar, next_boundary
from tradeagent.tv.snapshots import (
    Snapshot,
    build_snapshot,
    failed_snapshot,
    resolve_signal_version,
    settings_fingerprint,
    store_snapshot,
)
from tradeagent.tv.watchdog import Watchdog

log = logging.getLogger("tradeagent.reader")


class SignalReader:
    def __init__(
        self,
        settings: Settings,
        catalog: Catalog,
        conn: sqlite3.Connection,
        *,
        cdp: TradingViewCDP | None = None,
        clock: ServerClock | None = None,
    ) -> None:
        tv = settings.tradingview
        self.settings = settings
        self.catalog = catalog
        self.conn = conn
        self.cdp = cdp or TradingViewCDP(tv.cdp_host, tv.cdp_port, timeout=tv.prepare_timeout_s + 15)
        self.clock = clock or ServerClock()
        self.watchdog = Watchdog(settings, self.cdp)
        self.signal_version = tv.signal_version
        self._timeout_ms = int(tv.prepare_timeout_s * 1000)

    def template_for(self, timeframe: str) -> str:
        return "scalp" if timeframe in self.settings.timeframes.trade else "trend"

    async def start(self) -> list[str]:
        """Sync the clock, repair TradingView if needed, and check the indicator settings."""
        await asyncio.to_thread(self.clock.measure)
        actions = await self.watchdog.ensure()
        await self.check_signal_version()
        return actions

    async def check_signal_version(self) -> int:
        pages = await self.watchdog.pages()
        names = self.catalog.study_names()
        inputs: dict[str, Any] = {}
        for name, layout_id in sorted(self.settings.tradingview.layouts.items()):
            page = pages.get(layout_id)
            if page is None:
                raise CDPError(f"layout {name} is not open")
            for chart in await self.cdp.evaluate(page, js.read_inputs(names)):
                inputs[f"{name}/{chart['interval']}"] = chart["studies"]
        fingerprint, canonical = settings_fingerprint(inputs)
        version, changed = resolve_signal_version(
            self.conn, self.settings.tradingview.signal_version, fingerprint, canonical
        )
        if changed:
            message = f"indicator settings changed: snapshots now use signal version {version}"
            log.warning(message)
            log_event(self.conn, "WARNING", "reader", message, {"fingerprint": fingerprint})
        self.signal_version = version
        return version

    async def read(self, timeframes: list[str], boundary_s: int | None = None) -> list[Snapshot]:
        """Read the candles that closed at `boundary_s` (or the last closed ones) and store them."""
        now_s = self.clock.now_s()
        bar_times = {
            tf: boundary_s - TF_SECONDS[tf] if boundary_s is not None else last_closed_bar(now_s, tf)
            for tf in timeframes
        }
        trade = [tf for tf in timeframes if tf in self.settings.timeframes.trade]
        overview = [tf for tf in timeframes if tf in self.settings.timeframes.overview]
        pages = await self.watchdog.pages()
        snaps: list[Snapshot] = []
        for coin in self.settings.exchange.symbols:
            if trade:
                snaps += await self._read_tab(pages.get(self.settings.layout_for(coin)), coin, False, trade, bar_times)
        for coin in self.settings.exchange.symbols:
            if overview:
                snaps += await self._read_tab(pages.get(self.settings.htf_layout), coin, True, overview, bar_times)
        for snap in snaps:
            store_snapshot(self.conn, snap)
        return snaps

    async def _read_tab(
        self, page: ChartPage | None, coin: str, switch_symbol: bool, timeframes: list[str], bar_times: dict[str, int]
    ) -> list[Snapshot]:
        tv_symbol = self.settings.exchange.symbols[coin].tradingview

        def failed(tf: str, problem: str) -> Snapshot:
            return failed_snapshot(coin, tf, bar_times[tf], self.signal_version, self.clock.now_ms(), problem)

        if page is None:
            return [failed(tf, "chart tab is not open") for tf in timeframes]
        try:
            prep = await self.cdp.evaluate(
                page,
                js.prepare(tv_symbol if switch_symbol else None, self.settings.tradingview.min_bars, self._timeout_ms),
                await_promise=True,
            )
        except CDPError as exc:
            return [failed(tf, f"could not prepare the chart: {exc}") for tf in timeframes]
        index_by_interval = {chart["interval"]: chart["index"] for chart in prep["charts"]}

        snaps = []
        for tf in timeframes:
            index = index_by_interval.get(TV_INTERVAL[tf])
            if index is None:
                snaps.append(failed(tf, f"no {tf} chart in the tab"))
                continue
            spec = self.catalog.js_spec(self.template_for(tf))
            try:
                raw = await self.cdp.evaluate(page, js.read_closed(spec, index, bar_times[tf]))
            except CDPError as exc:
                raw = {"error": f"read failed: {exc}"}
            snap = build_snapshot(
                raw, symbol=coin, timeframe=tf, tradingview_symbol=tv_symbol, bar_time_s=bar_times[tf],
                signal_version=self.signal_version, read_at_ms=self.clock.now_ms(), spec=spec,
            )
            if not prep.get("ok"):
                snap.problems.append("chart was not fully prepared (history or indicators still loading)")
            snaps.append(snap)
        return snaps

    async def _run_hourly(self, hourly: Callable[[], Awaitable[None]] | None) -> None:
        for task in (self._hourly, hourly):
            if task is None:
                continue
            try:
                await task()
            except Exception as exc:  # e.g. no internet for a moment; the next hour tries again
                log.warning("hourly task failed: %s", exc)

    async def run(
        self,
        *,
        stop: asyncio.Event | None = None,
        max_cycles: int | None = None,
        after_cycle: Callable[[int, list[Snapshot]], Awaitable[None]] | None = None,
        hourly: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Read at every candle close until `stop` is set (or `max_cycles` cycles have run).

        `after_cycle` runs after every read (the agent uses it for the shadow engine); `hourly` once an hour.
        """
        stop = stop or asyncio.Event()
        while not stop.is_set():
            try:
                await self.start()
                break
            except Exception as exc:  # TradingView not ready yet: wait and try again instead of exiting
                log.exception("start failed; retrying in 60 s")
                log_event(self.conn, "ERROR", "reader", f"start failed, retrying: {exc}")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=60)
                except TimeoutError:
                    pass
        await self._run_hourly(hourly)
        step = min(TF_SECONDS[tf] for tf in self.settings.all_timeframes)
        last_hourly = time.monotonic()
        cycles = 0
        log.info("reader started (signal version %s)", self.signal_version)
        while not stop.is_set():
            boundary = next_boundary(self.clock.now_s(), step)
            delay = boundary + self.settings.tradingview.read_delay_s - self.clock.now_s()
            try:
                await asyncio.wait_for(stop.wait(), timeout=max(0.0, delay))
                break
            except TimeoutError:
                pass
            timeframes = closing_at(boundary, self.settings.all_timeframes)
            try:
                actions = await self.watchdog.ensure()
                if actions:
                    log_event(self.conn, "WARNING", "watchdog", "; ".join(actions))
                snaps = await self.read(timeframes, boundary)
                self._record_cycle(boundary, snaps)
                if after_cycle:
                    await after_cycle(boundary, snaps)
            except Exception as exc:  # keep running; the next cycle retries
                log.exception("cycle failed")
                log_event(self.conn, "ERROR", "reader", f"cycle failed: {exc}")
            if time.monotonic() - last_hourly >= 3600:
                last_hourly = time.monotonic()
                await self._run_hourly(hourly)
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break

    def _record_cycle(self, boundary_s: int, snaps: list[Snapshot]) -> None:
        bad = [s for s in snaps if not s.ok]
        latency = max((s.latency_ms for s in snaps), default=0)
        message = f"{len(snaps) - len(bad)}/{len(snaps)} snapshots ok, max latency {latency / 1000:.1f}s"
        log.info("cycle %s: %s", time.strftime("%H:%M", time.gmtime(boundary_s)), message)
        if bad:
            details = [{"symbol": s.symbol, "timeframe": s.timeframe, "problems": s.problems} for s in bad]
            log_event(self.conn, "WARNING", "reader", message, details)

    async def _hourly(self) -> None:
        try:
            await asyncio.to_thread(self.clock.measure)
        except Exception as exc:
            log.warning("clock measurement failed: %s", exc)
        try:
            await self.check_signal_version()
        except Exception as exc:
            log.warning("signal version check failed: %s", exc)
        usage = await asyncio.to_thread(resources.usage)
        level = "WARNING" if usage["ram_used_pct"] > 80 else "INFO"
        log_event(self.conn, level, "resources", f"RAM {usage['ram_used_pct']}% used", usage)
        log.log(logging.WARNING if level == "WARNING" else logging.INFO, "resources: %s", usage)
