"""The 15m decides, the 5m times the entry (research/notes/2026-10-21-entry-timing-plan.md). Research only.

    .venv\\Scripts\\python -u research\\tools\\entry_timing_test.py
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ct, dt, mt, at = (_load(n) for n in ("coordination_test", "demo_ideas_test", "mtf_test", "addon_test"))
sys.path.insert(0, str(ROOT / "src"))
from tradeagent.sim.simulator import apply_funding, close_now, open_trade, results, step  # noqa: E402

COSTS, MAX_HOLD = at.COSTS, at.MAX_HOLD
M1, M5 = 60_000, 300_000


def simulate(conn: sqlite3.Connection, t: dict, entry_time: int, entry_px: float, target: float) -> tuple[float, int] | None:
    sign = 1 if t["side"] == "long" else -1
    if sign * (entry_px - t["stop"]) <= 0 or sign * (target - entry_px) <= 0:
        return None
    tp_r = sign * (target - entry_px) / abs(entry_px - t["stop"])
    state = open_trade(side=t["side"], mode="fixed", entry_time=entry_time, entry_ref=entry_px, stop=t["stop"],
                       take_profit_r=tp_r, partial_r=1.0, partial_fraction=0.5, trail_lookback=3, costs=COSTS, limit_entry=True)
    state.target = target
    funding = conn.execute("SELECT funding_time, rate FROM funding WHERE symbol = ? AND funding_time > ? AND funding_time < ?"
                           " ORDER BY funding_time", (t["symbol"], entry_time, entry_time + MAX_HOLD + M1)).fetchall()
    nf = 0
    for ot, o, h, l, c in conn.execute("SELECT open_time, open, high, low, close FROM candles WHERE symbol = ? AND timeframe = '1m'"
                                       " AND open_time >= ? AND open_time <= ? ORDER BY open_time",
                                       (t["symbol"], entry_time, entry_time + MAX_HOLD + M1)):
        while nf < len(funding) and funding[nf][0] <= ot:
            apply_funding(state, funding[nf][1], o)
            nf += 1
        if ot - entry_time >= MAX_HOLD:
            close_now(state, ot, o, COSTS, "timeout")
            break
        step(state, (ot, o, h, l, c), COSTS)
        if state.closed:
            break
    if not state.closed:
        return None
    return results(state, COSTS)["r_net"], state.legs[-1].time


def touched_before(conn: sqlite3.Connection, t: dict, target: float, until: int) -> bool:
    """Did the price reach the stop or the target between the planned entry and `until`?"""
    sign = 1 if t["side"] == "long" else -1
    row = conn.execute("SELECT min(low), max(high) FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time >= ?"
                       " AND open_time < ?", (t["symbol"], t["entry"], until)).fetchone()
    if row[0] is None:
        return False
    lo, hi = row
    return (lo <= t["stop"] or hi >= target) if sign > 0 else (hi >= t["stop"] or lo <= target)


def limit_entry(conn: sqlite3.Connection, t: dict, k: float, keep_tp: bool) -> dict | None:
    sign = 1 if t["side"] == "long" else -1
    risk = abs(t["entry_ref"] - t["stop"])
    tp0 = at.target_of(t)
    limit = t["entry_ref"] - sign * k * risk
    for ot, o, h, l in conn.execute("SELECT open_time, open, high, low FROM candles WHERE symbol = ? AND timeframe = '1m'"
                                    " AND open_time >= ? AND open_time < ? ORDER BY open_time",
                                    (t["symbol"], t["entry"], t["entry"] + 2 * 3_600_000)):
        if (sign > 0 and l <= limit) or (sign < 0 and h >= limit):
            fill = min(o, limit) if sign > 0 else max(o, limit)
            if sign * (fill - t["stop"]) <= 0:
                return None  # opened beyond the stop
            target = tp0 if keep_tp else fill + sign * at.TP_R * abs(fill - t["stop"])
            res = simulate(conn, t, ot, fill, target)
            return None if res is None else {**t, "entry": ot, "r": res[0], "exit": res[1]}
        if (sign > 0 and h >= tp0) or (sign < 0 and l <= tp0):
            return None  # the move went without us
    return None


def five_min(conn: sqlite3.Connection, symbol: str, start: int, bars: int) -> list[tuple]:
    return conn.execute("SELECT open_time, open, high, low, close FROM candles WHERE symbol = ? AND timeframe = '5m'"
                        " AND open_time >= ? ORDER BY open_time LIMIT ?", (symbol, start, bars + 1)).fetchall()


def dip_candle_entry(conn: sqlite3.Connection, t: dict) -> dict | None:
    sign = 1 if t["side"] == "long" else -1
    tp0 = at.target_of(t)
    rows = five_min(conn, t["symbol"], t["entry"], 12)
    when = None
    for i, (ot, o, h, l, c) in enumerate(rows[:-1]):
        if sign * (c - o) < 0:  # a candle against the trade
            when = rows[i + 1][0]
            break
    if when is None:
        when = t["entry"] + 3_600_000
    if touched_before(conn, t, tp0, when):
        return None
    row = conn.execute("SELECT open FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time >= ? ORDER BY open_time LIMIT 1",
                       (t["symbol"], when)).fetchone()
    if row is None:
        return None
    res = simulate(conn, t, when, row[0], tp0)
    return None if res is None else {**t, "entry": when, "r": res[0], "exit": res[1]}


def klinger_entry(conn: sqlite3.Connection, t: dict) -> dict | None:
    sign = 1 if t["side"] == "long" else -1
    tp0 = at.target_of(t)
    snaps = conn.execute("SELECT bar_time, values_json FROM snapshots WHERE symbol = ? AND timeframe = '5m' AND bar_time >= ?"
                         " AND bar_time < ? ORDER BY bar_time", (t["symbol"], t["entry"] - M5, t["entry"] + 2 * 3_600_000)).fetchall()
    prev, when = None, None
    for bt, v in snaps:
        hist = (json.loads(v).get("klinger") or {}).get("hist")
        if hist is None:
            continue
        if prev is not None and sign * prev < 0 <= sign * hist and bt >= t["entry"]:
            when = bt + M5  # known when that 5m candle closes
            break
        prev = hist
    if when is None or touched_before(conn, t, tp0, when):
        return None
    row = conn.execute("SELECT open FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time >= ? ORDER BY open_time LIMIT 1",
                       (t["symbol"], when)).fetchone()
    if row is None:
        return None
    res = simulate(conn, t, when, row[0], tp0)
    return None if res is None else {**t, "entry": when, "r": res[0], "exit": res[1]}


ENTRIES = {
    "E0 now (next 1m open)": lambda c, t: dict(t),
    "E1 limit 0.25R better, TP same": lambda c, t: limit_entry(c, t, 0.25, True),
    "E1b limit 0.25R better, TP 1.5R from fill": lambda c, t: limit_entry(c, t, 0.25, False),
    "E2 limit 0.5R better, TP same": lambda c, t: limit_entry(c, t, 0.5, True),
    "E3 first 5m dip candle (else 1 h)": dip_candle_entry,
    "E4 5m Klinger turns back": klinger_entry,
}


def table(title: str, conn: sqlite3.Connection, coins: list[str], start: int, split: int | None) -> None:
    signals = [t for t in ct.load(conn, 1, start, tuple(coins)) if t["closed"] and t["tf"] == "15m"]
    print(f"\n== {title}: {len(signals)} 15m signals")
    for name, fn in ENTRIES.items():
        made = [x for x in (fn(conn, t) for t in signals) if x is not None]
        for pol_name, add_from in (("C6", ()), ("A1", ("15m",))):
            taken = at.policy(conn, made, add_from, None)
            rs = [t["r"] for t in taken]
            bal, dd = dt.account(taken)
            line = (f"   {name:40} {pol_name} {len(made) / len(signals):4.0%} entered {len(taken):5d} taken {sum(rs) / len(rs):+.3f}R"
                    f" win {sum(r > 0 for r in rs) / len(rs):4.0%} | ${bal:9,.0f} ({bal / 150 - 1:+6.0%}) DD {dd:5.1%}")
            if split:
                b1 = dt.account([t for t in taken if t["entry"] < split])
                b2 = dt.account([t for t in taken if t["entry"] >= split])
                line += f" | 2022-24 {b1[0] / 150 - 1:+6.0%} (DD {b1[1]:3.0%}) | 2024-26 {b2[0] / 150 - 1:+6.0%} (DD {b2[1]:3.0%})"
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
