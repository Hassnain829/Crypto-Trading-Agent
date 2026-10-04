"""Live preview: replay the baseline's shadow trades through a set of account limits, in memory.

Shows what an account with those limits (max positions, per coin, daily loss stop, risk, leverage) would
have done with the same signals and fills. Nothing is written to the journal.
"""

from __future__ import annotations

import sqlite3
import time
from collections import Counter
from typing import Any

from tradeagent.config import PaperAccountConfig, Settings
from tradeagent.journal import migrate


def _copy(src: sqlite3.Connection, dst: sqlite3.Connection, table: str, where: str = "", params: tuple = ()) -> int:
    rows = src.execute(f"SELECT * FROM {table} {where}", params).fetchall()
    if rows:
        cols = rows[0].keys()
        dst.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [tuple(r) for r in rows])
    return len(rows)


def live_preview(conn: sqlite3.Connection, settings: Settings, rules: PaperAccountConfig | None = None,
                 since: int | None = None) -> dict[str, Any]:
    from tradeagent.account.engine import ACCOUNT, AccountEngine

    rules = rules or settings.live_account
    baseline = conn.execute("SELECT id FROM variants WHERE role = 'baseline'").fetchone()
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    migrate(mem)
    signals = 0
    if baseline:
        _copy(conn, mem, "variants", "WHERE id = ?", (baseline[0],))
        _copy(conn, mem, "market_info")
        signals = _copy(conn, mem, "trades", "WHERE book = 'exploration' AND variant_id = ? AND taken = 1"
                        " AND status IN ('open', 'closed') AND entry_time >= ?", (baseline[0], since or 0))
        _copy(conn, mem, "candles", "WHERE timeframe = '1m' AND open_time = (SELECT max(c.open_time) FROM candles c"
              " WHERE c.symbol = candles.symbol AND c.timeframe = '1m')")
        mem.commit()
    replay = settings.model_copy(deep=True)
    replay.paper_account = PaperAccountConfig(**{k: getattr(rules, k) for k in PaperAccountConfig.model_fields})
    AccountEngine(replay, mem).process()

    closed = mem.execute("SELECT pnl_usd, r_net, fees_usd, balance_after, exit_time FROM account_trades"
                         " WHERE account = ? AND status = 'closed' ORDER BY exit_time, id", (ACCOUNT,)).fetchall()
    rejected = Counter(r[0] for r in mem.execute(
        "SELECT reject_reason FROM account_trades WHERE account = ? AND status = 'rejected'", (ACCOUNT,)))
    state = mem.execute("SELECT balance FROM account_state WHERE account = ?", (ACCOUNT,)).fetchone()
    start = rules.starting_balance
    balance = state["balance"] if state else start
    peak, max_dd, curve = start, 0.0, []
    for r in closed:
        peak = max(peak, r["balance_after"])
        max_dd = max(max_dd, (peak - r["balance_after"]) / peak)
        curve.append((r["exit_time"], r["balance_after"]))
    first = mem.execute("SELECT min(entry_time) FROM trades").fetchone()[0]
    days = max((time.time() * 1000 - (since or first or time.time() * 1000)) / 86_400_000, 1e-9)
    wins = [r["pnl_usd"] for r in closed if r["pnl_usd"] > 0]
    losses = -sum(r["pnl_usd"] for r in closed if r["pnl_usd"] < 0)
    mem.close()
    return {
        "signals": signals,
        "taken": len(closed),
        "balance": balance,
        "return_pct": (balance - start) / start * 100,
        "net_pnl": balance - start,
        "win_rate": len(wins) / len(closed) if closed else None,
        "expectancy_r": sum(r["r_net"] for r in closed) / len(closed) if closed else None,
        "profit_factor": sum(wins) / losses if losses else None,
        "max_drawdown": max_dd,
        "fees_usd": sum(r["fees_usd"] for r in closed),
        "trades_per_day": len(closed) / days if closed else 0.0,
        "skipped": dict(rejected.most_common()),
        "equity": curve,
        "start_balance": start,
    }
