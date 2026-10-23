"""Every idea of 2026-10-20 on the real demo signals (since the demo started), with the tiers filled in.

    .venv\\Scripts\\python -u research\\tools\\demo_ideas_test.py

The demo recorded quality only from 2026-10-18 and the squeeze from 2026-10-20. For older demo signals the quality
and the squeeze come from the same signal in the v6 backtest journal (the v6 charts' history covers the demo period;
same symbol, chart, side and entry). Open positions are valued at the latest 1m close. The live journal is only read.
"""
from __future__ import annotations

import importlib.util
import random
import sqlite3
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ct = _load("coordination_test")
op = _load("one_position_test")


def fill_tiers(trades: list[dict]) -> tuple[int, int, int]:
    v6 = sqlite3.connect(f"file:{ct.PAST}?mode=ro", uri=True)
    past = {(t["symbol"], t["tf"], t["side"], t["entry"]): t for t in ct.load(v6, 1) + ct.load(v6, 0)}
    v6.close()
    live_q = matched = missing = 0
    for t in trades:
        t["q_src"] = "live"
        if t.get("q_live"):
            live_q += 1
        m = past.get((t["symbol"], t["tf"], t["side"], t["entry"]))
        if not t.get("q_live"):
            if m is not None:
                t["q"], t["q_src"] = m["q"], "v6"
                matched += 1
            else:
                t["q_src"] = "none"
                missing += 1
        if t["sqz"] is None and m is not None:
            t["sqz"] = m["sqz"]
    return live_q, matched, missing


def mark_open(conn: sqlite3.Connection, trades: list[dict]) -> int:
    now = 0
    for t in trades:
        if not t["closed"]:
            row = conn.execute("SELECT open_time, close FROM candles WHERE symbol = ? AND timeframe = '1m'"
                               " ORDER BY open_time DESC LIMIT 1", (t["symbol"],)).fetchone()
            sign = 1 if t["side"] == "long" else -1
            t["r"] = sign * (row[1] - t["entry_ref"]) / abs(t["entry_ref"] - t["stop"]) - t["cost"]
            t["exit"], t["closed"], t["marked"] = row[0] + 60_000, True, True
            now = max(now, row[0] + 60_000)
    return now


def account(taken: list[dict], risk_a: float = 0.03, risk_b: float = 0.02, budget: float = 0.12) -> tuple[float, float]:
    events = []
    for i, t in enumerate(taken):
        events.append((t["entry"], 1, i))
        events.append((t["exit"], 0, i))
    events.sort()
    bal = peak = 150.0
    dd, open_risk = 0.0, {}
    for _, kind, i in events:
        t = taken[i]
        if kind == 1:
            room = budget * bal - sum(open_risk.values())
            risk = min(bal * (risk_a if t["q"] == "A" else risk_b), room)
            if risk > 0.001 * bal:
                open_risk[i] = risk
        elif i in open_risk:
            bal += open_risk.pop(i) * t["r"]
            peak = max(peak, bal)
            dd = max(dd, 1 - bal / peak)
    return bal, dd


