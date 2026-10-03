"""Per-variant results of a trade book."""

from __future__ import annotations

import sqlite3
from typing import Any


def summarize(r_values: list[float]) -> dict[str, Any]:
    """Statistics of closed trades, in time order of their exit."""
    n = len(r_values)
    wins = [r for r in r_values if r > 0]
    losses = [r for r in r_values if r < 0]
    equity = peak = drawdown = 0.0
    for r in r_values:
        equity += r
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "trades": n,
        "win_rate": len(wins) / n if n else None,
        "expectancy_r": sum(r_values) / n if n else None,
        "total_r": sum(r_values),
        "profit_factor": sum(wins) / -sum(losses) if losses else None,
        "max_drawdown_r": drawdown,
    }


def variant_report(conn: sqlite3.Connection, book: str = "exploration", split_time: int | None = None) -> list[dict[str, Any]]:
    """One row per active variant. With `split_time`, also the expectancy before and after it (stability check)."""
    report = []
    variants = conn.execute(
        "SELECT id, role FROM variants WHERE role != 'retired' ORDER BY CASE role WHEN 'baseline' THEN 0 ELSE 1 END, id"
    ).fetchall()
    for v in variants:
        closed = conn.execute(
            "SELECT r_net, fees_r, ambiguous, entry_time FROM trades WHERE book = ? AND variant_id = ? AND status = 'closed'"
            " AND taken = 1 ORDER BY exit_time",
            (book, v["id"]),
        ).fetchall()
        row = summarize([r["r_net"] for r in closed])
        counts = conn.execute(
            """
            SELECT
                SUM(status = 'open' AND taken = 1),
                SUM(status = 'closed' AND taken = 0),
                AVG(CASE WHEN status = 'closed' AND taken = 0 THEN r_net END),
                SUM(status = 'invalid'),
                SUM(status = 'missed')
            FROM trades WHERE book = ? AND variant_id = ?
            """,
            (book, v["id"]),
        ).fetchone()
        row.update(
            {
                "variant": v["id"],
                "role": v["role"],
                "open": counts[0] or 0,
                "counterfactual": counts[1] or 0,
                "counterfactual_expectancy_r": counts[2],
                "invalid": counts[3] or 0,
                "missed": counts[4] or 0,
                "avg_fees_r": sum(r["fees_r"] for r in closed) / len(closed) if closed else None,
                "ambiguous": sum(r["ambiguous"] for r in closed),
            }
        )
        if split_time is not None:
            for half, part in (("first", [r["r_net"] for r in closed if r["entry_time"] < split_time]),
                               ("second", [r["r_net"] for r in closed if r["entry_time"] >= split_time])):
                row[f"{half}_trades"] = len(part)
                row[f"{half}_expectancy_r"] = sum(part) / len(part) if part else None
        report.append(row)
    return report


def baseline_median_entry(conn: sqlite3.Connection, book: str = "exploration") -> int | None:
    """Entry time that splits the baseline's closed trades into two equal halves."""
    times = [r[0] for r in conn.execute(
        "SELECT t.entry_time FROM trades t JOIN variants v ON v.id = t.variant_id"
        " WHERE v.role = 'baseline' AND t.book = ? AND t.status = 'closed' AND t.taken = 1 ORDER BY t.entry_time",
        (book,),
    )]
    return times[len(times) // 2] if times else None
