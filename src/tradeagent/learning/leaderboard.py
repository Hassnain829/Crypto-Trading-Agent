"""Leaderboard: every active strategy on the same demo rules, forward and on the long research history.

Forward: the variant's shadow trades since the demo started (or since the variant was added, if later), replayed
through today's demo rules with the live-preview replay (in memory). Long history: the stored result of
learning/long_screen.backtest (the agent fills it in the background). The demo account itself still follows only
the baseline; this is a comparison, and a short forward lead is no proof (many strategies make lucky leaders).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from tradeagent.account.preview import live_preview
from tradeagent.config import Settings

_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
CACHE_S = 1800  # ~20 s of Python in the dashboard process: not more often than needed


def leaderboard(journal: Path, settings: Settings) -> list[dict[str, Any]]:
    """One row per active variant (the baseline first). Opens its own connection: safe in a worker thread."""
    hit = _CACHE.get(str(journal))
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    conn = sqlite3.connect(journal, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        state = conn.execute("SELECT started_at FROM account_state WHERE account = 'paper'").fetchone()
        start = (state["started_at"] if state else None) or 0
        try:
            long = {r["variant_id"]: json.loads(r["result_json"]) for r in conn.execute("SELECT variant_id, result_json FROM long_results")}
        except sqlite3.OperationalError:  # an older journal without the table
            long = {}
        rows = []
        for v in conn.execute("SELECT id, role, created_at FROM variants WHERE role != 'retired'"
                              " ORDER BY CASE role WHEN 'baseline' THEN 0 ELSE 1 END, id").fetchall():
            since = max(start, v["created_at"] or 0)
            fwd = live_preview(conn, settings, settings.paper_account, since=since, variant_id=v["id"])
            lr = long.get(v["id"])
            row = {
                "variant": v["id"], "name": v["id"].rsplit("-", 1)[0], "role": v["role"], "since": since,
                "fwd_trades": fwd["taken"], "fwd_exp": fwd["expectancy_r"], "fwd_return": fwd["return_pct"],
                "fwd_dd": fwd["max_drawdown"],
                "long_trades": None, "long_exp": None, "long_h1": None, "long_h2": None, "long_return": None, "long_dd": None,
                "long_period": None,
            }
            if lr:
                row.update(long_trades=lr["all"]["trades"], long_exp=lr["all"]["expectancy_r"],
                           long_h1=lr["halves"][0]["expectancy_r"], long_h2=lr["halves"][1]["expectancy_r"],
                           long_return=lr["account"]["all"]["return_pct"], long_dd=lr["account"]["all"]["max_drawdown"],
                           long_period=lr["period"])
            rows.append(row)
    finally:
        conn.close()
    _CACHE[str(journal)] = (time.monotonic(), rows)
    return rows
