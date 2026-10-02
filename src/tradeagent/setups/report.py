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


def variant_report(conn: sqlite3.Connection, book: str = "exploration") -> list[dict[str, Any]]:
    report = []
    variants = conn.execute(
        "SELECT id, role FROM variants WHERE role != 'retired' ORDER BY CASE role WHEN 'baseline' THEN 0 ELSE 1 END, id"
    ).fetchall()
    for v in variants:
        closed = conn.execute(
            "SELECT r_net, fees_r, ambiguous FROM trades WHERE book = ? AND variant_id = ? AND status = 'closed'"
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
                SUM(status = 'invalid')
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
                "avg_fees_r": sum(r["fees_r"] for r in closed) / len(closed) if closed else None,
                "ambiguous": sum(r["ambiguous"] for r in closed),
            }
        )
        report.append(row)
    return report
