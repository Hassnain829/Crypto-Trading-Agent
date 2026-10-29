"""Import the baseline's trades from a replay of the agent's own data, so the go-live gate can count them.

The replay comes from research/tools/gate_replay.py: the agent's own TradingView snapshots and Binance candles run
through the agent's engine and tracker. Its trades are stored here under the variant "replay-<baseline id>" with the
baseline's exact rules (same params hash) and role "retired": the shadow engine and the demo account never touch them,
and the gate (account/report.forward_trades) counts trades by the rules' hash, one per signal, from goal.count_from.

Only trades that entered before the baseline's own first trade are imported (or before `before`), so a signal is
never counted twice. A new import replaces the previous one.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tradeagent.journal.db import now_ms


def import_replay(conn: sqlite3.Connection, replay: Path, before: int | None = None) -> tuple[str, int]:
    """(variant id, trades imported). Raises ValueError when the replay has no variant with the baseline's rules."""
    base = conn.execute("SELECT id, params_json, params_hash FROM variants WHERE role = 'baseline'").fetchone()
    if base is None:
        raise ValueError("there is no baseline variant in this journal")
    src = sqlite3.connect(f"file:{replay}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        found = src.execute("SELECT id FROM variants WHERE params_hash = ?", (base["params_hash"],)).fetchone()
        if found is None:
            raise ValueError(f"{replay.name} has no variant with the baseline's rules ({base['id']}); replay it again")
        first_own = conn.execute("SELECT min(entry_time) FROM trades WHERE variant_id = ? AND entry_time IS NOT NULL",
                                 (base["id"],)).fetchone()[0]
        cutoff = min(x for x in (before, first_own, now_ms()) if x is not None)
        columns = [r[1] for r in conn.execute("PRAGMA table_info(trades)") if r[1] != "id"]
        shared = [c for c in columns if c in {r[1] for r in src.execute("PRAGMA table_info(trades)")}]
        rows = src.execute(f"SELECT {', '.join(shared)} FROM trades WHERE variant_id = ? AND entry_time < ?",
                           (found["id"], cutoff)).fetchall()
    finally:
        src.close()
    vid = f"replay-{base['id']}"
    with conn:
        conn.execute(
            "INSERT INTO variants (id, params_json, params_hash, role, parent, created_at) VALUES (?, ?, ?, 'retired', ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET params_json = excluded.params_json, params_hash = excluded.params_hash",
            (vid, base["params_json"], base["params_hash"], base["id"], now_ms()))
        conn.execute("DELETE FROM trades WHERE variant_id = ?", (vid,))
        out = []
        for r in rows:
            values = dict(r)
            values["variant_id"] = vid
            context = json.loads(values.get("context_json") or "{}")
            context["replayed_from"] = replay.name  # marks a replayed trade on the dashboard and in reports
            values["context_json"] = json.dumps(context)
            out.append(tuple(values[c] for c in shared))
        conn.executemany(f"INSERT INTO trades ({', '.join(shared)}) VALUES ({', '.join('?' * len(shared))})", out)
    return vid, len(out)
