"""The first position from the 15m signal, the second (same direction, max 2 per coin) timed on a 5m dip; and ways to
cut the drawdown (the user, 2026-10-21). Research only.

    .venv\\Scripts\\python -u research\\tools\\addon2_test.py

Designs (opposite signals are always skipped while a coin has a position; 15m only opens a coin's first position):
- C6        one position per coin, entry at the next 1m open
- C6+E3     one position per coin, every entry timed on the first 5m candle against the trade (else 1 h)
- A1+E3     two per coin, both entries timed as E3
- F1        first entry now; a second same-direction 15m signal is entered on its E3 5m dip
- F3        first entry now; a same-direction 5m signal while the first is open is entered on its E3 5m dip
- F4        first entry now; a limit 0.5R below the first entry (above for shorts) adds a second position with the
            first one's stop and target, while the first is open
Drawdown levers on top (risk A 3% / B 2%, 12% budget unless said):
- corr2     at most 2 open positions in the same direction across all coins
- brake     risk halved while the balance is more than 10% below its peak
- 1%        1% a trade (reference)
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


ct, mt, at, et = (_load(n) for n in ("coordination_test", "mtf_test", "addon_test", "entry_timing_test"))


def account(taken: list[dict], ra: float = .03, rb: float = .02, budget: float = .12, corr: int | None = None,
            brake: float | None = None) -> tuple[float, float]:
    ev = []
    for i, t in enumerate(taken):
        ev += [(t["entry"], 1, i), (t["exit"], 0, i)]
    ev.sort()
    bal = peak = 150.0
    dd, open_ = 0.0, {}
    for _, kind, i in ev:
        t = taken[i]
        if kind == 1:
            if corr is not None and sum(1 for j in open_ if taken[j]["side"] == t["side"]) >= corr:
                continue
            scale = 0.5 if brake is not None and bal < peak * (1 - brake) else 1.0
            room = budget * bal - sum(open_.values())
            risk = min(bal * (ra if t["q"] == "A" else rb) * scale, room)
            if risk > 0.001 * bal:
                open_[i] = risk
        elif i in open_:
            bal += open_.pop(i) * t["r"]
            peak = max(peak, bal)
            dd = max(dd, 1 - bal / peak)
    return bal, dd


def mixed(conn: sqlite3.Connection, firsts: list[dict], adds: list[dict]) -> list[dict]:
    """First positions from `firsts` (15m, entered now); second positions from `adds` (already timed), max 2 per coin,
    same direction only. Both lists are decided in the order of their decision time ('t0')."""
    events = sorted([("f", t) for t in firsts] + [("a", t) for t in adds], key=lambda x: (x[1]["t0"], x[0] != "f"))
    out, active = [], {}
    for kind, t in events:
        live = [o for o in active.get(t["symbol"], []) if o["exit"] > t["entry"]]
        active[t["symbol"]] = live
        if kind == "f":
            if live:
                continue
        else:
            if not live or len(live) >= 2 or any(o["side"] != t["side"] for o in live):
                continue
            if t["id"] < 0 and not any(o["id"] == -t["id"] for o in live):
                continue  # F4: a dip add belongs to its own first position
            if any(o["id"] == t["id"] for o in out):
                continue  # F1: a signal that already opened the first position cannot add to itself
        cur = {**t, "addon": kind == "a"}
        out.append(cur)
        live.append(cur)
    return out


def dip_adds(conn: sqlite3.Connection, firsts: list[dict], k: float = 0.5) -> list[dict]:
    """F4: a limit k R beyond the first entry while the first position is open; the first one's stop and target."""
    out = []
    for f in firsts:
        sign = 1 if f["side"] == "long" else -1
        risk = abs(f["entry_ref"] - f["stop"])
        limit, tp = f["entry_ref"] - sign * k * risk, at.target_of(f)
        for ot, o, h, l in conn.execute("SELECT open_time, open, high, low FROM candles WHERE symbol = ? AND timeframe = '1m'"
                                        " AND open_time > ? AND open_time < ? ORDER BY open_time", (f["symbol"], f["entry"], f["exit"])):
            if (sign > 0 and l <= limit) or (sign < 0 and h >= limit):
                fill = min(o, limit) if sign > 0 else max(o, limit)
                res = et.simulate(conn, f, ot, fill, tp)
                if res is not None:
                    out.append({**f, "id": -f["id"], "entry": ot, "r": res[0], "exit": res[1], "t0": ot})
                break
    return out


