"""Command implementations for market data and the shadow engine (called from cli.py)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager

from tradeagent.agent import Agent
from tradeagent.config import Settings, load_settings
from tradeagent.journal import connect, migrate
from tradeagent.logging_setup import setup_logging
from tradeagent.setups.report import baseline_median_entry, variant_report
from tradeagent.tv.catalog import load_catalog


@contextmanager
def _agent(*, console_log: bool = False) -> Iterator[Agent]:
    settings = load_settings()
    setup_logging(settings, console=console_log)
    conn = connect(settings.resolve(settings.journal.path))
    try:
        migrate(conn)
        catalog = load_catalog(settings.resolve(settings.tradingview.catalog))
        yield Agent(settings, catalog, conn)
    finally:
        conn.close()


def _utc(ms: int | None) -> str:
    return time.strftime("%m-%d %H:%M", time.gmtime(ms / 1000)) if ms else "-"


def market_sync() -> int:
    from tradeagent.market.sync import sync_all
    from tradeagent.venues import market_data

    settings: Settings = load_settings()
    setup_logging(settings, console=False)
    conn = connect(settings.resolve(settings.journal.path))
    try:
        migrate(conn)
        counts = sync_all(settings, conn, market_data(settings), int(time.time() * 1000), with_info=True)
    finally:
        conn.close()
    for name, n in counts.items():
        print(f"{name:<14} +{n}")
    return 0


def backfill(bars: int | None = None) -> int:
    from tradeagent.tv.backfill import backfill_snapshots

    with _agent(console_log=bool(bars)) as agent:
        async def run():
            await agent.reader.start()
            return await backfill_snapshots(agent.reader, bars, reload_after=bool(bars))

        counts = asyncio.run(run())
    for name, n in counts.items():
        print(f"{name:<12} {n}")
    return 0


def shadow_run() -> int:
    with _agent() as agent:
        counts = agent.shadow_step()
    for name, n in sorted(counts.items()):
        print(f"{name:<22} {n}")
    return 0


def shadow_reset(confirm: bool) -> int:
    if not confirm:
        print("This deletes every exploration setup and trade, and the paper account that follows them,"
              " so history can be replayed. Add --yes to do it.")
        return 1
    settings = load_settings()
    conn = connect(settings.resolve(settings.journal.path))
    try:
        migrate(conn)
        with conn:
            trades = conn.execute("DELETE FROM trades WHERE book = 'exploration'").rowcount
            setups = conn.execute("DELETE FROM setups").rowcount
            conn.execute("DELETE FROM engine_state WHERE key LIKE 'engine:%'")
            paper = conn.execute("DELETE FROM account_trades WHERE account = 'paper'").rowcount
            conn.execute("DELETE FROM account_state WHERE account = 'paper'")
    finally:
        conn.close()
    print(f"deleted {trades} trades, {setups} setups and {paper} paper account entries; run shadow-run to replay")
    return 0


def shadow_report(halves: bool = False) -> int:
    settings = load_settings()
    conn = connect(settings.resolve(settings.journal.path))
    try:
        migrate(conn)
        split = baseline_median_entry(conn) if halves else None
        rows = variant_report(conn, split_time=split)
    finally:
        conn.close()

    def num(value: float | None, fmt: str) -> str:
        return format(value, fmt) if value is not None else "-"

    print("Exploration book (closed, taken trades; R after fees, slippage and funding)")
    print(f"{'variant':<24} {'trades':>6} {'win%':>6} {'exp R':>7} {'total R':>8} {'PF':>5} {'maxDD R':>8} "
          f"{'open':>5} {'miss':>5} {'cf n':>5} {'cf exp':>7} {'fees R':>7} {'amb':>4}"
          + (f" {'1st half':>14} {'2nd half':>14}" if split else ""))
    for r in rows:
        halves_cols = ""
        if split:
            halves_cols = "".join(
                f" {num(r[f'{h}_expectancy_r'], '+7.3f'):>7} ({r[f'{h}_trades']:>4})" for h in ("first", "second"))
        print(
            f"{r['variant']:<24} {r['trades']:>6} {num(r['win_rate'] and r['win_rate'] * 100, '6.1f'):>6} "
            f"{num(r['expectancy_r'], '+7.3f'):>7} {r['total_r']:>+8.2f} {num(r['profit_factor'], '5.2f'):>5} "
            f"{r['max_drawdown_r']:>8.2f} {r['open']:>5} {r['missed']:>5} {r['counterfactual']:>5} "
            f"{num(r['counterfactual_expectancy_r'], '+7.3f'):>7} {num(r['avg_fees_r'], '7.3f'):>7} {r['ambiguous']:>4}"
            f"{halves_cols}"
        )
    print("\ncf = counterfactual: trades the variant's filters rejected, simulated anyway.")
    print("miss = limit entries that did not fill (no trade).")
    if split:
        print(f"halves: trades entered before / after {_utc(split)} UTC (the baseline's median entry)")
    return 0


def list_trades(variant: str | None, symbol: str | None, last: int, trade_id: int | None) -> int:
    settings = load_settings()
    conn = connect(settings.resolve(settings.journal.path))
    try:
        migrate(conn)
        if trade_id is not None:
            row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
            if row is None:
                print("no such trade")
                return 1
            data = dict(row)
            context = json.loads(data.pop("context_json"))
            state = json.loads(data.pop("state_json") or "{}")
            for key, value in data.items():
                print(f"{key:<14} {value}")
            print("htf           ", context.get("htf"), " filters failed:", context.get("filters_failed"))
            print("candle (OHLC) ", context.get("candle"))
            for leg in state.get("legs", []):
                print(f"exit leg       {_utc(leg['time'])} ref {leg['ref']} fill {leg['fill']:.6f} x{leg['fraction']} ({leg['reason']})")
            return 0
        clauses, params = ["book = 'exploration'"], []
        if variant:
            clauses.append("variant_id LIKE ?")
            params.append(f"{variant}%")
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        rows = conn.execute(
            "SELECT id, variant_id, symbol, timeframe, side, confirm_time, entry_ref, stop_initial, target, status,"
            " exit_time, exit_reason, r_net, taken, reason FROM trades WHERE " + " AND ".join(clauses)
            + " ORDER BY confirm_time DESC, id DESC LIMIT ?",
            (*params, last),
        ).fetchall()
    finally:
        conn.close()
    for r in rows:
        r_net = f"{r['r_net']:+.2f}R" if r["r_net"] is not None else "   -  "
        taken = "" if r["taken"] else f"  [not taken: {r['reason']}]"
        print(
            f"#{r['id']:<6} {r['variant_id']:<24} {r['symbol']:<4} {r['timeframe']:<3} {r['side']:<5} "
            f"confirm {_utc(r['confirm_time'])} entry {r['entry_ref']:<10g} stop {r['stop_initial']:<10g} "
            f"{r['status']:<7} {r['exit_reason'] or '':<7} {_utc(r['exit_time'])} {r_net}{taken}"
        )
    return 0


def verify_trades(count: int) -> int:
    """Re-compute random closed fixed-exit trades independently from raw journal data."""
    from tradeagent.setups.verify import verify_trade

    settings = load_settings()
    conn = connect(settings.resolve(settings.journal.path))
    try:
        migrate(conn)
        trades = conn.execute(
            "SELECT * FROM trades WHERE book = 'exploration' AND status = 'closed' AND exit_mode = 'fixed'"
            " ORDER BY random() LIMIT ?",
            (count,),
        ).fetchall()
        failures = 0
        for t in trades:
            issues = verify_trade(conn, settings, t)
            failures += bool(issues)
            print(
                f"{'OK  ' if not issues else 'DIFF'} #{t['id']:<6} {t['variant_id']:<24} {t['symbol']:<4} {t['timeframe']:<3} "
                f"{t['side']:<5} {_utc(t['confirm_time'])} {t['exit_reason']:<7} {t['r_net']:+.3f}R"
            )
            for issue in issues:
                print(f"       - {issue}")
    finally:
        conn.close()
    print(f"\n{len(trades) - failures}/{len(trades)} trades match an independent re-computation.")
    return 0 if failures == 0 else 1


def paper_report() -> int:
    from tradeagent.account.report import account_report

    settings = load_settings()
    conn = connect(settings.resolve(settings.journal.path))
    try:
        migrate(conn)
        r = account_report(conn, settings)
    finally:
        conn.close()
    win_rate = f"{r['win_rate'] * 100:.1f}%" if r["win_rate"] is not None else "-"
    exp = f"{r['expectancy_r']:+.3f}R" if r["expectancy_r"] is not None else "-"
    pf = f"{r['profit_factor']:.2f}" if r["profit_factor"] is not None else "-"
    pa = settings.paper_account
    limits = [f"max {pa.max_positions} positions" if pa.max_positions else "",
              f"{pa.max_positions_per_coin} per coin" if pa.max_positions_per_coin else "",
              f"daily stop {pa.daily_loss_stop:.0%}" if pa.daily_loss_stop else ""]
    rules = ", ".join(x for x in limits if x) or "no limits, every signal"
    print(f"Paper account (baseline variant, {pa.risk_per_trade:.0%} risk, {rules}; PnL after fees, slippage and funding)")
    print(f"  balance        {r['balance']:.2f} USDT (start {r['starting_balance']:.2f}, {r['return_pct']:+.2f}%)")
    print(f"  equity         {r['equity']:.2f} USDT (open positions valued at the last price)")
    print(f"  closed trades  {r['closed']}  win rate {win_rate}  expectancy {exp}  profit factor {pf}")
    print(f"  max drawdown   {r['max_drawdown_pct']:.1f}%  fees paid {r['fees_usd']:.2f} USDT"
          f"  daily loss stop hit on {r['daily_stop_days']} day(s)")
    for p in r["positions"]:
        print(f"  open: {p['symbol']} {p['timeframe']} {p['side']} since {_utc(p['entry_time'])} entry {p['entry_fill']:g}"
              f" qty {p['qty']:g} ({p['notional']:.2f} USDT, {p['leverage']:.1f}x) last {p['last_price'] or '-'}"
              f" -> {p['unrealized_usd']:+.2f} USDT ({p['unrealized_r']:+.2f}R)")
    if r["rejected"]:
        print("  signals not taken:")
        for reason, n in r["rejected"]:
            print(f"    {n:>5}  {reason}")
    for issue in r["consistency_issues"]:
        print(f"  CONSISTENCY: {issue}")
    print("\nGo-live gate:")
    for c in r["gate"]:
        print(f"  [{'x' if c['ok'] else ' '}] {c['name']:<42} {c['value']}")
    print(f"\n{'GATE MET: ready for your approval' if r['gate_met'] else 'Gate not met yet.'}")
    return 0


def paper_reset(confirm: bool, from_now: bool = False) -> int:
    from tradeagent.account.engine import reset_account

    if not confirm:
        print("This deletes the paper account history. Add --yes to do it"
              " (and --from-now to start a fresh forward test instead of replaying history).")
        return 1
    settings = load_settings()
    conn = connect(settings.resolve(settings.journal.path))
    try:
        migrate(conn)
        n = reset_account(conn, settings, from_now=from_now)
    finally:
        conn.close()
    if from_now:
        print(f"deleted {n} paper account entries; the account restarts at "
              f"{settings.paper_account.starting_balance:g} USDT and takes signals from now on")
    else:
        print(f"deleted {n} paper account entries; run shadow-run to replay the history")
    return 0


def kill_switch(mode: str | None) -> int:
    from tradeagent.account.kill_switch import get_kill_switch, set_kill_switch

    settings = load_settings()
    conn = connect(settings.resolve(settings.journal.path))
    try:
        migrate(conn)
        if mode:
            set_kill_switch(conn, mode, "cli")
        print(f"kill switch: {get_kill_switch(conn)}")
    finally:
        conn.close()
    return 0


def draw_trades(clear: bool) -> int:
    from tradeagent.tv.drawings import TradeDrawer

    with _agent() as agent:
        drawer = TradeDrawer(agent.settings, agent.conn, agent.reader.cdp, agent.reader.watchdog.pages)
        if clear:
            print(f"removed {asyncio.run(drawer.clear())} drawings")
        else:
            print(dict(asyncio.run(drawer.sync())) or "nothing new to draw")
    return 0


def run_agent() -> int:
    from tradeagent.supervisor import InstanceLock, lock_path

    lock = InstanceLock(lock_path(load_settings()))
    if not lock.acquire(attempts=6):  # a short wait: the dashboard checks the lock by taking it for a moment
        print("Another agent is already running (data/agent.lock is held); not starting a second one.")
        return 3
    try:
        with _agent(console_log=True) as agent:
            print("Agent running (reader + shadow engine). Press Ctrl+C to stop.")
            try:
                asyncio.run(agent.run())
            except KeyboardInterrupt:
                print("Stopped.")
    finally:
        lock.release()
    return 0