def day(ms: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def beats(base: dict[int, float], pol: dict[int, float], trades: list[dict], n: int = 10_000) -> float:
    """Paired day-block bootstrap: the share of resampled demo periods in which the rule makes more R than now."""
    by_day: dict[str, float] = {}
    for t in trades:
        by_day[day(t["entry"])] = by_day.get(day(t["entry"]), 0.0) + pol.get(t["id"], 0.0) - base.get(t["id"], 0.0)
    diffs = list(by_day.values())
    if not any(diffs):
        return float("nan")
    rng = random.Random(11)
    return sum(sum(rng.choice(diffs) for _ in diffs) > 0 for _ in range(n)) / n


def main() -> None:
    conn = sqlite3.connect(f"file:{ct.LIVE}?mode=ro", uri=True)
    started = conn.execute("SELECT started_at FROM account_state WHERE account = 'paper'").fetchone()[0]
    balance = conn.execute("SELECT balance FROM account_state WHERE account = 'paper'").fetchone()[0]
    trades = ct.load(conn, 1, started)
    import json
    for t in trades:  # was the quality recorded live?
        ctx = json.loads(conn.execute("SELECT context_json FROM trades WHERE id = ?", (t["id"],)).fetchone()[0] or "{}")
        t["q_live"] = ctx.get("quality")
    ct.trend15(conn, trades)
    live_q, matched, missing = fill_tiers(trades)
    n_open = sum(1 for t in trades if not t["closed"])
    now = mark_open(conn, trades)
    print(f"Demo signals since {day(started)}: {len(trades)} ({n_open} still open, valued at the price of"
          f" {time.strftime('%m-%d %H:%M', time.gmtime(now / 1000))} UTC). The real demo balance is ${balance:.2f} plus the open positions.")
    print(f"Quality: {live_q} recorded live, {matched} taken from the same signal on the v6 charts, {missing} not found (counted as B).")
    print(f"A: {sum(t['q'] == 'A' for t in trades)}, B: {sum(t['q'] == 'B' for t in trades)};"
          f" squeeze known on {sum(t['sqz'] is not None for t in trades)}, fired on {sum(t['sqz'] is True for t in trades)}")

    def line(name: str, rs: list[float]) -> str:
        if not rs:
            return f"   {name:44} no trades"
        return f"   {name:44} n={len(rs):3d} win={sum(r > 0 for r in rs) / len(rs):4.0%} {sum(rs) / len(rs):+.3f}R total {sum(rs):+5.1f}R"

    print("\n== The demo's own groups")
    print(line("all", [t["r"] for t in trades]))
    print(line("quality A", [t["r"] for t in trades if t["q"] == "A"]))
    print(line("quality B", [t["r"] for t in trades if t["q"] == "B"]))
    print(line("squeeze fired", [t["r"] for t in trades if t["sqz"] is True]))
    print(line("squeeze not fired", [t["r"] for t in trades if t["sqz"] is False]))
    print(line("B without squeeze", [t["r"] for t in trades if t["q"] == "B" and t["sqz"] is not True]))
    base_run = op.run(conn, trades, None)
    dup = [t for t in base_run if any(o["symbol"] == t["symbol"] and o["side"] == t["side"] and o["entry"] < t["entry"] < o["exit"]
                                      for o in base_run)]
    print(line("duplicates (same direction already open)", [t["r"] for t in dup]))
    opp = [t for t in base_run if any(o["symbol"] == t["symbol"] and o["side"] != t["side"] and o["entry"] < t["entry"] < o["exit"]
                                      for o in base_run)]
    print(line("counter signals (opposite already open)", [t["r"] for t in opp]))

    rules = {}
    for r in ct.RULES:
        rules[r] = ("ct", r)
    for p, pol in op.POLICIES.items():
        if pol is not None:
            rules[p] = ("op", pol)
    mid = sorted(t["entry"] for t in trades)[len(trades) // 2]
    base = {t["id"]: t["r"] for t in ct.apply(conn, trades, ct.RULES[0])}
    print(f"\n== Every idea on the demo signals ({day(trades[0]['entry'])} .. {day(trades[-1]['entry'])}; halves split at {day(mid)})")
    print(f"   {'rule':48} {'trades':>6} {'win':>4} {'R/trade':>8} {'half 1':>7} {'half 2':>7} {'total':>7} {'DD R':>5} {'both SL':>7}"
          f" | {'demo $150, today':>24} | P(beats now)")
    for name, (kind, key) in rules.items():
        taken = ct.apply(conn, trades, key) if kind == "ct" else op.run(conn, trades, key)
        h1 = sum(t["r"] for t in taken if t["entry"] < mid)
        h2 = sum(t["r"] for t in taken if t["entry"] >= mid)
        cum = peak = dd = 0.0
        for t in sorted(taken, key=lambda x: x["exit"]):
            cum += t["r"]
            peak = max(peak, cum)
            dd = max(dd, peak - cum)
        bal, add = account(taken)
        pol = {t["id"]: t["r"] for t in taken}
        p = beats(base, pol, trades)
        win = sum(t["r"] > 0 for t in taken) / len(taken)
        print(f"   {name:48} {len(taken):6d} {win:4.0%} {(h1 + h2) / len(taken):+8.3f} {h1:+7.1f} {h2:+7.1f} {h1 + h2:+7.1f} {dd:5.1f}"
              f" {op.both_stopped(taken):7d} | ${bal:7.2f} ({bal / 150 - 1:+4.0%}) DD {add:5.1%} | "
              + ("-" if p != p else f"{p:4.0%}"))

    print("\n== Risk rules on the demo signals (every signal, as now; event simulation)")
    for label, ra, rb, bud in [("now: A 3% / B 2%, 12% budget", .03, .02, .12), ("A 3% / B 2%, 20% budget", .03, .02, .20),
                               ("flat 5%, 12% budget", .05, .05, .12), ("flat 5%, 20% budget", .05, .05, .20),
                               ("A 5% / B 3%, 20% budget", .05, .03, .20)]:
        bal, add = account(ct.apply(conn, trades, ct.RULES[0]), ra, rb, bud)
        print(f"   {label:36} ${bal:7.2f} ({bal / 150 - 1:+4.0%}) max DD {add:5.1%}")
    conn.close()


if __name__ == "__main__":
    main()
