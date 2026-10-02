"""The 24/7 agent: signal reader + Binance market data + setup engine + shadow tracker (+ paper account)."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections import Counter
from typing import Any

from tradeagent.account.engine import AccountEngine
from tradeagent.config import Settings
from tradeagent.journal import log_event
from tradeagent.market.candles import sync_market_info
from tradeagent.market.sync import sync_all
from tradeagent.setups.config import load_variants, register_variants
from tradeagent.setups.engine import SetupEngine
from tradeagent.sim.tracker import Tracker
from tradeagent.tv.catalog import Catalog
from tradeagent.tv.reader import SignalReader
from tradeagent.tv.snapshots import Snapshot

log = logging.getLogger("tradeagent.agent")


class Agent:
    def __init__(self, settings: Settings, catalog: Catalog, conn: sqlite3.Connection) -> None:
        self.settings = settings
        self.conn = conn
        self.reader = SignalReader(settings, catalog, conn)
        self.variants = load_variants(settings.resolve(settings.shadow.setups), catalog)
        register_variants(conn, self.variants)
        self.engine = SetupEngine(settings, self.variants, conn)
        self.tracker = Tracker(settings, conn)
        self.account = AccountEngine(settings, conn)
        self._client: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            from tradeagent.market.binance import public_client

            self._client = public_client()
        return self._client

    def shadow_step(self) -> Counter[str]:
        """Sync Binance candles, turn new snapshots into trades, and move open trades forward. Blocking."""
        counts: Counter[str] = Counter()
        synced = sync_all(self.settings, self.conn, self.client, self.reader.clock.now_ms())
        counts["candles_added"] = sum(n for name, n in synced.items() if not name.endswith("funding"))
        counts.update(self.engine.process())
        counts.update(self.tracker.update())
        counts.update({f"paper_{name}": n for name, n in self.account.process().items()})
        counts["open_trades"] = self.conn.execute(
            "SELECT count(*) FROM trades WHERE book = 'exploration' AND status = 'open'"
        ).fetchone()[0]
        return counts

    async def _after_cycle(self, boundary_s: int, snaps: list[Snapshot]) -> None:
        counts = self.shadow_step()
        message = (
            f"shadow: {counts['candles']} candles, {counts['triggers']} triggers, "
            f"{counts['trades_taken']} taken, {counts['trades_counterfactual']} counterfactual, "
            f"{counts['closed']} closed, {counts['open_trades']} open | paper: {counts['paper_opened']} opened, "
            f"{counts['paper_rejected']} rejected, {counts['paper_settled']} settled"
        )
        log.info(message)
        if counts["no_entry_candle"]:
            log_event(self.conn, "WARNING", "engine", f"{counts['no_entry_candle']} candles had no Binance entry candle")

    async def _hourly(self) -> None:
        sync_market_info(self.conn, self.client, {s: c.ccxt for s, c in self.settings.exchange.symbols.items()})

    async def run(self, *, stop: asyncio.Event | None = None, max_cycles: int | None = None) -> None:
        log.info("agent starting: catching up market data and shadow trades")
        try:
            await self._hourly()  # market info first: the paper account sizes orders with the step sizes
            counts = self.shadow_step()
            log.info("catch-up done: %s", dict(counts))
        except Exception as exc:  # no internet yet, for example: start reading anyway, later cycles catch up
            log.exception("catch-up failed")
            log_event(self.conn, "ERROR", "agent", f"catch-up failed: {exc}")
        await self.reader.run(stop=stop, max_cycles=max_cycles, after_cycle=self._after_cycle, hourly=self._hourly)
