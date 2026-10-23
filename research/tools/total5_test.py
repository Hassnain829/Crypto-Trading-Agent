r"""The user's final rules (2026-10-21): at most 5 open positions in total (any direction), every coin may always hold
its first one, a second same-direction position per coin when there is room; opposite signals skipped; 15m signals
with 5m dip entries; A 3% / B 2%, 12% budget; with and without the brake. Research only.

    .venv\Scripts\python -u research\tools\total5_test.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ct, mt, at, et, a2, ud = (_load(n) for n in ("coordination_test", "mtf_test", "addon_test", "entry_timing_test", "addon2_test",
                                            "user_design_test"))


def total_cap(signals: list[dict], cap: int) -> list[dict]:
    out, active = [], {}
    for t in sorted(signals, key=lambda x: (x["entry"], x["id"])):
        for sym in list(active):
            active[sym] = [o for o in active[sym] if o["exit"] > t["entry"]]
        live = active.get(t["symbol"], [])
        cur = dict(t)
        if live:
            if any(o["side"] != t["side"] for o in live) or len(live) >= 2:
                continue
            if sum(len(ps) for ps in active.values()) >= cap:
                continue  # the 5-position total is full: only a coin's first position may still open
            cur["addon"] = True
        out.append(cur)
        active.setdefault(t["symbol"], []).append(cur)
    return out


def main() -> None:
    conn = sqlite3.connect(f"file:{mt.LONG4}?mode=ro", uri=True)
    signals = [t for t in ct.load(conn, 1, mt.START4, ("XRP", "SOL", "ETH")) if t["closed"] and t["tf"] == "15m"]
    e3 = [x for x in (et.dip_candle_entry(conn, t) for t in signals) if x is not None]
    taken = total_cap(e3, 5)
    adds = [t["r"] for t in taken if t.get("addon")]
    for label, kw in (("total 5, no brake", {}), ("total 5 + brake", {"brake": 0.10})):
        bal, dd = a2.account(taken, **kw)
        b1 = a2.account([t for t in taken if t["entry"] < mt.SPLIT], **kw)
        b2 = a2.account([t for t in taken if t["entry"] >= mt.SPLIT], **kw)
        print(f"{label:20} {len(taken)} trades ({len(adds)} second, {sum(adds) / len(adds):+.3f}R) | $150 -> ${bal:,.0f}"
              f" ({bal / 150 - 1:+.0%}) max DD {dd:.1%} worst day {ud.worst_day(taken, **kw):+.1%} |"
              f" 2022-24 {b1[0] / 150 - 1:+.0%} (DD {b1[1]:.0%}) | 2024-26 {b2[0] / 150 - 1:+.0%} (DD {b2[1]:.0%})")
    # the deepest fall, with dates, for the explanation of the drawdown
    import time
    for label, kw in (("no brake", {}), ("brake", {"brake": 0.10})):
        ev = []
        for i, t in enumerate(taken):
            ev += [(t["entry"], 1, i), (t["exit"], 0, i)]
        ev.sort()
        bal = peak = 150.0
        peak_t, worst = ev[0][0], (0.0, 0, 0, 0.0, 0.0)
        open_ = {}
        for tm, kind, i in ev:
            t = taken[i]
            if kind == 1:
                scale = 0.5 if kw.get("brake") and bal < peak * (1 - kw["brake"]) else 1.0
                room = 0.12 * bal - sum(open_.values())
                risk = min(bal * (0.03 if t["q"] == "A" else 0.02) * scale, room)
                if risk > 0.001 * bal:
                    open_[i] = risk
            elif i in open_:
                bal += open_.pop(i) * t["r"]
                if bal > peak:
                    peak, peak_t = bal, tm
                if 1 - bal / peak > worst[0]:
                    worst = (1 - bal / peak, peak_t, tm, peak, bal)
        f = lambda ms: time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))
        print(f"deepest fall ({label}): from ${worst[3]:,.0f} on {f(worst[1])} down to ${worst[4]:,.0f} on {f(worst[2])} = -{worst[0]:.1%}")


if __name__ == "__main__":
    main()
