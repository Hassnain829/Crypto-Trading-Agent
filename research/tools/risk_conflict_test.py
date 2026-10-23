"""Two tests on the signal version 6 trades (research only; the live journal is only read).

    .venv\\Scripts\\python -u research\\tools\\risk_conflict_test.py risk       # bigger risk and open-risk budget
    .venv\\Scripts\\python -u research\\tools\\risk_conflict_test.py conflict   # long and short open on one coin

Samples:
- past: the v6 backtest journal (data/replay/journal-v6.db, built by v6_backtest.py), 2026-07-13 .. 2026-10-18
- forward: a copy of the live journal (data/replay/journal-fwd-risk.db), every demo trade since the demo started

`risk` replays the demo account (AccountEngine, every signal, $150) with other risk rules and adds a day-block
bootstrap of the past trades for the spread of drawdowns. `conflict` looks at trades that opened while an opposite
position on the same coin was open, and at size rules for them (the user does not want trades skipped).
"""
from __future__ import annotations

import json
import random
import sqlite3
import statistics as st
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tradeagent.config import load_settings  # noqa: E402
from tradeagent.journal import connect, migrate  # noqa: E402

PAST = ROOT / "data" / "replay" / "journal-v6.db"
FWD = ROOT / "data" / "replay" / "journal-fwd-risk.db"
LIVE = ROOT / "data" / "journal.db"
BASELINE = "v0-773ea9"
settings = load_settings()

RULES = [  # label, risk B, risk A, open-risk budget, leverage cap, day stop
    ("now: A 3% / B 2%, 12% budget", 0.02, 0.03, 0.12, 10, None),
    ("A 3% / B 2%, 20% budget", 0.02, 0.03, 0.20, 10, None),
    ("flat 5%, 12% budget", 0.05, None, 0.12, 10, None),
    ("flat 5%, 20% budget", 0.05, None, 0.20, 10, None),
    ("A 5% / B 3%, 20% budget", 0.03, 0.05, 0.20, 10, None),
    ("flat 5%, 20% budget, 20x leverage", 0.05, None, 0.20, 20, None),
    ("flat 5%, 20% budget, 10% day stop", 0.05, None, 0.20, 10, 0.10),
]


def fmt(ms: int) -> str:
    return time.strftime("%m-%d", time.gmtime(ms / 1000))


def forward_copy() -> int:
    """Copy the live journal; return the demo's start time."""
    FWD.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{LIVE}?mode=ro", uri=True)
    dst = sqlite3.connect(FWD)
    src.backup(dst)
    started = src.execute("SELECT started_at FROM account_state WHERE account = 'paper'").fetchone()[0]
    src.close()
    dst.close()
    return started


def account_run(conn: sqlite3.Connection, rule: tuple, start_at: int | None) -> dict:
    from tradeagent.account.engine import AccountEngine, reset_account

    label, risk_b, risk_a, budget, lev, day_stop = rule
    s = settings.model_copy(deep=True)
    pa = s.paper_account
    pa.risk_per_trade, pa.risk_tier_a, pa.max_open_risk, pa.leverage_cap, pa.daily_loss_stop = risk_b, risk_a, budget, lev, day_stop
    pa.max_positions = pa.max_positions_per_coin = None
    reset_account(conn, s)
    if start_at is not None:  # the forward demo: only signals from the demo's start on
        with conn:
            conn.execute("INSERT INTO account_state (account, balance, day, day_start_balance, last_entry_time, baseline,"
                         " started_at, updated_at) VALUES ('paper', ?, NULL, ?, ?, ?, ?, ?)",
                         (pa.starting_balance, pa.starting_balance, start_at, BASELINE, start_at, int(time.time() * 1000)))
    AccountEngine(s, conn).process()
    rows = conn.execute("SELECT exit_time, pnl_usd, balance_after, notes, risk_usd, balance_before FROM account_trades"
                        " WHERE account = 'paper' AND status = 'closed' ORDER BY exit_time, id").fetchall()
    open_rows = conn.execute("SELECT count(*), coalesce(sum(risk_usd), 0) FROM account_trades"
                             " WHERE account = 'paper' AND status = 'open'").fetchone()
    skipped = conn.execute("SELECT count(*) FROM account_trades WHERE account = 'paper' AND status = 'rejected'"
                           " AND reject_reason NOT LIKE 'signal arrived after%'").fetchone()[0]
    start = pa.starting_balance
    bal = peak = start
    dd = 0.0
    days: dict[str, float] = {}
    for r in rows:
        bal = r[2]
        peak = max(peak, bal)
        dd = max(dd, (peak - bal) / peak)
        days[time.strftime("%Y-%m-%d", time.gmtime(r[0] / 1000))] = days.get(time.strftime("%Y-%m-%d", time.gmtime(r[0] / 1000)), 0) + r[1]
    worst_day = min(days.values()) if days else 0.0
    reduced = sum(1 for r in rows if r[3] and ("open-risk" in r[3] or "leverage" in r[3] or "free margin" in r[3]))
    avg_risk = st.mean(r[4] / r[5] for r in rows) if rows else 0.0
    # the worst run of losses in a row, as a share of the balance before it
    worst_run, run_start, cur = 0.0, None, start
    for r in rows:
        if r[1] < 0:
            run_start = run_start if run_start is not None else r[5]
            worst_run = max(worst_run, (run_start - r[2]) / run_start)
        else:
            run_start = None
    print(f"   {label:36} {len(rows):3d} closed, {skipped} skipped, {reduced:3d} made smaller, avg risk {avg_risk:.1%} |"
          f" ${start:.0f} -> ${bal:7.2f} ({bal / start - 1:+5.0%}) max DD {dd:5.1%}, worst loss streak {worst_run:5.1%},"
          f" worst day ${worst_day:+.2f}" + (f" | {open_rows[0]} open, ${open_rows[1]:.2f} at risk" if open_rows[0] else ""))
    return {"final": bal, "dd": dd}


