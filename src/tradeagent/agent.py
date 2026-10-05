"""The 24/7 agent: signal reader + Binance market data + setup engine + shadow tracker + paper account."""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import time
from collections import Counter
from typing import Any

from tradeagent import __version__
from tradeagent.account.engine import AccountEngine
from tradeagent.config import Settings
from tradeagent.journal import log_event
from tradeagent.journal.db import now_ms, write_status
from tradeagent.learning import experiments as learning
from tradeagent.learning import runner
from tradeagent.learning.pack import write_pack, written_today
from tradeagent.market.candles import ensure_venue, sync_market_info
from tradeagent.market.sync import sync_all
from tradeagent.settings_store import apply_overrides
from tradeagent.setups.config import register_variants
from tradeagent.setups.engine import SetupEngine
from tradeagent.sim.tracker import Tracker
from tradeagent.supervisor import stop_requested_at
from tradeagent.tv.catalog import Catalog
from tradeagent.tv.drawings import TradeDrawer
from tradeagent.tv.reader import SignalReader
from tradeagent.tv.snapshots import Snapshot

log = logging.getLogger("tradeagent.agent")

STOP_POLL_S = 3  # how often the agent looks for a stop request from the dashboard
BACKFILL_PAGES = 20  # older candles downloaded per cycle and timeframe (newest first) after a venue change


