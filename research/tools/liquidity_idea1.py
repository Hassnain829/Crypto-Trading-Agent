"""Idea 1 of research/notes/2026-10-19-liquidity-plan.md: does a liquidity pool between the entry and the target
hurt the baseline's trades? Read-only on the journal; Binance candles only.

    .venv\\Scripts\\python -I research\\tools\\liquidity_idea1.py
"""
from __future__ import annotations

import json
import random
import sqlite3
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tradeagent.config import load_settings  # noqa: E402
from tradeagent.sim.simulator import Costs, open_trade, results, step  # noqa: E402

M, H, D = 60_000, 3_600_000, 86_400_000
TF = {"5m": 5 * M, "15m": 15 * M}
EQUAL_TOL = 0.0010  # 0.10%

settings = load_settings(ROOT)
COSTS = Costs(settings.costs.maker_fee, settings.costs.taker_fee, settings.costs.slippage)
conn = sqlite3.connect(f"file:{settings.resolve(settings.journal.path)}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row


def candles(symbol: str, tf: str, start: int, end: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT open_time, open, high, low, close FROM candles WHERE symbol = ? AND timeframe = ?"
                        " AND open_time >= ? AND open_time < ? ORDER BY open_time", (symbol, tf, start, end)).fetchall()


def prior_range_levels(symbol: str, decision: int, sign: int) -> list[float]:
    day_start = decision - decision % D
    prev_day = candles(symbol, "1h", day_start - D, day_start)
    last4h = [c for c in candles(symbol, "5m", decision - 4 * H, decision) if c["open_time"] + 5 * M <= decision]
    levels = []
    if len(prev_day) >= 20:
        levels.append(max(c["high"] for c in prev_day) if sign > 0 else min(c["low"] for c in prev_day))
    if len(last4h) >= 40:
        levels.append(max(c["high"] for c in last4h) if sign > 0 else min(c["low"] for c in last4h))
    return levels


def equal_pools(symbol: str, decision: int, sign: int) -> list[float]:
    bars = [c for c in candles(symbol, "5m", decision - D, decision) if c["open_time"] + 5 * M <= decision]
    key = "high" if sign > 0 else "low"
    swings = []
    for i in range(2, len(bars) - 2):
        v = bars[i][key]
        around = [bars[j][key] for j in (i - 2, i - 1, i + 1, i + 2)]
        if (sign > 0 and v > max(around)) or (sign < 0 and v < min(around)):
            swings.append(v)
    pools = []
    for i, a in enumerate(swings):
        group = [b for b in swings if abs(b - a) / a <= EQUAL_TOL]
        if len(group) >= 2:
            pools.append(max(group) if sign > 0 else min(group))
    return sorted(set(pools))


def between(level: float, entry: float, target: float, sign: int) -> bool:
    return entry < level < target if sign > 0 else target < level < entry


def lower_bound(pairs: list[tuple[int, float]], draws: int = 3000) -> float | None:
    clusters, last = [], None
    for t, r in sorted(pairs):
        if last is None or t - last > 30 * M:
            clusters.append([])
        clusters[-1].append(r)
        last = t
    if len(clusters) < 5:
        return None
    rng = random.Random(7)
    means = sorted(sum(map(sum, p)) / sum(map(len, p)) for p in ([rng.choice(clusters) for _ in clusters] for _ in range(draws)))
    return means[int(0.1 * draws)]


def describe(name: str, rs: list[float]) -> str:
    if not rs:
        return f"{name}: none"
    return f"{name}: n={len(rs):3d} win={sum(r > 0 for r in rs) / len(rs):.0%} exp={st.mean(rs):+.3f}R"


trades = conn.execute("""
    SELECT t.id, t.symbol, t.timeframe, t.side, t.confirm_time, t.entry_time, t.entry_ref, t.stop_initial, t.target,
           t.r_net, t.mfe_r, t.exit_reason, t.state_json
    FROM trades t JOIN variants v ON v.id = t.variant_id
    WHERE v.role = 'baseline' AND t.taken = 1 AND t.status = 'closed' AND t.symbol IN ('XRP', 'SOL', 'ETH')
    ORDER BY t.entry_time""").fetchall()  # the plan's coins (the history also holds LINK from before 2026-10-04)
rows = []
for t in trades:
    sign = 1 if t["side"] == "long" else -1
    decision = t["confirm_time"] + TF[t["timeframe"]]
    a = [lv for lv in prior_range_levels(t["symbol"], decision, sign) if between(lv, t["entry_ref"], t["target"], sign)]
    b = [lv for lv in equal_pools(t["symbol"], decision, sign) if between(lv, t["entry_ref"], t["target"], sign)]
    rows.append({"t": t, "sign": sign, "decision": decision, "a": a, "b": b})

mid = rows[len(rows) // 2]["t"]["entry_time"]
print(f"baseline closed trades: {len(rows)} ({rows[0]['t']['entry_time']} .. {rows[-1]['t']['entry_time']}), "
      f"halves split at {mid}\n")
verdicts = {}
for flag, label in (("a", "1a prior range (prev day / last 4h) blocks the target"),
                    ("b", "1b equal highs/lows block the target")):
    print(f"== {label}")
    diffs = []
    for half_name, part in (("all", rows), ("half 1", [r for r in rows if r["t"]["entry_time"] < mid]),
                            ("half 2", [r for r in rows if r["t"]["entry_time"] >= mid])):
        blocked = [r["t"]["r_net"] for r in part if r[flag]]
        clear = [r["t"]["r_net"] for r in part if not r[flag]]
        print(f"  {half_name:6} {describe('blocked', blocked)} | {describe('clear', clear)}")
        if half_name != "all" and blocked and clear:
            diffs.append((st.mean(clear) - st.mean(blocked), len(blocked), len(clear)))
    for side in ("long", "short"):
        blocked = [r["t"]["r_net"] for r in rows if r[flag] and r["t"]["side"] == side]
        clear = [r["t"]["r_net"] for r in rows if not r[flag] and r["t"]["side"] == side]
        print(f"  {side:6} {describe('blocked', blocked)} | {describe('clear', clear)}")
    for coin in ("XRP", "SOL", "ETH"):
        blocked = [r["t"]["r_net"] for r in rows if r[flag] and r["t"]["symbol"] == coin]
        clear = [r["t"]["r_net"] for r in rows if not r[flag] and r["t"]["symbol"] == coin]
        print(f"  {coin:6} {describe('blocked', blocked)} | {describe('clear', clear)}")
    lb_b = lower_bound([(r["t"]["entry_time"], r["t"]["r_net"]) for r in rows if r[flag]])
    lb_c = lower_bound([(r["t"]["entry_time"], r["t"]["r_net"]) for r in rows if not r[flag]])
    print(f"  90% lower bounds: blocked {lb_b:+.3f}R, clear {lb_c:+.3f}R" if lb_b is not None and lb_c is not None else "")
    same_sign = len(diffs) == 2 and (diffs[0][0] > 0) == (diffs[1][0] > 0)
    passed = same_sign and all(abs(d) >= 0.15 and nb >= 25 and nc >= 25 for d, nb, nc in diffs)
    verdicts[flag] = (passed, diffs)
    print(f"  half differences (clear - blocked): {[round(d, 3) for d, _, _ in diffs]} -> "
          f"{'PASS' if passed else 'no pass'} (needs >= 0.15R, same sign, >= 25 trades per group per half)\n")

# Losers that went >= 0.5R first: did they turn near a pool (within 0.15% of the best price reached)?
print("== losers that first reached +0.5R: turned near a pool?")
near = total = 0
for r in rows:
    t = r["t"]
    if t["exit_reason"] != "stop" or (t["mfe_r"] or 0) < 0.5:
        continue
    total += 1
    risk = abs(t["entry_ref"] - t["stop_initial"])
    best = t["entry_ref"] + r["sign"] * t["mfe_r"] * risk
    levels = prior_range_levels(t["symbol"], r["decision"], r["sign"]) + equal_pools(t["symbol"], r["decision"], r["sign"])
    if any(abs(lv - best) / best <= 0.0015 for lv in levels):
        near += 1
print(f"  {near} of {total} turned within 0.15% of a pool level known at entry\n")

# Follow-up (planned): target just before the first blocking pool, only if a blocked flag passed.
if any(p for p, _ in verdicts.values()):
    flag = "a" if verdicts["a"][0] else "b"
    print(f"== follow-up: target at the first blocking pool minus 0.05% (flag {flag}), replayed on 1m candles")
    old, new = [], []
    for r in rows:
        t = r["t"]
        if not r[flag]:
            continue
        sign, entry, stop = r["sign"], t["entry_ref"], t["stop_initial"]
        risk = abs(entry - stop)
        pool = min(r[flag]) if sign > 0 else max(r[flag])
        tp = pool * (1 - sign * 0.0005)
        if sign * (tp - entry) < 0.75 * risk:
            continue
        state = open_trade(side=t["side"], mode="fixed", entry_time=t["entry_time"], entry_ref=entry, stop=stop,
                           take_profit_r=sign * (tp - entry) / risk, partial_r=1.0, partial_fraction=0.5, trail_lookback=3,
                           costs=COSTS, limit_entry=True)
        for c in candles(t["symbol"], "1m", t["entry_time"], t["entry_time"] + 72 * H):
            step(state, (c["open_time"], c["open"], c["high"], c["low"], c["close"]), COSTS)
            if state.closed:
                break
        if state.closed:
            old.append(t["r_net"])
            new.append(results(state, COSTS)["r_net"])
    print(f"  {describe('as traded', old)}\n  {describe('pool target', new)}")
else:
    print("== follow-up skipped: no blocked flag passed")
