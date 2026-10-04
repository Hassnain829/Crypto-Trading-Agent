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


def forward_sample(conn: sqlite3.Connection, since: int | None, symbols: list[str] | None = None) -> list[float]:
    """Net R of the current baseline's closed shadow trades (every signal it took) since `since`, on the coins
    the account trades (`symbols`; None = every coin)."""
    only = f" AND t.symbol IN ({', '.join('?' * len(symbols))})" if symbols else ""
    return [r[0] for r in conn.execute(
        "SELECT t.r_net FROM trades t JOIN variants v ON v.id = t.variant_id WHERE v.role = 'baseline'"
        " AND t.book = 'exploration' AND t.taken = 1 AND t.status = 'closed' AND t.entry_time >= ?" + only,
        (since or 0, *(symbols or [])),
    )]


def account_report(conn: sqlite3.Connection, settings: Settings) -> dict[str, Any]:
    """The paper account (money view) and the go-live gate.

    The gate's sample (trade count, expectancy, profit factor) is the baseline's forward shadow trades, which
    include every signal. Net PnL and drawdown come from the live preview: the same trades replayed through
    the live limits (settings live_account), because the demo account itself may have no limits.
    """
    from tradeagent.account.preview import live_preview

    start = settings.paper_account.starting_balance
    state = conn.execute("SELECT balance, started_at FROM account_state WHERE account = ?", (ACCOUNT,)).fetchone()
    balance = state["balance"] if state else start
    started_at = state["started_at"] if state else None
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
    begin = started_at or first_entry
    days = (time.time() * 1000 - begin) / 86_400_000 if begin else 0.0
    expectancy = sum(r["r_net"] for r in closed) / len(closed) if closed else None
    profit_factor = sum(wins) / -sum(losses) if losses else None
    sample = forward_sample(conn, started_at, settings.paper_account.symbols)
    sample_exp = sum(sample) / len(sample) if sample else None
    sample_losses = -sum(r for r in sample if r < 0)
    sample_pf = sum(r for r in sample if r > 0) / sample_losses if sample_losses else None
    checked, issues = consistency_issues(conn)

    now = int(time.time() * 1000)
    rows = coverage(conn, settings.exchange.symbols, settings.all_timeframes, now - 7 * 86_400_000, now)
    expected = sum(r["expected"] for r in rows)
    snapshot_coverage = sum(r["ok"] for r in rows) / expected if expected else 0.0

    goal = settings.goal
    preview = live_preview(conn, settings, settings.live_account, since=started_at)

    def ratio(value: float | None, target: float) -> float:
        if value is None or target <= 0:
            return 0.0
        return max(0.0, min(1.0, value / target))

    def check(name: str, value: str, ok: bool, progress: float) -> dict[str, Any]:
        return {"name": name, "value": value, "ok": ok, "progress": 1.0 if ok else min(progress, 0.99)}

    preview_dd = preview["max_drawdown"]
    gate = [
        check("strategy trades (forward, every signal)", f"{len(sample)} / {goal.min_trades}",
              len(sample) >= goal.min_trades, ratio(len(sample), goal.min_trades)),
        check("days running", f"{days:.1f} / {goal.min_days}", days >= goal.min_days, ratio(days, goal.min_days)),
        check("strategy expectancy",
              f"{sample_exp:+.3f}R / {goal.min_expectancy_r:+.2f}R" if sample_exp is not None else "-",
              sample_exp is not None and sample_exp >= goal.min_expectancy_r, ratio(sample_exp, goal.min_expectancy_r)),
        check("strategy profit factor", f"{sample_pf:.2f} / {goal.min_profit_factor}" if sample_pf is not None else "-",
              sample_pf is not None and sample_pf >= goal.min_profit_factor, ratio(sample_pf, goal.min_profit_factor)),
        check("live preview net PnL > 0", f"{preview['net_pnl']:+.2f} USDT ({preview['taken']} trades)",
              preview["net_pnl"] > 0 and preview["taken"] > 0, 0.0),
        check("live preview max drawdown", f"{preview_dd:.1%} / {goal.max_drawdown:.0%}",
              preview_dd <= goal.max_drawdown and preview["taken"] > 0,
              goal.max_drawdown / preview_dd if preview_dd > 0 else 0.0),
        check("snapshot coverage (7 days, live)", f"{snapshot_coverage:.1%} / {goal.min_snapshot_coverage:.0%}",
              snapshot_coverage >= goal.min_snapshot_coverage, ratio(snapshot_coverage, goal.min_snapshot_coverage)),
        check("every trade explained (snapshot + reason)", f"{unexplained} without", unexplained == 0, 0.0),
        check("paper = exploration (consistency)", f"{checked - len(issues)}/{checked} match", not issues, 0.0),
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
        "forward_start": started_at,
        "strategy_trades": len(sample),
        "strategy_expectancy_r": sample_exp,
        "strategy_profit_factor": sample_pf,
        "strategy_win_rate": sum(1 for r in sample if r > 0) / len(sample) if sample else None,
        "days_running": days,
        "snapshot_coverage": snapshot_coverage,
        "live_preview": preview,
        "gate": gate,
        "gate_met": all(c["ok"] for c in gate),
    }