def trades_of(conn: sqlite3.Connection, since: int = 0) -> list[dict]:
    rows = conn.execute("SELECT id, symbol, timeframe, side, entry_time, exit_time, r_net, context_json, status,"
                        " entry_ref, stop_initial, r_gross FROM trades"
                        " WHERE book = 'exploration' AND variant_id = ? AND taken = 1 AND status IN ('open', 'closed')"
                        " AND entry_time >= ? AND symbol IN ('XRP', 'SOL', 'ETH') ORDER BY entry_time, id",
                        (BASELINE, since)).fetchall()
    out = []
    for r in rows:
        ctx = json.loads(r[7] or "{}")
        out.append({"id": r[0], "symbol": r[1], "tf": r[2], "side": r[3], "entry": r[4], "exit": r[5] or 2**62,
                    "r": r[6], "q": ctx.get("quality") or "B", "sqz": ctx.get("sqz_fire"), "closed": r[8] == "closed",
                    "entry_ref": r[9], "stop": r[10], "cost": (r[11] - r[6]) if r[11] is not None and r[6] is not None else 0.05})
    return out


def bootstrap(trades: list[dict], rule: tuple, n: int = 4000, seed: int = 7) -> str:
    """Day-block bootstrap: whole days of trades drawn with replacement. Trades of one 30-minute cluster are sized
    together from the balance before it and share the open-risk budget (approximate; long overlaps are ignored)."""
    _, risk_b, risk_a, budget, _, _ = rule
    by_day: dict[str, list[list[dict]]] = {}
    for t in trades:
        if not t["closed"]:
            continue
        day = time.strftime("%Y-%m-%d", time.gmtime(t["entry"] / 1000))
        clusters = by_day.setdefault(day, [])
        if clusters and t["entry"] - clusters[-1][0]["entry"] <= 30 * 60_000:
            clusters[-1].append(t)
        else:
            clusters.append([t])
    days = list(by_day.values())
    n_days = len(days)
    rng = random.Random(seed)
    finals, dds = [], []
    for _ in range(n):
        bal = peak = 1.0
        dd = 0.0
        for _d in range(n_days):
            for cl in rng.choice(days):
                risks = [(risk_a if (risk_a and t["q"] == "A") else risk_b) for t in cl]
                scale = min(1.0, budget / sum(risks))
                bal += sum(bal * rk * scale * t["r"] for rk, t in zip(risks, cl))
                bal = max(bal, 1e-9)
                peak = max(peak, bal)
                dd = max(dd, 1 - bal / peak)
        finals.append(bal)
        dds.append(dd)
    finals.sort()
    dds.sort()
    q = lambda xs, p: xs[int(p * (len(xs) - 1))]
    return (f"median {q(finals, .5) - 1:+6.0%} (bad 5%: {q(finals, .05) - 1:+5.0%}) | max DD median {q(dds, .5):5.1%},"
            f" bad 5% {q(dds, .95):5.1%}, P(DD>30%) {sum(d > .30 for d in dds) / n:4.0%}, P(DD>50%) {sum(d > .50 for d in dds) / n:4.0%}")


