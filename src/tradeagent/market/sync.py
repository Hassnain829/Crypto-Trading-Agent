"""Keeps the journal's Binance market data current: candles, gap repair, funding and market info."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from tradeagent.config import Settings
from tradeagent.market.candles import repair_gaps, sync_candles, sync_funding, sync_market_info

log = logging.getLogger("tradeagent.market")

GAP_CHECK_MS = 2 * 86_400_000  # re-check the last two days for holes on every sync


def sync_all(settings: Settings, conn: sqlite3.Connection, client: Any, now: int, *, with_info: bool = False) -> dict[str, int]:
    """Bring candles (and funding, and optionally market info) up to the newest closed candle."""
    counts: dict[str, int] = {}
    days = settings.market_data.history_days
    for symbol, cfg in settings.exchange.symbols.items():
        for tf in settings.market_data.candle_timeframes:
            added = sync_candles(conn, client, symbol, cfg.ccxt, tf, now, days)
            added += repair_gaps(conn, client, symbol, cfg.ccxt, tf, now - GAP_CHECK_MS, now)
            counts[f"{symbol} {tf}"] = added
        counts[f"{symbol} funding"] = sync_funding(conn, client, symbol, cfg.ccxt, now, days)
    if with_info:
        sync_market_info(conn, client, {s: c.ccxt for s, c in settings.exchange.symbols.items()})
    return counts
