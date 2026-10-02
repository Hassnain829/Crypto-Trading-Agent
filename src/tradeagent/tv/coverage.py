"""Snapshot coverage and latency over a time window (Phase 1 exit criteria)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from typing import Any

from tradeagent.tv.schedule import TF_SECONDS


def expected_bars(start_ms: int, end_ms: int, timeframe: str) -> list[int]:
    """Open times of the candles that closed inside (start_ms, end_ms]."""
    tf_ms = TF_SECONDS[timeframe] * 1000
    first = (start_ms // tf_ms) * tf_ms
    return [t for t in range(first, end_ms, tf_ms) if start_ms < t + tf_ms <= end_ms]


def _percentile(sorted_values: list[int], q: float) -> float | None:
    if not sorted_values:
        return None
    return sorted_values[round(q * (len(sorted_values) - 1))] / 1000


def coverage(
    conn: sqlite3.Connection, symbols: Iterable[str], timeframes: Iterable[str], start_ms: int, end_ms: int
) -> list[dict[str, Any]]:
    report = []
    for symbol in symbols:
        for tf in timeframes:
            expected = expected_bars(start_ms, end_ms, tf)
            rows = {
                bar_time: (ok, latency)
                for bar_time, ok, latency in conn.execute(
                    """
                    SELECT bar_time, MAX(problems_json IS NULL),
                           MIN(CASE WHEN problems_json IS NULL THEN latency_ms END)
                    FROM snapshots WHERE symbol = ? AND timeframe = ? AND bar_time >= ? AND bar_time < ?
                      AND source = 'live'
                    GROUP BY bar_time
                    """,
                    (symbol, tf, expected[0] if expected else start_ms, end_ms),
                )
            }
            latencies = sorted(rows[t][1] for t in expected if t in rows and rows[t][0] == 1)
            failed = sum(1 for t in expected if t in rows and rows[t][0] == 0)
            report.append(
                {
                    "symbol": symbol,
                    "timeframe": tf,
                    "expected": len(expected),
                    "ok": len(latencies),
                    "failed": failed,
                    "missing": len(expected) - len(latencies) - failed,
                    "coverage": len(latencies) / len(expected) if expected else 1.0,
                    "latency_p50_s": _percentile(latencies, 0.5),
                    "latency_p95_s": _percentile(latencies, 0.95),
                    "latency_max_s": latencies[-1] / 1000 if latencies else None,
                }
            )
    return report