class Agent:
    def __init__(self, settings: Settings, catalog: Catalog, conn: sqlite3.Connection) -> None:
        self.settings = settings
        self.conn = conn
        self._apply_dashboard_settings()
        self.reader = SignalReader(settings, catalog, conn)
        self.catalog = catalog
        # The baseline (with promoted changes), setups.yaml's challengers and the running experiments.
        self.variants = learning.active_variants(settings, conn, catalog)
        register_variants(conn, self.variants)
        learning.sync_manual(conn, settings, self.variants)
        self.engine = SetupEngine(settings, self.variants, conn)
        self._rules_problem: str | None = None
        self._screen: Any = None  # the background history screen, while it runs
        self._research: Any = None  # the daily Claude research run, while it runs
        self.tracker = Tracker(settings, conn)
        self.account = AccountEngine(settings, conn)
        self.drawer = TradeDrawer(settings, conn, self.reader.cdp, self.reader.watchdog.pages)
        self._client: Any = None

    @property
    def client(self) -> Any:
        # A new client when the venue changed (the dashboard setting is re-applied every cycle).
        if self._client is None or self._client.venue.id != self.settings.venue:
            from tradeagent.venues import market_data

            self._client = market_data(self.settings)
        return self._client

    def _apply_dashboard_settings(self) -> None:
        """Settings changed in the dashboard are stored in the journal; apply them before each cycle."""
        for problem in apply_overrides(self.settings, self.conn):
            log.warning("dashboard setting ignored: %s", problem)

    def reload_variants(self) -> None:
        """Edits of setups.yaml, new experiments and promotions take effect without a restart."""
        try:
            variants = learning.active_variants(self.settings, self.conn, self.catalog)
        except Exception as exc:  # a broken setups.yaml must not stop trading: keep the current rules
            if str(exc) != self._rules_problem:
                self._rules_problem = str(exc)
                log_event(self.conn, "ERROR", "learning", f"setup rules not reloaded, the current ones stay: {exc}")
            return
        self._rules_problem = None
        if [v.id for v in variants] != [v.id for v in self.variants]:
            register_variants(self.conn, variants)
            self.variants = variants
            self.engine = SetupEngine(self.settings, variants, self.conn)
            log_event(self.conn, "INFO", "learning",
                      f"setup rules reloaded: baseline {variants[0].id}, {len(variants) - 1} challengers")
        for action in learning.sync_manual(self.conn, self.settings, variants):
            log_event(self.conn, "INFO", "learning", action)

    def learning_hourly(self) -> None:
        """Judge the experiments, screen waiting proposals, and write the daily research pack."""
        for action in learning.evaluate(self.conn, self.settings, self.variants):
            log_event(self.conn, "INFO", "learning", action)
        self.reload_variants()  # a promotion becomes the baseline right away
        waiting = self.conn.execute("SELECT count(*) FROM experiments WHERE status = 'screening'").fetchone()[0]
        if waiting and (self._screen is None or self._screen.poll() is not None):
            self._screen = runner.spawn_screen(self.settings)
            log.info("history screen started for %d proposal(s)", waiting)
        research = self.settings.research
        if time.strftime("%H:%M", time.gmtime()) >= research.daily_time_utc and not written_today(self.settings):
            path = write_pack(self.settings, self.conn, self.variants)
            log_event(self.conn, "INFO", "learning", f"research pack written: {path.name}")
            if research.enabled and (self._research is None or self._research.poll() is not None):
                self._research = runner.spawn_research(self.settings)
                if self._research is None:
                    log_event(self.conn, "WARNING", "learning", "daily research is on, but the claude command is not"
                              " installed on this computer: run /research in Claude Code by hand")
                else:
                    log_event(self.conn, "INFO", "learning", "daily Claude research started (data/logs/research.log)")

    def shadow_step(self) -> Counter[str]:
        """Sync Binance candles, turn new snapshots into trades, and move open trades forward. Blocking."""
        self._apply_dashboard_settings()
        self.reload_variants()
        counts: Counter[str] = Counter()
        synced = sync_all(self.settings, self.conn, self.client, self.reader.clock.now_ms(),
                          backfill_pages=BACKFILL_PAGES)
        counts["candles_added"] = sum(n for name, n in synced.items() if not name.endswith("funding"))
        counts.update(self.engine.process())
        counts.update(self.tracker.update())
        counts.update({f"paper_{name}": n for name, n in self.account.process().items()})
        counts["open_trades"] = self.conn.execute(
            "SELECT count(*) FROM trades WHERE book = 'exploration' AND status = 'open'"
        ).fetchone()[0]
        return counts

    async def _after_cycle(self, boundary_s: int, snaps: list[Snapshot]) -> None:
        started = time.monotonic()
        counts = self.shadow_step()
        message = (
            f"shadow: {counts['candles']} candles, {counts['triggers']} triggers, "
            f"{counts['trades_taken']} taken, {counts['trades_counterfactual']} counterfactual, "
            f"{counts['closed']} closed, {counts['open_trades']} open | paper: {counts['paper_opened']} opened, "
            f"{counts['paper_rejected']} rejected, {counts['paper_settled']} settled"
        )
        log.info(message)
        if self.settings.tradingview.draw_trades:
            try:  # drawings are a convenience: they must never break the cycle
                drawn = await self.drawer.sync()
                if drawn:
                    log.info("drawings: %s", dict(drawn))
            except Exception as exc:
                log.warning("drawing paper trades failed: %s", exc)
        if counts["no_entry_candle"]:
            log_event(self.conn, "WARNING", "engine", f"{counts['no_entry_candle']} candles had no Binance entry candle")
        write_status(self.conn, "heartbeat", {
            "at": now_ms(), "boundary": boundary_s * 1000,
            "snapshots_ok": sum(1 for s in snaps if s.ok), "snapshots": len(snaps),
            "max_latency_s": max((s.latency_ms for s in snaps), default=0) / 1000,
            "shadow_seconds": round(time.monotonic() - started, 1),
            "clock_offset_ms": self.reader.clock.offset_ms,  # Binance minus this computer; corrected in every read
            "counts": {k: v for k, v in counts.items() if v},
        })

    async def _hourly(self) -> None:
        try:  # the learning loop needs no network; its failure must not stop the market data
            self.learning_hourly()
        except Exception as exc:
            log.exception("learning step failed")
            log_event(self.conn, "ERROR", "learning", f"learning step failed: {exc}")
        ensure_venue(self.conn, self.settings.venue)
        sync_market_info(self.conn, self.client, self.settings.markets())

    async def _watch_stop_requests(self, stop: asyncio.Event, started_at: int) -> None:
        """The dashboard's Stop button writes a stop request to the journal; stop after the current step."""
        while not stop.is_set():
            requested = stop_requested_at(self.conn)
            if requested and requested > started_at:
                log.info("stop requested from the dashboard")
                stop.set()
                return
            await asyncio.sleep(STOP_POLL_S)

    async def run(self, *, stop: asyncio.Event | None = None, max_cycles: int | None = None) -> None:
        log.info("agent starting: catching up market data and shadow trades")
        started_at = now_ms()
        write_status(self.conn, "agent", {"started_at": started_at, "pid": os.getpid(), "version": __version__,
                                          "baseline": self.variants[0].id, "variants": len(self.variants)})
        stop = stop or asyncio.Event()
        watcher = asyncio.create_task(self._watch_stop_requests(stop, started_at))
        try:
            try:
                await self._hourly()  # market info first: the paper account sizes orders with the step sizes
                counts = self.shadow_step()
                log.info("catch-up done: %s", dict(counts))
            except Exception as exc:  # no internet yet, for example: start reading anyway, later cycles catch up
                log.exception("catch-up failed")
                log_event(self.conn, "ERROR", "agent", f"catch-up failed: {exc}")
            await self.reader.run(stop=stop, max_cycles=max_cycles, after_cycle=self._after_cycle, hourly=self._hourly)
        finally:
            watcher.cancel()
        log.info("agent stopped")
