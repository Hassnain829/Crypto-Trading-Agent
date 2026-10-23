"""Three more ways to keep one position per coin (the user, 2026-10-21), on 4 years, next to C6.

    .venv\\Scripts\\python -u research\\tools\\c6_variants.py

All use only 15m signals and never hold long and short together:
- C6   one position per coin; every new signal of the coin is skipped while it is open
- V1   C6, but a B signal is taken only when its squeeze released (A signals always)
- V2   an opposite 15m signal closes the open position (at its entry) and opens nothing: signals act as exits
- V3   an opposite 15m signal closes the open position and opens the new one (always in the market's latest direction)
Same-direction signals are skipped in all of them. Research only.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ct, dt, mt, at, op = (_load(n) for n in ("coordination_test", "demo_ideas_test", "mtf_test", "addon_test", "one_position_test"))


def run(conn: sqlite3.Connection, trades: list[dict], mode: str) -> list[dict]:
    out, held = [], {}
    for t in sorted(trades, key=lambda x: (x["entry"], x["id"])):
        if t["tf"] != "15m":
            continue
        if mode == "V1" and t["q"] == "B" and t["sqz"] is not True:
            continue
        h = held.get(t["symbol"])
        if h is not None and h["exit"] <= t["entry"]:
            h = None
        if h is None:
            cur = dict(t)
            out.append(cur)
            held[t["symbol"]] = cur
            continue
        if h["side"] == t["side"] or mode in ("C6", "V1"):
            continue  # same direction, or C6/V1: skip while a position is open
        r = ct.price_r(conn, h, t["entry"])  # V2/V3: the opposite signal closes the open position
        if r is not None:
            h["r"], h["exit"] = r, t["entry"]
        held[t["symbol"]] = None
        if mode == "V3":
            cur = dict(t)
            out.append(cur)
            held[t["symbol"]] = cur
    return out


def table(title: str, conn: sqlite3.Connection, coins: list[str], start: int, split: int | None) -> None:
    trades = [t for t in ct.load(conn, 1, start, tuple(coins)) if t["closed"]]
    print(f"\n== {title}")
    for mode, label in (("C6", "C6 one position per coin"), ("V1", "V1 C6 + B only with a squeeze release"),
                        ("V2", "V2 an opposite signal only closes"), ("V3", "V3 an opposite signal reverses")):
        taken = run(conn, trades, mode)
        rs = [t["r"] for t in taken]
        bal, dd = dt.account(taken)
        stops = sum(r <= -0.9 for r in rs)
        line = (f"   {label:40} {len(taken):5d} trades {sum(rs) / len(rs):+.3f}R win {sum(r > 0 for r in rs) / len(rs):4.0%}"
                f" SL {stops / len(rs):4.0%} DD {mt.maxdd_r(taken):5.1f}R | ${bal:8,.0f} ({bal / 150 - 1:+5.0%}) DD {dd:5.1%}")
        if split:
            b1 = dt.account([t for t in taken if t["entry"] < split])
            b2 = dt.account([t for t in taken if t["entry"] >= split])
            yrs = [sum(t["r"] for t in taken if mt.START4 + k * 365 * mt.DAY <= t["entry"] < mt.START4 + (k + 1) * 365 * mt.DAY)
                   for k in range(4)]
            line += (f" | 2022-24 {b1[0] / 150 - 1:+5.0%} (DD {b1[1]:3.0%}) | 2024-26 {b2[0] / 150 - 1:+5.0%} (DD {b2[1]:3.0%})"
                     f" | years " + " ".join(f"{y:+5.1f}" for y in yrs))
        print(line, flush=True)


def main() -> None:
    conn = sqlite3.connect(f"file:{mt.LONG4}?mode=ro", uri=True)
    table("MAIN: XRP, SOL, ETH, 4 years", conn, ["XRP", "SOL", "ETH"], mt.START4, mt.SPLIT)
    table("REPLICATION: BTC, 4 years", conn, ["BTC"], mt.START4, mt.SPLIT)
    conn.close()
    conn = sqlite3.connect(f"file:{mt.LONG}?mode=ro", uri=True)
    table("REPLICATION: 10 check coins, 1.5 years", conn, ["BNB", "DOGE", "LTC", "ADA", "LINK", "AVAX", "NEAR", "SUI", "ZEC", "BTC"],
          mt.START15, None)
    conn.close()


if __name__ == "__main__":
    main()
