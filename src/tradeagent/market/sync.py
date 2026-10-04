"""Keeps the journal's market data of the trading venue current: candles, gap repair, funding and market info."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from tradeagent.config import Settings
from tradeagent.market.candles import ensure_venue, repair_gaps, sync_candles, sync_funding, sync_market_info

log = logging.getLogger("tradeagent.market")

GAP_CHECK_MS = 2 * 86_400_000  # re-check the last two days for holes on every sync


def sync_all(settings: Settings, conn: sqlite3.Connection, client: Any, now: int, *, with_info: bool = False,
             backfill_pages: int | None = None) -> dict[str, int]:
    """Bring candles (and funding, and optionally market info) up to the newest closed candle.
    `backfill_pages` limits how much older history one call downloads (the agent passes a limit)."""
    counts: dict[str, int] = {}
    days = settings.market_data.history_days
    if ensure_venue(conn, settings.venue):
        with_info = True
    for symbol, market in settings.markets().items():
        for tf in settings.market_data.candle_timeframes:
            added = sync_candles(conn, client, symbol, market, tf, now, days, backfill_pages)
            added += repair_gaps(conn, client, symbol, market, tf, now - GAP_CHECK_MS, now)
            counts[f"{symbol} {tf}"] = added
        counts[f"{symbol} funding"] = sync_funding(conn, client, symbol, market, now, days)
    if with_info or conn.execute("SELECT count(*) FROM market_info").fetchone()[0] < len(settings.exchange.symbols):
        sync_market_info(conn, client, settings.markets())
    return counts
