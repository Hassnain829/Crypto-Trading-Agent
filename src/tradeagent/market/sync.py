"""Keeps the journal's market data of the trading venue current: candles, gap repair, funding and market info."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from tradeagent.config import Settings
from tradeagent.market.candles import (ensure_venue, repair_gaps, sync_candles, sync_funding, sync_market_info,
                                      sync_open_interest)
from tradeagent.market.fear_greed import sync_fear_greed

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
        try:  # the OI quality flag is a convenience: a failure must not stop the candles
            counts[f"{symbol} oi"] = sync_open_interest(conn, client, symbol, market, now)
        except Exception as exc:
            log.warning("open interest of %s not synced: %s", symbol, " ".join(str(exc).split())[:200])
    if settings.venue == "binance-usdm":  # reference markets (BTC) as 5m candles, for the BTC-shock filter
        for symbol, market in settings.market_data.reference_markets.items():
            if symbol in settings.markets():
                continue  # traded anyway
            try:
                counts[f"{symbol} 5m"] = sync_candles(conn, client, symbol, market, "5m", now, min(days, 7), backfill_pages)
            except Exception as exc:
                log.warning("reference market %s not synced: %s", symbol, " ".join(str(exc).split())[:200])
    if settings.market_data.fear_greed:
        try:  # an outside service: a failure must not stop the candles
            counts["fear & greed"] = sync_fear_greed(conn, now)
        except Exception as exc:
            log.warning("fear & greed index not synced: %s", " ".join(str(exc).split())[:200])
    if with_info or conn.execute("SELECT count(*) FROM market_info").fetchone()[0] < len(settings.exchange.symbols):
        sync_market_info(conn, client, settings.markets())
    return counts
