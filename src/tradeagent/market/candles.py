"""Binance market data in the journal: closed candles, funding rates and market info."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from tradeagent.journal.db import now_ms
from tradeagent.tv.schedule import TF_SECONDS

log = logging.getLogger("tradeagent.market")

FETCH_LIMIT = 1500  # Binance USDT-M maximum per kline request


def tf_ms(timeframe: str) -> int:
    return TF_SECONDS[timeframe] * 1000


def latest_closed_open(now: int, timeframe: str) -> int:
    """Open time of the newest closed candle at `now` (ms)."""
    step = tf_ms(timeframe)
    return (now // step) * step - step


def fetch_range(client: Any, ccxt_symbol: str, timeframe: str, start: int, last_open: int) -> list[list[float]]:
    """Closed candles with open time in [start, last_open], paging through Binance's limit."""
    step = tf_ms(timeframe)
    out: list[list[float]] = []
    since = start
    while since <= last_open:
        batch = client.fetch_ohlcv(ccxt_symbol, timeframe, since=since, limit=FETCH_LIMIT)
        batch = [c for c in batch if since <= c[0] <= last_open]
        if not batch:
            break
        out.extend(batch)
        since = int(batch[-1][0]) + step
    return out


def store_candles(conn: sqlite3.Connection, symbol: str, timeframe: str, rows: list[list[float]]) -> int:
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO candles (symbol, timeframe, open_time, open, high, low, close, volume)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(symbol, timeframe, int(r[0]), r[1], r[2], r[3], r[4], r[5]) for r in rows],
        )
    return len(rows)


def sync_candles(
    conn: sqlite3.Connection, client: Any, symbol: str, ccxt_symbol: str, timeframe: str, now: int, history_days: int
) -> int:
    """Fetch every closed candle after the newest stored one, and before the oldest one if `history_days`
    reaches further back than the stored history (for example after it was raised). Returns rows added."""
    step = tf_ms(timeframe)
    oldest, newest = conn.execute(
        "SELECT min(open_time), max(open_time) FROM candles WHERE symbol = ? AND timeframe = ?", (symbol, timeframe)
    ).fetchone()
    first_wanted = ((now - history_days * 86_400_000) // step) * step
    last_open = latest_closed_open(now, timeframe)
    added = 0
    if oldest is not None and oldest > first_wanted:
        added += store_candles(conn, symbol, timeframe, fetch_range(client, ccxt_symbol, timeframe, first_wanted, oldest - step))
    start = newest + step if newest is not None else first_wanted
    if start <= last_open:
        added += store_candles(conn, symbol, timeframe, fetch_range(client, ccxt_symbol, timeframe, start, last_open))
    return added


def find_gaps(conn: sqlite3.Connection, symbol: str, timeframe: str, start: int, end: int) -> list[tuple[int, int]]:
    """Missing candle ranges [first_missing_open, last_missing_open] between the stored candles in [start, end]."""
    step = tf_ms(timeframe)
    times = [
        row[0]
        for row in conn.execute(
            "SELECT open_time FROM candles WHERE symbol = ? AND timeframe = ? AND open_time BETWEEN ? AND ?"
            " ORDER BY open_time",
            (symbol, timeframe, start, end),
        )
    ]
    return [(a + step, b - step) for a, b in zip(times, times[1:]) if b - a > step]


def repair_gaps(
    conn: sqlite3.Connection, client: Any, symbol: str, ccxt_symbol: str, timeframe: str, start: int, end: int
) -> int:
    filled = 0
    for first, last in find_gaps(conn, symbol, timeframe, start, end):
        rows = fetch_range(client, ccxt_symbol, timeframe, first, last)
        filled += store_candles(conn, symbol, timeframe, rows)
        if len(rows) < (last - first) // tf_ms(timeframe) + 1:
            log.warning("%s %s: Binance has no candles for part of %s..%s", symbol, timeframe, first, last)
    return filled


def sync_funding(conn: sqlite3.Connection, client: Any, symbol: str, ccxt_symbol: str, now: int, history_days: int) -> int:
    oldest, newest = conn.execute(
        "SELECT min(funding_time), max(funding_time) FROM funding WHERE symbol = ?", (symbol,)
    ).fetchone()
    first_wanted = now - history_days * 86_400_000
    # Older history is wanted (first sync, or history_days was raised): fetch from there; rows are upserted.
    since = first_wanted if newest is None or oldest > first_wanted + 86_400_000 else newest + 1
    added = 0
    while True:
        rates = client.fetch_funding_rate_history(ccxt_symbol, since=since, limit=1000)
        rates = [r for r in rates if r.get("timestamp") and r["timestamp"] >= since]
        if not rates:
            break
        with conn:
            conn.executemany(
                "INSERT OR REPLACE INTO funding (symbol, funding_time, rate) VALUES (?, ?, ?)",
                [(symbol, int(r["timestamp"]), float(r["fundingRate"])) for r in rates],
            )
        added += len(rates)
        since = int(rates[-1]["timestamp"]) + 1
        if len(rates) < 1000:
            break
    return added


def sync_market_info(conn: sqlite3.Connection, client: Any, symbols: dict[str, str]) -> None:
    """Tick size, step size and minimum order size for every agent symbol (agent name -> ccxt symbol)."""
    markets = client.load_markets()
    with conn:
        for symbol, ccxt_symbol in symbols.items():
            m = markets[ccxt_symbol]
            conn.execute(
                "INSERT OR REPLACE INTO market_info (symbol, tick_size, step_size, min_qty, min_notional, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    symbol,
                    m["precision"].get("price"),
                    m["precision"].get("amount"),
                    (m["limits"].get("amount") or {}).get("min"),
                    (m["limits"].get("cost") or {}).get("min"),
                    now_ms(),
                ),
            )
