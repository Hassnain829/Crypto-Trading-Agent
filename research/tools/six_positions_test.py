r"""Max 2 positions per coin on XRP/SOL/ETH (up to 6 open), entries on the 5m dip (E3): how a same-direction cap across
coins and the drawdown brake change it (the user, 2026-10-21). Research only.

    .venv\Scripts\python -u research\tools\six_positions_test.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ct, mt, at, et, a2 = (_load(n) for n in ("coordination_test", "mtf_test", "addon_test", "entry_timing_test", "addon2_test"))


def max_open(taken: list[dict]) -> Counter:
    """How often 1..6 positions were open together (counted at each entry)."""
    c, ev = Counter(), sorted([(t["entry"], 1) for t in taken] + [(t["exit"], -1) for t in taken])
    n = 0
    for _, d in ev:
        n += d
        if d == 1:
            c[n] += 1
    return c


def main() -> None:
    conn = sqlite3.connect(f"file:{mt.LONG4}?mode=ro", uri=True)
    signals = [t for t in ct.load(conn, 1, mt.START4, ("XRP", "SOL", "ETH")) if t["closed"] and t["tf"] == "15m"]
    e3 = [x for x in (et.dip_candle_entry(conn, t) for t in signals) if x is not None]
    taken = at.policy(conn, e3, ("15m",), None)  # max 2 per coin, same direction, opposite skipped
    seen = max_open(taken)
    print(f"A1+E3 (max 2 per coin, both entries on a 5m dip): {len(taken)} trades; positions open at an entry:",
          ", ".join(f"{k}: {seen[k] / len(taken):.0%}" for k in sorted(seen)))
    print(f"   {'same-direction cap across coins':34} {'brake':6} | {'$150 over 4 years':>20} {'max DD':>7} | {'2022-24':>16} | {'2024-26':>16}")
    for cap in (None, 4, 3, 2):
        for brake in (None, 0.10):
            bal, dd = a2.account(taken, corr=cap, brake=brake)
            b1 = a2.account([t for t in taken if t["entry"] < mt.SPLIT], corr=cap, brake=brake)
            b2 = a2.account([t for t in taken if t["entry"] >= mt.SPLIT], corr=cap, brake=brake)
            label = "none (up to 6 open)" if cap is None else f"{cap} (up to {min(6, 2 * cap)} open)"
            print(f"   {label:34} {'yes' if brake else 'no':6} | ${bal:9,.0f} ({bal / 150 - 1:+6.0%}) {dd:6.1%} |"
                  f" {b1[0] / 150 - 1:+6.0%} (DD {b1[1]:3.0%}) | {b2[0] / 150 - 1:+6.0%} (DD {b2[1]:3.0%})", flush=True)


if __name__ == "__main__":
    main()