def report(title: str, conn: sqlite3.Connection, coins: list[str], start: int, split: int | None, levers: bool) -> None:
    signals = [t for t in ct.load(conn, 1, start, tuple(coins)) if t["closed"]]
    s15 = [dict(t, t0=t["entry"]) for t in signals if t["tf"] == "15m"]
    s5 = [dict(t, t0=t["entry"]) for t in signals if t["tf"] == "5m"]
    e3_15 = [dict(x, t0=t["entry"]) for t, x in ((t, et.dip_candle_entry(conn, t)) for t in s15) if x is not None]
    e3_5 = [dict(x, t0=t["entry"]) for t, x in ((t, et.dip_candle_entry(conn, t)) for t in s5) if x is not None]
    designs = {
        "C6 (one per coin, entry now)": at.policy(conn, s15, (), None),
        "C6+E3 (one per coin, 5m dip entry)": at.policy(conn, e3_15, (), None),
        "A1+E3 (two per coin, both on a 5m dip)": at.policy(conn, e3_15, ("15m",), None),
        "F1 first now, 2nd 15m signal on a 5m dip": mixed(conn, s15, e3_15),
        "F3 first now, 2nd from a 5m signal on a dip": mixed(conn, s15, e3_5),
    }
    c6 = designs["C6 (one per coin, entry now)"]
    designs["F4 first now, add at a 0.5R dip (same SL/TP)"] = mixed(conn, s15, dip_adds(conn, c6))
    print(f"\n== {title}")
    for name, taken in designs.items():
        rs = [t["r"] for t in taken]
        adds = [t["r"] for t in taken if t.get("addon")]
        bal, dd = account(taken)
        line = (f"   {name:46} {len(taken):5d} trades ({len(adds):4d} 2nd, {sum(adds) / len(adds) if adds else 0:+.3f}R)"
                f" {sum(rs) / len(rs):+.3f}R | ${bal:9,.0f} ({bal / 150 - 1:+6.0%}) DD {dd:5.1%}")
        if split:
            b1 = account([t for t in taken if t["entry"] < split])
            b2 = account([t for t in taken if t["entry"] >= split])
            line += f" | 2022-24 {b1[0] / 150 - 1:+6.0%} (DD {b1[1]:3.0%}) | 2024-26 {b2[0] / 150 - 1:+6.0%} (DD {b2[1]:3.0%})"
        print(line, flush=True)
        if levers:
            for lname, kw in (("  + corr2 (max 2 same-direction across coins)", {"corr": 2}),
                              ("  + brake (half risk 10% below the peak)", {"brake": 0.10}),
                              ("  + corr2 + brake", {"corr": 2, "brake": 0.10}),
                              ("  at 1% a trade (reference)", {"ra": .01, "rb": .01, "budget": .06})):
                bal, dd = account(taken, **kw)
                line = f"   {lname:46} {'':40} | ${bal:9,.0f} ({bal / 150 - 1:+6.0%}) DD {dd:5.1%}"
                if split:
                    b1 = account([t for t in taken if t["entry"] < split], **kw)
                    b2 = account([t for t in taken if t["entry"] >= split], **kw)
                    line += f" | 2022-24 {b1[0] / 150 - 1:+6.0%} (DD {b1[1]:3.0%}) | 2024-26 {b2[0] / 150 - 1:+6.0%} (DD {b2[1]:3.0%})"
                print(line, flush=True)


def main() -> None:
    conn = sqlite3.connect(f"file:{mt.LONG4}?mode=ro", uri=True)
    report("MAIN: XRP, SOL, ETH, 4 years", conn, ["XRP", "SOL", "ETH"], mt.START4, mt.SPLIT, True)
    report("REPLICATION: BTC, 4 years", conn, ["BTC"], mt.START4, mt.SPLIT, False)
    conn.close()
    conn = sqlite3.connect(f"file:{mt.LONG}?mode=ro", uri=True)
    report("REPLICATION: 10 check coins, 1.5 years", conn, ["BNB", "DOGE", "LTC", "ADA", "LINK", "AVAX", "NEAR", "SUI", "ZEC", "BTC"],
           mt.START15, None, False)
    conn.close()


if __name__ == "__main__":
    main()
