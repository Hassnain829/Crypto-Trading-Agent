"""Tests 2 and 3 of research/notes/2026-10-20-three-tests-plan.md on trades that are already simulated. Read-only.

    .venv\\Scripts\\python -I research\\tools\\tests_2_3.py
"""
from __future__ import annotations

import sqlite3
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tradeagent.config import load_settings  # noqa: E402
from vol_stop_test import BASE_MIN, REF_RANGE, TF, WEAKEST, Vol, fmt, screen, stats, trades  # noqa: E402

settings = load_settings(ROOT)
live = sqlite3.connect(f"file:{settings.resolve(settings.journal.path)}?mode=ro", uri=True)

print("== Test 2: minimum stop = max(1.5%, scaled)")
for (coin,) in screen.execute("SELECT DISTINCT symbol FROM trades WHERE symbol != 'XRP' ORDER BY symbol").fetchall():
    vol = Vol(screen, coin)
    chosen = []
    for r in trades(screen, coin):
        v = vol.at(r[0] + TF[r[1]])
        if v is not None and abs(r[3] - r[4]) / r[3] >= max(BASE_MIN, BASE_MIN * v / REF_RANGE):
            chosen.append(r)
    s = stats(chosen)
    if not s["n"]:
        print(f"  {coin:8} no trades")
        continue
    mid = chosen[len(chosen) // 2][2]
    h1, h2 = stats([r for r in chosen if r[2] < mid]), stats([r for r in chosen if r[2] >= mid])
    checks = {"40+": s["n"] >= 40, "halves>0": bool(h1["n"] and h2["n"] and h1["exp"] > 0 and h2["exp"] > 0),
              "PF>=1.3": (s["pf"] or 0) >= 1.3, "target>=42%": s["target"] >= 0.42, f">= +{WEAKEST}R": s["exp"] >= WEAKEST}
    print(f"  {coin:8} {fmt(s)} halves {h1['exp']:+.3f} / {h2['exp']:+.3f} -> "
          f"{'QUALIFIES' if all(checks.values()) else 'no'}: " + ", ".join(f"{k} {'ok' if v else 'FAIL'}" for k, v in checks.items()))


def late_split(conn: sqlite3.Connection, where: str, args: tuple = ()) -> list[tuple]:
    rows = conn.execute(
        "SELECT t.entry_time, t.r_net, (t.confirm_time - t.trigger_time) / CASE t.timeframe WHEN '5m' THEN 300000 ELSE 900000 END"
        " FROM trades t JOIN variants v ON v.id = t.variant_id WHERE v.role = 'baseline' AND t.status = 'closed' " + where +
        " ORDER BY t.entry_time", args).fetchall()
    return rows


def report(name: str, rows: list[tuple]) -> tuple[list[float], int, int]:
    mid = rows[len(rows) // 2][0]
    diffs, ns = [], []
    print(f"  -- {name}: {len(rows)} trades")
    for half, part in (("all", rows), ("half 1", [r for r in rows if r[0] < mid]), ("half 2", [r for r in rows if r[0] >= mid])):
        late = [r[1] for r in part if r[2] >= 1]
        same = [r[1] for r in part if r[2] == 0]
        print(f"     {half:6} late (1-3): n={len(late):4d} exp={st.mean(late):+.3f}R win={sum(x > 0 for x in late) / len(late):.0%}"
              f" | same candle: n={len(same):4d} exp={st.mean(same):+.3f}R win={sum(x > 0 for x in same) / len(same):.0%}")
        if half != "all":
            diffs.append(st.mean(late) - st.mean(same))
            ns.append(min(len(late), len(same)))
    print(f"     difference (late - same) by half: {[round(d, 3) for d in diffs]}")
    return diffs, min(ns), 0


print("\n== Test 3: late confirmation")
da, n_a, _ = report("(a) current coins, skipped signals (live journal)",
                    late_split(live, "AND t.taken = 0 AND t.reason = 'min_stop_pct' AND t.symbol IN ('XRP', 'SOL', 'ETH')"))
db, _n_b, _ = report("(b) the eight screen coins, taken and skipped (coin screen)",
                     late_split(screen, "AND t.symbol != 'XRP' AND (t.taken = 1 OR t.reason = 'min_stop_pct')"))
passed = all(d >= 0.15 for d in da) and n_a >= 25 and all(d > 0 for d in db)
print(f"  verdict: {'PASS' if passed else 'no'} (needs (a) >= +0.15R in both halves with 25+ per group, and (b) the same way)")
