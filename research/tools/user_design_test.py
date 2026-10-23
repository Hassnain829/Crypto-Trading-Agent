r"""The user's design of 2026-10-21 on XRP/SOL/ETH, 4 years (research only):

- every coin may always hold its first position (so 3 can always be open, one a coin)
- a second same-direction position on a coin is allowed while the total same-direction positions stay within a cap
  (6, 5 or 4), optionally only when the first position is in profit ("the signal is in favour")
- opposite signals are skipped while a coin has a position; only 15m signals; both entries on the 5m dip (E3)
- risk A 3% / B 2%, 12% open-risk budget; optional brake (half risk while 10% below the peak)

    .venv\Scripts\python -u research\tools\user_design_test.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ct, mt, at, et, a2 = (_load(n) for n in ("coordination_test", "mtf_test", "addon_test", "entry_timing_test", "addon2_test"))


def design(conn: sqlite3.Connection, signals: list[dict], cap: int, favour: float | None) -> list[dict]:
    """favour: None = no condition; otherwise the first position must be at least this R in profit at the add."""
    out, active = [], {}
    for t in sorted(signals, key=lambda x: (x["entry"], x["id"])):
        for sym in list(active):
            active[sym] = [o for o in active[sym] if o["exit"] > t["entry"]]
        live = active.get(t["symbol"], [])
        cur = dict(t)
        if live:
            if any(o["side"] != t["side"] for o in live) or len(live) >= 2:
                continue
            same_total = sum(1 for ps in active.values() for o in ps if o["side"] == t["side"])
            if same_total >= cap:
                continue
            if favour is not None:
                first = live[0]
                r_now = ct.price_r(conn, first, t["entry"])
                if r_now is None or r_now < favour:
                    continue
            cur["addon"] = True
        out.append(cur)
        active.setdefault(t["symbol"], []).append(cur)
    return out


def worst_day(taken: list[dict], **kw) -> float:
    ev = []
    for i, t in enumerate(taken):
        ev += [(t["entry"], 1, i), (t["exit"], 0, i)]
    ev.sort()
    bal, open_, days = 150.0, {}, defaultdict(float)
    peak = bal
    for tm, kind, i in ev:
        t = taken[i]
        if kind == 1:
            scale = 0.5 if kw.get("brake") and bal < peak * (1 - kw["brake"]) else 1.0
            room = 0.12 * bal - sum(open_.values())
            risk = min(bal * (0.03 if t["q"] == "A" else 0.02) * scale, room)
            if risk > 0.001 * bal:
                open_[i] = risk
        elif i in open_:
            pnl = open_.pop(i) * t["r"]
            days[time.strftime("%Y-%m-%d", time.gmtime(tm / 1000))] += pnl / bal
            bal += pnl
            peak = max(peak, bal)
    return min(days.values())


def report(title: str, conn: sqlite3.Connection, coins: list[str], start: int, split: int) -> None:
    signals = [t for t in ct.load(conn, 1, start, tuple(coins)) if t["closed"] and t["tf"] == "15m"]
    e3 = [x for x in (et.dip_candle_entry(conn, t) for t in signals) if x is not None]
    print(f"\n== {title}")
    print(f"   {'design':58} {'trades':>6} {'2nd':>5} {'2nd R':>7} | {'$150 over 4 years':>20} {'DD':>6} {'worst day':>9} |"
          f" {'2022-24':>15} | {'2024-26':>15}")
    rows = [("one position per coin (C6 + 5m dip)", at.policy(conn, e3, (), None), {})]
    for cap in (6, 5, 4):
        for favour, fname in ((None, "any time"), (0.0, "1st in profit"), (0.5, "1st at +0.5R")):
            rows.append((f"1st always, 2nd {fname}, max {cap} same direction", design(conn, e3, cap, favour), {}))
    best = [r for r in rows if "max 6" in r[0] or "max 5" in r[0]]
    for name, taken, _ in list(rows):
        if name in [b[0] for b in best]:
            rows.append((name + " + brake", taken, {"brake": 0.10}))
    for name, taken, kw in rows:
        adds = [t["r"] for t in taken if t.get("addon")]
        bal, dd = a2.account(taken, **kw)
        b1 = a2.account([t for t in taken if t["entry"] < split], **kw)
        b2 = a2.account([t for t in taken if t["entry"] >= split], **kw)
        print(f"   {name:58} {len(taken):6d} {len(adds):5d} {sum(adds) / len(adds) if adds else 0:+7.3f} |"
              f" ${bal:9,.0f} ({bal / 150 - 1:+6.0%}) {dd:6.1%} {worst_day(taken, **kw):+9.1%} |"
              f" {b1[0] / 150 - 1:+6.0%} (DD {b1[1]:3.0%}) | {b2[0] / 150 - 1:+6.0%} (DD {b2[1]:3.0%})", flush=True)


def main() -> None:
    conn = sqlite3.connect(f"file:{mt.LONG4}?mode=ro", uri=True)
    report("MAIN: XRP, SOL, ETH, 4 years", conn, ["XRP", "SOL", "ETH"], mt.START4, mt.SPLIT)
    conn.close()


if __name__ == "__main__":
    main()