def risk_test() -> None:
    print("== PAST: v6 charts of XRP, SOL and ETH, 2026-07-13 .. 2026-10-18 (the whole demo account replayed, $150)")
    conn = connect(PAST)
    migrate(conn)
    for rule in RULES:
        account_run(conn, rule, None)
    past = trades_of(conn)
    conn.close()
    print("\n== FORWARD: every real demo signal since the demo started (signal versions 2..6), $150")
    started = forward_copy()
    conn = connect(FWD)
    migrate(conn)
    for rule in RULES:
        account_run(conn, rule, started)
    conn.close()
    print(f"\n== BOOTSTRAP of the past trades ({len(past)} trades; whole days redrawn 4,000 times over the same number of days)")
    for rule in RULES[:5]:
        print(f"   {rule[0]:36} {bootstrap(past, rule)}")


def opposite_open(trades: list[dict]) -> None:
    """Mark each trade with the opposite positions on its coin that were open when it entered."""
    for t in trades:
        t["against"] = [o for o in trades if o["symbol"] == t["symbol"] and o["side"] != t["side"]
                        and o["entry"] < t["entry"] < o["exit"]]
        t["countered"] = [o for o in trades if o["symbol"] == t["symbol"] and o["side"] != t["side"]
                          and t["entry"] < o["entry"] < t["exit"]]


def line(name: str, rs: list[float]) -> str:
    if not rs:
        return f"   {name:52} no trades"
    w, l = sum(x for x in rs if x > 0), -sum(x for x in rs if x < 0)
    return (f"   {name:52} n={len(rs):3d} win={sum(x > 0 for x in rs) / len(rs):4.0%} exp={st.mean(rs):+.3f}R"
            f" PF={w / l if l else float('inf'):4.2f} total={sum(rs):+6.1f}R")


SIZE_RULES = {  # size multiplier of a trade given the opposite positions open at its entry
    "every trade full size (now)": lambda t: 1.0,
    "counter trade half size": lambda t: 0.5 if t["against"] else 1.0,
    "counter B against an open A: half size": lambda t: 0.5 if t["q"] == "B" and any(o["q"] == "A" for o in t["against"]) else 1.0,
    "counter 5m against an open 15m: half size": lambda t: 0.5 if t["tf"] == "5m" and any(o["tf"] == "15m" for o in t["against"]) else 1.0,
    "counter trade without squeeze: half size": lambda t: 0.5 if t["against"] and t["sqz"] is not True else 1.0,
}


def r_at(conn: sqlite3.Connection, t: dict, at: int) -> float | None:
    """The trade's R if it were closed at the open of the 1m candle at `at` (its own costs taken off)."""
    row = conn.execute("SELECT open FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time >= ?"
                       " ORDER BY open_time LIMIT 1", (t["symbol"], at)).fetchone()
    if row is None:
        return None
    sign = 1 if t["side"] == "long" else -1
    return sign * (row[0] - t["entry_ref"]) / abs(t["entry_ref"] - t["stop"]) - t["cost"]


CLOSE_RULES = {  # which older position a new opposite signal closes at its entry (the new trade is always taken)
    "keep both (now)": lambda older, newer: False,
    "the new opposite signal closes the older position": lambda older, newer: True,
    "it closes the older position only if it is quality B": lambda older, newer: older["q"] == "B",
    "it closes an older B position only if it is losing": lambda older, newer: older["q"] == "B" and newer["_older_r"] < 0,
}


def close_rules(conn: sqlite3.Connection, closed: list[dict], mid: int) -> None:
    print("   close rules (the older position closed when the first opposite signal enters; halves of this sample):")
    for rname, f in CLOSE_RULES.items():
        rs = []
        for t in closed:
            r = t["r"]
            first = min((o for o in t["countered"]), key=lambda o: o["entry"], default=None)
            if first is not None:
                now_r = r_at(conn, t, first["entry"])
                if now_r is not None:
                    first["_older_r"] = now_r
                    if f(t, first):
                        r = now_r
            rs.append((t["entry"], r))
        h1 = sum(r for e, r in rs if e < mid)
        h2 = sum(r for e, r in rs if e >= mid)
        cum = peak = dd = 0.0
        for _, r in rs:
            cum += r
            peak = max(peak, cum)
            dd = max(dd, peak - cum)
        print(f"   {rname:52} half 1 {h1:+6.1f}R | half 2 {h2:+6.1f}R | all {h1 + h2:+6.1f}R"
              f" ({(h1 + h2) / len(rs):+.3f}R a trade), max DD {dd:4.1f}R")


