"""The trading venue's market data in the journal: closed candles, funding rates and market info.

`client` is a venues.MarketData (or anything with the same methods). The journal holds one venue's market
data at a time: ensure_venue() clears it when the configured venue changes, and the next sync downloads the
history again.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from tradeagent.journal.db import now_ms
from tradeagent.tv.schedule import TF_SECONDS

log = logging.getLogger("tradeagent.market")

FETCH_LIMIT = 1500  # candles per request when the client does not say (Binance USDT-M maximum)
SETTLE_MS = 3 * 60_000  # a minute that still has no candle this long after it closed had no trades
VENUE_KEY = "market:venue"


def tf_ms(timeframe: str) -> int:
    return TF_SECONDS[timeframe] * 1000


def latest_closed_open(now: int, timeframe: str) -> int:
    """Open time of the newest closed candle at `now` (ms)."""
    step = tf_ms(timeframe)
    return (now // step) * step - step


def ensure_venue(conn: sqlite3.Connection, venue: str) -> bool:
    """Clear the market data if it belongs to another venue. Returns True when it was cleared.
    Journals from before venues existed hold Binance USDT-M data."""
    row = conn.execute("SELECT value FROM engine_state WHERE key = ?", (VENUE_KEY,)).fetchone()
    stored = row[0] if row else "binance-usdm"
    if stored == venue and row:
        return False
    with conn:
        if stored != venue:
            for table in ("candles", "funding", "market_info"):
                conn.execute(f"DELETE FROM {table}")
            log.warning("trading venue changed from %s to %s: market data cleared, downloading it again", stored, venue)
        conn.execute("INSERT INTO engine_state (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                     (VENUE_KEY, venue))
    return stored != venue


def _sparse(client: Any) -> bool:
    venue = getattr(client, "venue", None)
    return bool(getattr(venue, "sparse_candles", False))


def _venue_name(client: Any) -> str:
    venue = getattr(client, "venue", None)
    return getattr(venue, "id", "the exchange")


def fill_quiet(rows: list[list[float]], timeframe: str, start: int, end: int, prev_close: float | None) -> list[list[float]]:
    """Add a flat candle (open = high = low = close = the previous close, volume 0) for every candle in
    [start, end] without trades. Rows after `end` are kept as they are. Some venues send no candle when
    nothing traded; the engine and the tracker need one per minute."""
    step = tf_ms(timeframe)
    by_time = {int(r[0]): r for r in rows}
    out: list[list[float]] = []
    last = prev_close
    t = start
    while t <= end:
        r = by_time.get(t)
        if r is not None:
            out.append(r)
            last = r[4]
        elif last is not None:
            out.append([t, last, last, last, last, 0.0])
        t += step
    out.extend(r for r in rows if r[0] > end or r[0] < start)
    return sorted(out, key=lambda r: r[0])


def _close_before(conn: sqlite3.Connection, symbol: str, timeframe: str, t: int) -> float | None:
    row = conn.execute("SELECT close FROM candles WHERE symbol = ? AND timeframe = ? AND open_time < ?"
                       " ORDER BY open_time DESC LIMIT 1", (symbol, timeframe, t)).fetchone()
    return row[0] if row else None


def fetch_range(client: Any, ccxt_symbol: str, timeframe: str, start: int, last_open: int) -> list[list[float]]:
    """Closed candles with open time in [start, last_open], paging through the venue's per-request limit.
    A venue with quiet minutes may return an empty page for a span without trades, so paging moves on by
    a full page instead of stopping there."""
    step = tf_ms(timeframe)
    limit = getattr(client, "candle_limit", FETCH_LIMIT)
    out: list[list[float]] = []
    since = start
    while since <= last_open:
        batch = client.fetch_ohlcv(ccxt_symbol, timeframe, since=since, limit=limit)
        batch = [c for c in batch if since <= c[0] <= last_open]
        if not batch:
            if not _sparse(client):
                break
            since += limit * step
            continue
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
    conn: sqlite3.Connection, client: Any, symbol: str, ccxt_symbol: str, timeframe: str, now: int, history_days: int,
    backfill_pages: int | None = None,
) -> int:
    """Fetch every closed candle after the newest stored one, and before the oldest one if `history_days`
    reaches further back than the stored history (for example after it was raised). Returns rows added.

    With `backfill_pages`, older history is fetched at most that many requests at a time (the newest candles
    first), so a running agent is not blocked for long after a venue change; later syncs continue."""
    step = tf_ms(timeframe)
    oldest, newest = conn.execute(
        "SELECT min(open_time), max(open_time) FROM candles WHERE symbol = ? AND timeframe = ?", (symbol, timeframe)
    ).fetchone()
    first_wanted = ((now - history_days * 86_400_000) // step) * step
    last_open = latest_closed_open(now, timeframe)
    settled = latest_closed_open(now - SETTLE_MS, timeframe)
    if backfill_pages is not None:
        span = backfill_pages * getattr(client, "candle_limit", FETCH_LIMIT) * step
        if newest is None:
            first_wanted = max(first_wanted, last_open - span)
        elif oldest is not None:
            first_wanted = max(first_wanted, oldest - span)
    added = 0
    if oldest is not None and oldest > first_wanted:
        rows = fetch_range(client, ccxt_symbol, timeframe, first_wanted, oldest - step)
        if _sparse(client) and rows:
            rows = fill_quiet(rows, timeframe, int(rows[0][0]), oldest - step, None)
        added += store_candles(conn, symbol, timeframe, rows)
    start = newest + step if newest is not None else first_wanted
    if start <= last_open:
        rows = fetch_range(client, ccxt_symbol, timeframe, start, last_open)
        if _sparse(client) and rows:
            first = start if newest is not None else int(rows[0][0])
            rows = fill_quiet(rows, timeframe, first, settled, _close_before(conn, symbol, timeframe, first))
        added += store_candles(conn, symbol, timeframe, rows)
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
    settled = latest_closed_open(now_ms() - SETTLE_MS, timeframe)
    for first, last in find_gaps(conn, symbol, timeframe, start, end):
        rows = fetch_range(client, ccxt_symbol, timeframe, first, last)
        if _sparse(client):
            rows = fill_quiet(rows, timeframe, first, min(last, settled), _close_before(conn, symbol, timeframe, first))
        filled += store_candles(conn, symbol, timeframe, rows)
        if len(rows) < (last - first) // tf_ms(timeframe) + 1 and not _sparse(client):
            log.warning("%s %s: %s has no candles for part of %s..%s", symbol, timeframe, _venue_name(client), first, last)
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
    """Tick size, order step, minimum order and contract size for every agent symbol (agent name -> market).
    Step and minimum are in the market's order unit: contracts on contract markets, coins otherwise;
    contract_size converts contracts to coins."""
    with conn:
        for symbol, ref in symbols.items():
            m = client.market(ref) if hasattr(client, "market") else client.load_markets()[ref]
            conn.execute(
                "INSERT OR REPLACE INTO market_info (symbol, tick_size, step_size, min_qty, min_notional, contract_size,"
                " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    symbol,
                    m["precision"].get("price"),
                    m["precision"].get("amount") or 1.0,
                    (m["limits"].get("amount") or {}).get("min"),
                    (m["limits"].get("cost") or {}).get("min"),
                    float(m.get("contractSize") or 1.0),
                    now_ms(),
                ),
            )
