"""Indicator snapshots: validation, storage, and signal versions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from tradeagent.journal.db import now_ms
from tradeagent.tv.schedule import TF_SECONDS, TV_INTERVAL


@dataclass
class Snapshot:
    symbol: str  # agent symbol, e.g. XRP
    timeframe: str  # e.g. 5m
    bar_time_ms: int  # candle open time
    signal_version: int
    read_at_ms: int  # Binance server time
    values: dict[str, dict[str, Any]] = field(default_factory=dict)
    ohlcv: list[float] | None = None
    problems: list[str] = field(default_factory=list)
    source: str = "live"  # live (read at the candle close) | backfill (read later from loaded history)

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def latency_ms(self) -> int:
        """Delay between the candle close and the read."""
        return self.read_at_ms - (self.bar_time_ms + TF_SECONDS[self.timeframe] * 1000)


def build_snapshot(
    raw: dict[str, Any] | None,
    *,
    symbol: str,
    timeframe: str,
    tradingview_symbol: str,
    bar_time_s: int,
    signal_version: int,
    read_at_ms: int,
    spec: dict[str, Any],
) -> Snapshot:
    """Turn the in-page read result into a Snapshot, recording every problem found."""
    snap = Snapshot(symbol, timeframe, bar_time_s * 1000, signal_version, read_at_ms)
    if not isinstance(raw, dict):
        snap.problems.append(f"no result from TradingView: {raw!r}")
        return snap
    if raw.get("error"):
        snap.problems.append(str(raw["error"]))
    snap.problems.extend(raw.get("problems") or [])
    if raw.get("symbol") != tradingview_symbol:
        snap.problems.append(f"chart shows {raw.get('symbol')}, expected {tradingview_symbol}")
    if raw.get("interval") != TV_INTERVAL[timeframe]:
        snap.problems.append(f"chart interval {raw.get('interval')}, expected {TV_INTERVAL[timeframe]}")
    if raw.get("series_status") != 3 or raw.get("is_loading"):
        snap.problems.append("chart was still loading")
    snap.ohlcv = raw.get("ohlcv")
    snap.values = raw.get("values") or {}
    for key, indicator in spec.items():
        for f in indicator["fields"]:
            if f["name"] not in snap.values.get(key, {}):
                snap.problems.append(f"missing {key}.{f['name']}")
    # Keep the list readable when a whole study is missing.
    snap.problems = list(dict.fromkeys(snap.problems))
    return snap


def failed_snapshot(
    symbol: str, timeframe: str, bar_time_s: int, signal_version: int, read_at_ms: int, problem: str
) -> Snapshot:
    return Snapshot(symbol, timeframe, bar_time_s * 1000, signal_version, read_at_ms, problems=[problem])


def store_snapshot(conn: sqlite3.Connection, snap: Snapshot) -> None:
    """Insert, or replace an earlier failed read (or a backfilled one, with a good live read).

    A good live snapshot is never overwritten.
    """
    store_snapshots(conn, [snap])


def store_snapshots(conn: sqlite3.Connection, snaps: list[Snapshot]) -> None:
    rows = []
    for snap in snaps:
        o = snap.ohlcv if snap.ohlcv and len(snap.ohlcv) == 5 else [None] * 5
        rows.append(
            (
                snap.symbol, snap.timeframe, snap.bar_time_ms, snap.signal_version, *o,
                json.dumps(snap.values, sort_keys=True), json.dumps(snap.problems) if snap.problems else None,
                snap.read_at_ms, snap.latency_ms, snap.source,
            )
        )
    with conn:
        conn.executemany(
            """
            INSERT INTO snapshots (symbol, timeframe, bar_time, signal_version, open, high, low, close, volume,
                                   values_json, problems_json, read_at, latency_ms, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (symbol, timeframe, bar_time, signal_version) DO UPDATE SET
                open = excluded.open, high = excluded.high, low = excluded.low, close = excluded.close,
                volume = excluded.volume, values_json = excluded.values_json,
                problems_json = excluded.problems_json, read_at = excluded.read_at,
                latency_ms = excluded.latency_ms, source = excluded.source
            WHERE snapshots.problems_json IS NOT NULL
               OR (snapshots.source = 'backfill' AND excluded.source = 'live' AND excluded.problems_json IS NULL)
            """,
            rows,
        )


def settings_fingerprint(inputs: Any) -> tuple[str, str]:
    """sha256 and canonical JSON of the indicator inputs."""
    canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), canonical


def resolve_signal_version(conn: sqlite3.Connection, configured: int, fingerprint: str, canonical: str) -> tuple[int, bool]:
    """Return (signal version for these inputs, whether they differ from the newest known version).

    The first inputs ever seen get the configured version. Known inputs get their recorded version.
    Unknown inputs get a new version number (newest + 1).
    """
    row = conn.execute("SELECT signal_version FROM indicator_settings WHERE settings_hash = ?", (fingerprint,)).fetchone()
    newest = conn.execute("SELECT max(signal_version) FROM indicator_settings").fetchone()[0]
    if row:
        return row[0], row[0] != newest
    version = configured if newest is None else newest + 1
    with conn:
        conn.execute(
            "INSERT INTO indicator_settings (signal_version, settings_hash, settings_json, created_at) VALUES (?, ?, ?, ?)",
            (version, fingerprint, canonical, now_ms()),
        )
    return version, newest is not None
