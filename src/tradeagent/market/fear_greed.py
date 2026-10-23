"""The Crypto Fear & Greed Index (alternative.me): one value a day, 0 (extreme fear) to 100 (extreme greed).

Research 2026-10-21 (research/notes/2026-10-21-news-proxies.md): the planned design's trades in the extremes
(below 20 or above 80) did worse on 4 years of XRP/SOL/ETH and on 1.5 years of ten other coins. The setup engine can
skip them (filters.fear_greed_extremes; approved by the user as an outside input, like open interest).
Stored in the journal table `fear_greed` (time = the day's start, ms UTC). Market data, not an indicator.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import urllib.request
from typing import Any

log = logging.getLogger("tradeagent.market")

URL = "https://api.alternative.me/fng/?limit={limit}&format=json"
DAY_MS = 86_400_000


def parse(payload: bytes | str) -> list[tuple[int, int, str]]:
    """(day start ms, value, classification) rows from the API's JSON."""
    data: Any = json.loads(payload)
    return [(int(d["timestamp"]) * 1000, int(d["value"]), str(d.get("value_classification") or "")) for d in data.get("data") or []]


def sync_fear_greed(conn: sqlite3.Connection, now: int, timeout_s: float = 20.0) -> int:
    """Fetch the newest values once a day (the whole history the first time). Returns rows written."""
    newest = conn.execute("SELECT max(time) FROM fear_greed").fetchone()[0]
    if newest is not None and newest >= now // DAY_MS * DAY_MS:
        return 0  # today's value is stored
    limit = 0 if newest is None else max(2, (now - newest) // DAY_MS + 2)
    with urllib.request.urlopen(URL.format(limit=limit), timeout=timeout_s) as response:
        rows = parse(response.read())
    with conn:
        conn.executemany("INSERT OR REPLACE INTO fear_greed (time, value, classification) VALUES (?, ?, ?)", rows)
    return len(rows)


def value_at(conn: sqlite3.Connection, at: int, max_age_ms: int = 2 * DAY_MS) -> int | None:
    """The index known at `at` (the newest daily value at or before it); None if missing or stale."""
    row = conn.execute("SELECT time, value FROM fear_greed WHERE time <= ? ORDER BY time DESC LIMIT 1", (at,)).fetchone()
    if row is None or at - row[0] > max_age_ms:
        return None
    return int(row[1])