def conflict_sample(name: str, trades: list[dict], conn: sqlite3.Connection | None = None) -> None:
    opposite_open(trades)
    closed = [t for t in trades if t["closed"]]
    mid = closed[len(closed) // 2]["entry"] if closed else 0
    print(f"\n== {name}: {len(closed)} closed trades, {fmt(closed[0]['entry'])} .. {fmt(closed[-1]['entry'])}")
    print(line("all", [t["r"] for t in closed]))
    print(line("no opposite position open at entry", [t["r"] for t in closed if not t["against"]]))
    print(line("COUNTER: entered against an open opposite position", [t["r"] for t in closed if t["against"]]))
    print(line("  counter A", [t["r"] for t in closed if t["against"] and t["q"] == "A"]))
    print(line("  counter B", [t["r"] for t in closed if t["against"] and t["q"] == "B"]))
    print(line("  counter B against an open A", [t["r"] for t in closed if t["q"] == "B" and any(o["q"] == "A" for o in t["against"])]))
    print(line("  counter 5m against an open 15m", [t["r"] for t in closed if t["tf"] == "5m" and any(o["tf"] == "15m" for o in t["against"])]))
    print(line("  counter 15m against an open 5m only", [t["r"] for t in closed if t["tf"] == "15m" and t["against"] and all(o["tf"] == "5m" for o in t["against"])]))
    print(line("  counter with squeeze fired", [t["r"] for t in closed if t["against"] and t["sqz"] is True]))
    print(line("  counter without squeeze", [t["r"] for t in closed if t["against"] and t["sqz"] is not True]))
    print(line("OLDER: a later opposite signal came while it was open", [t["r"] for t in closed if t["countered"]]))
    print(line("  older A", [t["r"] for t in closed if t["countered"] and t["q"] == "A"]))
    print(line("  older B", [t["r"] for t in closed if t["countered"] and t["q"] == "B"]))
    pairs = [(t, o) for t in closed for o in t["against"] if o["closed"]]
    both_stop = sum(1 for t, o in pairs if t["r"] < 0 and o["r"] < 0)
    both_win = sum(1 for t, o in pairs if t["r"] > 0 and o["r"] > 0)
    newer_won = sum(1 for t, o in pairs if t["r"] > 0 > o["r"])
    older_won = sum(1 for t, o in pairs if o["r"] > 0 > t["r"])
    print(f"   pairs (newer, older): {len(pairs)} | newer won {newer_won}, older won {older_won}, both lost {both_stop}, both won {both_win}")
    print("   size rules (R per trade at the account's size; halves of this sample):")
    for rname, f in SIZE_RULES.items():
        res = []
        for part in ([t for t in closed if t["entry"] < mid], [t for t in closed if t["entry"] >= mid], closed):
            total = sum(f(t) * t["r"] for t in part)
            peak = cum = dd = 0.0
            for t in part:
                cum += f(t) * t["r"]
                peak = max(peak, cum)
                dd = max(dd, peak - cum)
            res.append((total, dd))
        print(f"   {rname:46} half 1 {res[0][0]:+6.1f}R | half 2 {res[1][0]:+6.1f}R | all {res[2][0]:+6.1f}R, max DD {res[2][1]:4.1f}R")
    if conn is not None:
        close_rules(conn, closed, mid)


def open_now() -> None:
    conn = sqlite3.connect(f"file:{LIVE}?mode=ro", uri=True)
    started = conn.execute("SELECT started_at FROM account_state WHERE account = 'paper'").fetchone()[0]
    trades = trades_of(conn, started)
    conflict_sample("FORWARD demo signals (live journal)", trades, conn)
    conn.close()
    opposite_open(trades)
    print("\n   open now:")
    for t in trades:
        if not t["closed"]:
            print(f"   {t['symbol']} {t['tf']:3} {t['side']:5} q={t['q']} sqz={t['sqz']} entered {time.strftime('%m-%d %H:%M', time.gmtime(t['entry'] / 1000))}"
                  f" | against open: {[(o['tf'], o['side'], o['q']) for o in t['against']]}")


def conflict_test() -> None:
    conn = sqlite3.connect(f"file:{PAST}?mode=ro", uri=True)
    conflict_sample("PAST v6 charts", trades_of(conn), conn)
    conn.close()
    open_now()


if __name__ == "__main__":
    {"risk": risk_test, "conflict": conflict_test}[sys.argv[1]]()
