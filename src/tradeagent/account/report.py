"""Paper account results, the consistency check and the go-live gate (docs/GOALS-AND-METRICS.md)."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from tradeagent.account.engine import ACCOUNT, AccountEngine
from tradeagent.config import Settings
from tradeagent.tv.coverage import coverage


def consistency_issues(conn: sqlite3.Connection) -> tuple[int, list[str]]:
    """Every paper trade must follow a taken exploration trade of the same variant, with the same result in R."""
    rows = conn.execute(
        """
        SELECT a.id, a.trade_id, a.variant_id, a.symbol, a.timeframe, a.side, a.entry_time, a.status,
               a.exit_time, a.exit_reason, a.r_net,
               t.id AS t_id, t.book AS t_book, t.variant_id AS t_variant_id, t.symbol AS t_symbol,
               t.timeframe AS t_timeframe, t.side AS t_side, t.entry_time AS t_entry_time, t.taken AS t_taken,
               t.status AS t_status, t.exit_time AS t_exit_time, t.r_net AS t_r_net
        FROM account_trades a LEFT JOIN trades t ON t.id = a.trade_id
        WHERE a.account = ? AND a.status != 'rejected' ORDER BY a.id
        """,
        (ACCOUNT,),
    ).fetchall()
    issues = []
    for r in rows:
        name = f"paper #{r['id']} (exploration #{r['trade_id']})"
        if r["t_id"] is None:
            issues.append(f"{name}: exploration trade missing")
            continue
        for field in ("variant_id", "symbol", "timeframe", "side", "entry_time"):
            if r[field] != r[f"t_{field}"]:
                issues.append(f"{name}: {field} {r[field]} != {r[f't_{field}']}")
        if r["t_book"] != "exploration" or r["t_taken"] != 1:
            issues.append(f"{name}: not a taken exploration trade")
        if r["status"] == "open" and r["t_status"] == "closed":
            issues.append(f"{name}: the exploration trade closed but the paper position is still open")
        if r["status"] == "closed" and r["exit_reason"] != "kill switch":
            if r["t_status"] != "closed" or r["exit_time"] != r["t_exit_time"]:
                issues.append(f"{name}: exit differs from the exploration trade")
            elif abs(r["r_net"] - r["t_r_net"]) > 1e-6:
                issues.append(f"{name}: {r['r_net']:+.6f}R, exploration {r['t_r_net']:+.6f}R")
    return len(rows), issues


def account_report(conn: sqlite3.Connection, settings: Settings) -> dict[str, Any]:
    start = settings.paper_account.starting_balance
    state = conn.execute("SELECT balance FROM account_state WHERE account = ?", (ACCOUNT,)).fetchone()
    balance = state["balance"] if state else start
    closed = conn.execute(
        "SELECT pnl_usd, r_net, fees_usd, balance_after FROM account_trades"
        " WHERE account = ? AND status = 'closed' ORDER BY exit_time, id",
        (ACCOUNT,),
    ).fetchall()
    rejected = conn.execute(
        "SELECT reject_reason, count(*) FROM account_trades WHERE account = ? AND status = 'rejected'"
        " GROUP BY reject_reason ORDER BY 2 DESC",
        (ACCOUNT,),
    ).fetchall()
    stop_days = conn.execute(
        "SELECT count(DISTINCT date(entry_time / 1000, 'unixepoch')) FROM account_trades"
        " WHERE account = ? AND reject_reason LIKE 'daily loss stop%'",
        (ACCOUNT,),
    ).fetchone()[0]
    first_entry = conn.execute(
        "SELECT min(entry_time) FROM account_trades WHERE account = ? AND status != 'rejected'", (ACCOUNT,)
    ).fetchone()[0]
    unexplained = conn.execute(  # every trade needs its indicator snapshot and reason (the context at confirmation)
        "SELECT count(*) FROM account_trades a LEFT JOIN trades t ON t.id = a.trade_id"
        " WHERE a.account = ? AND a.status != 'rejected' AND coalesce(t.context_json, '{}') = '{}'",
        (ACCOUNT,),
    ).fetchone()[0]
    positions = AccountEngine(settings, conn).mark_to_market()

    pnls = [r["pnl_usd"] for r in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    peak, max_dd = start, 0.0
    for r in closed:
        peak = max(peak, r["balance_after"])
        max_dd = max(max_dd, (peak - r["balance_after"]) / peak)
    days = (time.time() * 1000 - first_entry) / 86_400_000 if first_entry else 0.0
    expectancy = sum(r["r_net"] for r in closed) / len(closed) if closed else None
    profit_factor = sum(wins) / -sum(losses) if losses else None
    checked, issues = consistency_issues(conn)

    now = int(time.time() * 1000)
    rows = coverage(conn, settings.exchange.symbols, settings.all_timeframes, now - 7 * 86_400_000, now)
    expected = sum(r["expected"] for r in rows)
    snapshot_coverage = sum(r["ok"] for r in rows) / expected if expected else 0.0

    goal = settings.goal
    gate = [
        ("closed trades", f"{len(closed)} / {goal.min_trades}", len(closed) >= goal.min_trades),
        ("days running", f"{days:.1f} / {goal.min_days}", days >= goal.min_days),
        ("net PnL > 0", f"{balance - start:+.2f} USDT", balance > start),
        ("expectancy", f"{expectancy:+.3f}R / {goal.min_expectancy_r:+.2f}R" if expectancy is not None else "-",
         expectancy is not None and expectancy >= goal.min_expectancy_r),
        ("profit factor", f"{profit_factor:.2f} / {goal.min_profit_factor}" if profit_factor is not None else "-",
         profit_factor is not None and profit_factor >= goal.min_profit_factor),
        ("max drawdown", f"{max_dd:.1%} / {goal.max_drawdown:.0%}", max_dd <= goal.max_drawdown),
        ("snapshot coverage (7 days, live)", f"{snapshot_coverage:.1%} / {goal.min_snapshot_coverage:.0%}",
         snapshot_coverage >= goal.min_snapshot_coverage),
        ("every trade explained (snapshot + reason)", f"{unexplained} without", unexplained == 0),
        ("paper = exploration (consistency)", f"{checked - len(issues)}/{checked} match", not issues),
    ]
    return {
        "starting_balance": start,
        "balance": balance,
        "equity": balance + sum(p["unrealized_usd"] for p in positions),
        "return_pct": (balance - start) / start * 100,
        "closed": len(closed),
        "positions": positions,
        "win_rate": len(wins) / len(closed) if closed else None,
        "expectancy_r": expectancy,
        "profit_factor": profit_factor,
        "max_drawdown_pct": max_dd * 100,
        "fees_usd": sum(r["fees_usd"] for r in closed),
        "rejected": [(r[0], r[1]) for r in rejected],
        "daily_stop_days": stop_days,
        "consistency_issues": issues,
        "gate": gate,
        "gate_met": all(ok for _, _, ok in gate),
    }
