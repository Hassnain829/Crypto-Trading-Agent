r"""What happens when many same-direction positions are open on XRP/SOL/ETH together (max 2 per coin, 5m dip entries,
A 3% / B 2%, 12% budget), with and without the 2-same-direction cap across coins (the user, 2026-10-21). Research only.

    .venv\Scripts\python -u research\tools\crowd_test.py
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


ct, mt, at, et = (_load(n) for n in ("coordination_test", "mtf_test", "addon_test", "entry_timing_test"))


def replay(taken: list[dict], corr: int | None, ra: float = .03, rb: float = .02, budget: float = .12):
    """The account with its open positions; returns the balance curve and the 'crowds': times when 3 or more positions
    in one direction were open, with the balance before and after they all closed."""
    ev = []
    for i, t in enumerate(taken):
        ev += [(t["entry"], 1, i), (t["exit"], 0, i)]
    ev.sort()
    bal = peak = 150.0
    dd, open_, curve = 0.0, {}, []
    crowd, crowds = None, []
    for tm, kind, i in ev:
        t = taken[i]
        if kind == 1:
            if corr is not None and sum(1 for j in open_ if taken[j]["side"] == t["side"]) >= corr:
                continue
            room = budget * bal - sum(r for r, _ in open_.values())
            risk = min(bal * (ra if t["q"] == "A" else rb), room)
            if risk > 0.001 * bal:
                open_[i] = (risk, t["side"])
                same = [j for j in open_ if open_[j][1] == t["side"]]
                if len(same) >= 3 and crowd is None:
                    crowd = {"start": tm, "bal0": bal, "side": t["side"], "max": len(same), "risk": sum(open_[j][0] for j in same) / bal}
                elif crowd is not None and crowd["side"] == t["side"]:
                    crowd["max"] = max(crowd["max"], len(same))
                    crowd["risk"] = max(crowd["risk"], sum(open_[j][0] for j in same) / bal)
        elif i in open_:
            risk, side = open_.pop(i)
            bal += risk * t["r"]
            peak = max(peak, bal)
            dd = max(dd, 1 - bal / peak)
            curve.append((tm, bal))
            if crowd is not None and not any(s == crowd["side"] for _, s in open_.values()):
                crowd.update(end=tm, bal1=bal)
                crowds.append(crowd)
                crowd = None
    return curve, crowds, dd, bal


def main() -> None:
    conn = sqlite3.connect(f"file:{mt.LONG4}?mode=ro", uri=True)
    signals = [t for t in ct.load(conn, 1, mt.START4, ("XRP", "SOL", "ETH")) if t["closed"] and t["tf"] == "15m"]
    e3 = [x for x in (et.dip_candle_entry(conn, t) for t in signals) if x is not None]
    taken = at.policy(conn, e3, ("15m",), None)
    for label, corr in (("max 2 per coin, up to 6 open (no cap)", None), ("B: max 2 per coin + max 2 same direction across coins", 2)):
        curve, crowds, dd, bal = replay(taken, corr)
        print(f"\n== {label}: $150 -> ${bal:,.0f}, max DD {dd:.1%}")
        days = defaultdict(float)
        prev = 150.0
        for tm, b in curve:
            days[time.strftime("%Y-%m-%d", time.gmtime(tm / 1000))] += (b - prev) / prev
            prev = b
        worst_days = sorted(days.items(), key=lambda x: x[1])[:5]
        print("   worst days:", ", ".join(f"{d} {v:+.1%}" for d, v in worst_days))
        print(f"   times with 3+ same-direction positions open together: {len(crowds)}")
        by = defaultdict(list)
        for c in crowds:
            by[c["max"]].append(c["bal1"] / c["bal0"] - 1)
        for k in sorted(by):
            v = by[k]
            print(f"     at most {k} open together: {len(v):4d} times | won {sum(x > 0 for x in v) / len(v):4.0%} |"
                  f" average {sum(v) / len(v):+5.1%} | best {max(v):+5.1%} | worst {min(v):+5.1%}")
        worst = sorted(crowds, key=lambda c: c["bal1"] / c["bal0"])[:3]
        for c in worst:
            print(f"     worst: {time.strftime('%Y-%m-%d %H:%M', time.gmtime(c['start'] / 1000))} {c['side']}, {c['max']} open,"
                  f" risk at stops {c['risk']:.1%} of the balance -> {c['bal1'] / c['bal0'] - 1:+.1%}")


if __name__ == "__main__":
    main()
