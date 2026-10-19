"""Signal Reader: reads the closed candle of every AGENT chart on schedule and stores snapshots."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from typing import Any

from tradeagent import resources
from tradeagent.alerts import Alerter
from tradeagent.config import Settings
from tradeagent.journal import log_event
from tradeagent.market.clock import ServerClock
from tradeagent.tv import js
from tradeagent.tv.catalog import Catalog
from tradeagent.journal.db import now_ms, write_status
from tradeagent.tv.cdp import VERIFIED_APP_VERSIONS, CDPError, ChartPage, TradingViewCDP, app_version
from tradeagent.tv.schedule import TF_SECONDS, TV_INTERVAL, closing_at, last_closed_bar, next_boundary
from tradeagent.tv.snapshots import (
    NOT_CLOSED,
    Snapshot,
    build_snapshot,
    failed_snapshot,
    resolve_signal_version,
    settings_fingerprint,
    store_snapshot,
)
from tradeagent.tv.watchdog import Watchdog

log = logging.getLogger("tradeagent.reader")

# Candles of the last REPAIR_BARS that have no good snapshot (a failed read, a busy computer, a restart) are read
# again from the chart's loaded history in the next good read, before the shadow engine moves past them.
REPAIR_BARS = 12

INPUTS_WAIT_S = 120  # after a TradingView start the indicators of a tab can take a while to load
NOT_CLOSED_RETRIES = 3  # a candle read before the chart shows the next one is read again this often...
NOT_CLOSED_WAIT_S = 1.0  # ...this many seconds apart
CLOCK_EVERY_S = 900  # the venue's clock offset is measured this often (a stale offset shifts every read)
LATE_WAKE_S = 600  # a candle close noticed this late means the computer slept; it is skipped


def _is_connection_problem(exc: BaseException) -> bool:
    import ccxt

    return isinstance(exc, (ccxt.NetworkError, CDPError, TimeoutError, ConnectionError))


def _short(exc: BaseException) -> str:
    """One line for the log: the exception type and the start of its message."""
    text = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {text[:200]}" if text else type(exc).__name__


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
        if clock is None:  # the trading venue's server time (or this computer's clock where it has none)
            from tradeagent.venues import market_data

            clock = ServerClock(market_data(settings).fetch_time)
        self.clock = clock
        self.watchdog = Watchdog(settings, self.cdp)
        self.signal_version = tv.signal_version
        self._timeout_ms = int(tv.prepare_timeout_s * 1000)
        self.alerter: Alerter | None = None  # the agent sets one: phone messages for failing reads and the clock
        self._bad_cycles = 0  # cycles in a row with a failed read

    def template_for(self, timeframe: str) -> str:
        if timeframe in self.catalog.chart_templates:
            return self.catalog.chart_templates[timeframe]
        return "scalp" if timeframe in self.settings.timeframes.trade else "trend"

    async def start(self) -> list[str]:
        """Sync the clock, repair TradingView if needed, and check the indicator settings."""
        await asyncio.to_thread(self.clock.measure)
        actions = await self.watchdog.ensure()
        await self._check_app_version()
        await self.check_signal_version()
        return actions

    async def _check_app_version(self) -> None:
        """The reader uses TradingView's undocumented internal API: an update can break it. Record the version and
        say so when it changed since the last start."""
        try:
            version = app_version(await self.cdp.version())
        except Exception as exc:
            log.debug("TradingView version not read: %s", _short(exc))
            return
        if not version:
            return
        row = self.conn.execute("SELECT value_json FROM agent_status WHERE key = 'tradingview'").fetchone()
        before = json.loads(row[0]).get("version") if row else None
        write_status(self.conn, "tradingview", {"version": version, "at": now_ms()})
        if before and before != version:
            checked = "" if version in VERIFIED_APP_VERSIONS else " The reader was not checked with this version yet."
            message = f"TradingView Desktop changed from {before} to {version}.{checked} Watch the next reads."
            log.warning(message)
            log_event(self.conn, "WARNING", "reader", message)
            if self.alerter:
                self.alerter.notice(message)

    def _expected_studies(self, layout_id: str) -> dict[str, set[str]]:
        """Chart interval -> the indicators its template reads, for one AGENT layout."""
        overview = layout_id == self.settings.htf_layout
        timeframes = self.settings.timeframes.overview if overview else self.settings.timeframes.trade
        return {TV_INTERVAL[tf]: {ind["study"] for ind in self.catalog.js_spec(self.template_for(tf)).values()}
                for tf in timeframes}

    async def _read_indicator_inputs(self, wait_s: float, poll_s: float) -> dict[str, Any]:
        """Inputs of the indicators on every AGENT chart.

        Right after TradingView starts, a tab can show its charts before their indicators have loaded. A
        fingerprint taken then looks like changed settings and starts a false new signal version, so wait until
        every chart shows all indicators of its template.
        """
        names = self.catalog.study_names()
        deadline = time.monotonic() + wait_s
        while True:
            pages = await self.watchdog.pages()
            inputs: dict[str, Any] = {}
            missing: list[str] = []
            for name, layout_id in sorted(self.settings.tradingview.layouts.items()):
                page = pages.get(layout_id)
                if page is None:
                    missing.append(f"layout {name} is not open")
                    continue
                try:
                    charts = await self.cdp.evaluate(page, js.read_inputs(names))
                except CDPError as exc:
                    missing.append(f"{name}: {exc}")
                    continue
                found = {chart["interval"]: chart["studies"] for chart in charts}
                for interval, studies in self._expected_studies(layout_id).items():
                    absent = sorted(studies - set(found.get(interval, {})))
                    if absent:
                        missing.append(f"{name} {interval}: {', '.join(absent)} not loaded")
                for chart in charts:
                    inputs[f"{name}/{chart['interval']}"] = chart["studies"]
            if not missing:
                return inputs
            if time.monotonic() >= deadline:
                raise CDPError("indicator settings could not be read: " + "; ".join(missing))
            await asyncio.sleep(poll_s)

    async def check_signal_version(self, wait_s: float = INPUTS_WAIT_S, poll_s: float = 3) -> int:
        inputs = await self._read_indicator_inputs(wait_s, poll_s)
        fingerprint, canonical = settings_fingerprint(inputs)
        version, changed = resolve_signal_version(
            self.conn, self.settings.tradingview.signal_version, fingerprint, canonical
        )
        if changed:
            message = f"indicator settings changed: snapshots now use signal version {version}"
            log.warning(message)
            log_event(self.conn, "WARNING", "reader", message, {"fingerprint": fingerprint})
            if self.alerter:
                self.alerter.notice(f"{message}. If nobody changed an indicator on an AGENT chart, check TradingView.")
        self.signal_version = version
        return version

    async def check_clock(self) -> None:
        """Measure the venue's clock offset; alert when this computer's clock is off by more than allowed."""
        try:
            offset = await asyncio.to_thread(self.clock.measure)
        except Exception as exc:
            log.warning("clock measurement failed: %s", _short(exc))
            return
        if self.alerter is None or offset is None:
            return
        limit = self.settings.alerts.clock_offset_ms
        if abs(offset) > limit:
            self.alerter.problem("clock", f"this computer's clock is {offset / 1000:+.1f} s off the exchange (limit "
                                          f"{limit / 1000:g} s). Check Windows time sync: w32tm /query /status")
        else:
            self.alerter.solved("clock", f"the clock is back in sync ({offset:+d} ms)")

    async def _check_version_now(self) -> None:
        """Before every read: changed indicator inputs get their own signal version from this read on, not up to an
        hour later. A chart whose indicators are still loading is left to the hourly check, which waits for it."""
        try:
            await self.check_signal_version(wait_s=0)
        except Exception as exc:
            log.debug("signal version not checked this cycle: %s", _short(exc))

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
            # The HTF tab switches coins every read; a coin's own tab is switched back if someone changed its symbol.
            prep = await self.cdp.evaluate(
                page, js.prepare(tv_symbol, self.settings.tradingview.min_bars, self._timeout_ms), await_promise=True,
            )
        except CDPError as exc:
            return [failed(tf, f"could not prepare the chart: {exc}") for tf in timeframes]
        if not switch_symbol and prep.get("switched"):
            shown = sorted({s for s in prep.get("before") or [] if s != tv_symbol})
            name = next((n for n, i in self.settings.tradingview.layouts.items() if i == page.layout_id), page.layout_id)
            message = (f"{name} showed {', '.join(shown)} instead of {tv_symbol};"
                       " switched it back. Use your own layout (not an AGENT tab) to look at other charts.")
            log.warning(message)
            log_event(self.conn, "WARNING", "reader", message)
        index_by_interval = {chart["interval"]: chart["index"] for chart in prep["charts"]}

        snaps = []
        for tf in timeframes:
            index = index_by_interval.get(TV_INTERVAL[tf])
            if index is None:
                snaps.append(failed(tf, f"no {tf} chart in the tab"))
                continue
            spec = self.catalog.js_spec(self.template_for(tf))
            for attempt in range(NOT_CLOSED_RETRIES + 1):
                try:
                    raw = await self.cdp.evaluate(page, js.read_closed(spec, index, bar_times[tf]))
                except CDPError as exc:
                    raw = {"error": f"read failed: {exc}"}
                snap = build_snapshot(
                    raw, symbol=coin, timeframe=tf, tradingview_symbol=tv_symbol, bar_time_s=bar_times[tf],
                    signal_version=self.signal_version, read_at_ms=self.clock.now_ms(), spec=spec,
                )
                # The chart's next candle starts with its first trade: give a quiet moment a little longer.
                if NOT_CLOSED not in snap.problems or attempt == NOT_CLOSED_RETRIES:
                    break
                await asyncio.sleep(NOT_CLOSED_WAIT_S)
            if not prep.get("ok"):
                snap.problems.append("chart was not fully prepared (history or indicators still loading)")
            snaps.append(snap)
            if prep.get("ok"):
                await self._repair(page, coin, tf, index, spec, tv_symbol, bar_times[tf])
        return snaps

    async def _repair(self, page: ChartPage, coin: str, tf: str, index: int, spec: dict[str, Any], tv_symbol: str,
                      bar_time_s: int) -> None:
        """Read missed closed candles of the last REPAIR_BARS again (stored as source 'backfill')."""
        step = TF_SECONDS[tf]
        first = bar_time_s - REPAIR_BARS * step
        have = {r[0] for r in self.conn.execute(
            "SELECT bar_time FROM snapshots WHERE symbol = ? AND timeframe = ? AND bar_time >= ? AND bar_time < ?"
            " AND problems_json IS NULL", (coin, tf, first * 1000, bar_time_s * 1000))}
        repaired = []
        for t in range(first, bar_time_s, step):
            if t * 1000 in have:
                continue
            try:
                raw = await self.cdp.evaluate(page, js.read_closed(spec, index, t))
            except CDPError:
                return
            snap = build_snapshot(raw, symbol=coin, timeframe=tf, tradingview_symbol=tv_symbol, bar_time_s=t,
                                  signal_version=self.signal_version, read_at_ms=self.clock.now_ms(), spec=spec)
            if snap.ok:
                snap.source = "backfill"
                store_snapshot(self.conn, snap)
                repaired.append(time.strftime("%H:%M", time.gmtime(t)))
        if repaired:
            log.info("%s %s: read %d missed candle(s) again from the chart: %s", coin, tf, len(repaired), ", ".join(repaired))

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
        last_hourly = last_clock = time.monotonic()
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
            late = self.clock.now_s() - boundary
            if late > max(2 * step, LATE_WAKE_S):
                # The computer slept (or the process was paused): that candle close is long gone. Re-measure the
                # clock, say what was missed, and continue with the next candle close instead of a stale read.
                message = (f"no reads from {time.strftime('%H:%M', time.gmtime(boundary))} to "
                           f"{time.strftime('%H:%M', time.gmtime(self.clock.now_s()))} UTC: the computer was asleep or busy "
                           f"({late / 60:.0f} min, about {int(late // step)} candle closes missed)")
                log.warning(message)
                log_event(self.conn, "WARNING", "reader", message)
                try:
                    await asyncio.to_thread(self.clock.measure)
                except Exception as exc:
                    log.warning("clock measurement failed: %s", _short(exc))
                continue
            timeframes = closing_at(boundary, self.settings.all_timeframes)
            try:
                actions = await self.watchdog.ensure()
                if actions:
                    log_event(self.conn, "WARNING", "watchdog", "; ".join(actions))
                    if self.alerter:
                        self.alerter.notice("TradingView watchdog: " + "; ".join(actions))
                await self._check_version_now()
                snaps = await self.read(timeframes, boundary)
                self._record_cycle(boundary, snaps)
                if after_cycle:
                    await after_cycle(boundary, snaps)
            except Exception as exc:  # keep running; the next cycle retries
                if _is_connection_problem(exc):  # no internet, exchange or TradingView unreachable: one line is enough
                    log.warning("cycle failed, retrying next cycle: %s", _short(exc))
                else:
                    log.exception("cycle failed")
                log_event(self.conn, "ERROR", "reader", f"cycle failed: {_short(exc)}")
                self._count_bad_cycle(f"the cycle failed: {_short(exc)}")
            if time.monotonic() - last_hourly >= 3600:
                last_hourly = last_clock = time.monotonic()
                await self._run_hourly(hourly)
            elif time.monotonic() - last_clock >= CLOCK_EVERY_S:
                last_clock = time.monotonic()
                await self.check_clock()
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
            first = bad[0]
            self._count_bad_cycle(f"{message}; e.g. {first.symbol} {first.timeframe}: {'; '.join(first.problems)[:300]}")
        else:
            self._bad_cycles = 0
            if self.alerter:
                self.alerter.solved("reads", f"TradingView reads are good again ({message})")

    def _count_bad_cycle(self, what: str) -> None:
        self._bad_cycles += 1
        if self.alerter and self._bad_cycles >= self.settings.alerts.failed_cycles:
            self.alerter.problem("reads", f"{self._bad_cycles} cycles in a row with failed TradingView reads. Last: {what}")

    async def _hourly(self) -> None:
        await self.check_clock()
        try:
            await self.check_signal_version()
        except Exception as exc:
            log.warning("signal version check failed: %s", _short(exc))
        usage = await asyncio.to_thread(resources.usage)
        level = "WARNING" if usage["ram_used_pct"] > 80 else "INFO"
        log_event(self.conn, level, "resources", f"RAM {usage['ram_used_pct']}% used", usage)
        log.log(logging.WARNING if level == "WARNING" else logging.INFO, "resources: %s", usage)
