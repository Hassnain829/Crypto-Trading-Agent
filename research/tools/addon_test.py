"""One direction per coin with up to two same-direction positions (the user's question of 2026-10-21), on 4 years.

    .venv\\Scripts\\python -u research\\tools\\addon_test.py

- The 15m signal opens the first position. While a coin has a position, an opposite signal is skipped.
- A new signal in the same direction may add a second position (never more than two open per coin):
  only 15m signals (A) or 15m and 5m signals (B).
- The second position's target: its own 1.5R (as now), a smaller 1.0R, or the first position's target price.
  Changed targets are re-simulated on the 1m candles with the agent's own simulator (fees, slippage, funding,
  72-hour timeout).
Research only; trades come from the long backtests.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ct = _load("coordination_test")
dt = _load("demo_ideas_test")
mt = _load("mtf_test")
op = _load("one_position_test")
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "src"))
from tradeagent.config import load_settings  # noqa: E402
from tradeagent.sim.simulator import Costs, apply_funding, close_now, open_trade, results, step  # noqa: E402

settings = load_settings(ROOT)
COSTS = Costs(settings.costs.maker_fee, settings.costs.taker_fee, settings.costs.slippage)
MAX_HOLD = int(settings.shadow.max_hold_hours * 3_600_000)
TP_R = 1.5


def target_of(t: dict, r_mult: float = TP_R) -> float:
    sign = 1 if t["side"] == "long" else -1
    return t["entry_ref"] + sign * r_mult * abs(t["entry_ref"] - t["stop"])


def resim(conn: sqlite3.Connection, t: dict, target: float) -> tuple[float, int]:
    """The trade again with another take-profit price: (r_net, exit time)."""
    sign = 1 if t["side"] == "long" else -1
    tp_r = sign * (target - t["entry_ref"]) / abs(t["entry_ref"] - t["stop"])
    state = open_trade(side=t["side"], mode="fixed", entry_time=t["entry"], entry_ref=t["entry_ref"], stop=t["stop"],
                       take_profit_r=tp_r, partial_r=1.0, partial_fraction=0.5, trail_lookback=3, costs=COSTS, limit_entry=True)
    state.target = target
    funding = conn.execute("SELECT funding_time, rate FROM funding WHERE symbol = ? AND funding_time > ? AND funding_time < ?"
                           " ORDER BY funding_time", (t["symbol"], t["entry"], t["entry"] + MAX_HOLD + 60_000)).fetchall()
    nf = 0
    for ot, o, h, l, c in conn.execute("SELECT open_time, open, high, low, close FROM candles WHERE symbol = ? AND timeframe = '1m'"
                                       " AND open_time >= ? AND open_time <= ? ORDER BY open_time",
                                       (t["symbol"], t["entry"], t["entry"] + MAX_HOLD + 60_000)):
        while nf < len(funding) and funding[nf][0] <= ot:
            apply_funding(state, funding[nf][1], o)
            nf += 1
        if ot - t["entry"] >= MAX_HOLD:
            close_now(state, ot, o, COSTS, "timeout")
            break
        step(state, (ot, o, h, l, c), COSTS)
        if state.closed:
            break
    if not state.closed:
        return t["r"], t["exit"]
    return results(state, COSTS)["r_net"], state.legs[-1].time


def policy(conn: sqlite3.Connection, trades: list[dict], add_from: tuple[str, ...], add_target: str | None) -> list[dict]:
    """15m opens; up to two same-direction positions per coin; opposite signals skipped while a position is open.
    add_from: the charts whose signals may add the second position (empty = one position per coin)."""
    out, active = [], {}
    for t in sorted(trades, key=lambda x: (x["entry"], x["tf"] != "15m", x["id"])):
        live = [o for o in active.get(t["symbol"], []) if o["exit"] > t["entry"]]
        active[t["symbol"]] = live
        cur = dict(t)
        if not live:
            if t["tf"] != "15m":
                continue  # only the 15m chart opens a coin's first position
        else:
            if any(o["side"] != t["side"] for o in live) or len(live) >= 2 or t["tf"] not in add_from:
                continue
            cur["addon"] = True
            if add_target == "1.0R":
                cur["r"], cur["exit"] = resim(conn, cur, target_of(cur, 1.0))
            elif add_target == "first":
                first = min(live, key=lambda o: o["entry"])
                tp = first.get("tp", target_of(first))
                sign = 1 if t["side"] == "long" else -1
                if sign * (tp - t["entry_ref"]) > 0:  # the first target is still ahead of this entry
                    cur["r"], cur["exit"] = resim(conn, cur, tp)
                    cur["tp"] = tp
        out.append(cur)
        live.append(cur)
    return out


POLICIES = {
    "15m only + one position per coin (C6)": ((), None),
    "A1 15m add-on, own 1.5R target": (("15m",), None),
    "A2 15m add-on, 1.0R target": (("15m",), "1.0R"),
    "A3 15m add-on, the first trade's target": (("15m",), "first"),
    "B1 15m or 5m add-on, own 1.5R target": (("15m", "5m"), None),
    "B2 15m or 5m add-on, 1.0R target": (("15m", "5m"), "1.0R"),
    "B3 15m or 5m add-on, the first trade's target": (("15m", "5m"), "first"),
}


def stop_stats(taken: list[dict]) -> str:
    stops = [t for t in taken if t["r"] <= -0.9]
    together, by_coin = 0, {}
    for t in sorted(stops, key=lambda x: x["exit"]):
        prev = by_coin.get(t["symbol"])
        if prev is not None and abs(t["exit"] - prev) <= 60 * 60_000:
            together += 1  # a second stop of the coin within the hour (both positions stopped in one move)
        by_coin[t["symbol"]] = t["exit"]
    run = worst = 0
    for t in sorted(taken, key=lambda x: x["exit"]):
        run = run + 1 if t["r"] < 0 else 0
        worst = max(worst, run)
    return f"{len(stops):5d} SL ({len(stops) / max(len(taken), 1):4.0%}) {together:4d} double {worst:3d} streak"


def table(title: str, conn: sqlite3.Connection, coins: list[str], start: int, years: list[tuple[int, int]], split: int | None) -> None:
    trades = [t for t in ct.load(conn, 1, start, tuple(coins)) if t["closed"]]
    fmt = lambda ms: time.strftime("%Y-%m", time.gmtime(ms / 1000))
    print(f"\n== {title}: {len(trades)} signals taken by the engine")
    head = (f"   {'policy':46} {'trades':>6} {'add-ons':>7} {'R/tr':>7} " + " ".join(f"{fmt(a):>8}" for a, _ in years)
            + f" {'total':>7} {'DD R':>5} | {'stops':>34} | {'$150 whole':>17} {'DD':>6}")
    if split:
        head += " | in-sample        | out-of-sample"
    print(head)
    rows = {"now (every signal)": [dict(t) for t in trades]}
    for name, (add_from, tgt) in POLICIES.items():
        rows[name] = policy(conn, trades, add_from, tgt)
    for name, taken in rows.items():
        line = (f"   {name:46} {len(taken):6d} {sum(1 for t in taken if t.get('addon')):7d}"
                f" {sum(t['r'] for t in taken) / max(len(taken), 1):+7.3f} ")
        for a, b in years:
            rs = [t["r"] for t in taken if a <= t["entry"] < b]
            line += f" {sum(rs) / len(rs) if rs else 0:+7.3f}"
        bal, dd = dt.account(taken)
        line += f" {sum(t['r'] for t in taken):+7.1f} {mt.maxdd_r(taken):5.1f} | {stop_stats(taken)} | ${bal:9,.0f} ({bal / 150 - 1:+5.0%}) {dd:5.1%}"
        if split:
            b1, d1 = dt.account([t for t in taken if t["entry"] < split])
            b2, d2 = dt.account([t for t in taken if t["entry"] >= split])
            line += f" | {b1 / 150 - 1:+5.0%} DD {d1:4.0%} | {b2 / 150 - 1:+5.0%} DD {d2:4.0%}"
        print(line, flush=True)


def check_resim(conn: sqlite3.Connection) -> None:
    trades = [t for t in ct.load(conn, 1, mt.START4, ("XRP",)) if t["closed"]][:200]
    diffs = [abs(resim(conn, t, target_of(t))[0] - t["r"]) for t in trades]
    print(f"re-simulation check on 200 XRP trades with their own target: max |difference| {max(diffs):.4f}R,"
          f" {sum(d > 0.01 for d in diffs)} above 0.01R")


def main() -> None:
    conn = sqlite3.connect(f"file:{mt.LONG4}?mode=ro", uri=True)
    check_resim(conn)
    years4 = [(mt.START4 + k * 365 * mt.DAY, mt.START4 + (k + 1) * 365 * mt.DAY) for k in range(4)]
    table("MAIN: XRP, SOL, ETH, 4 years (in-sample before 2024-10-01)", conn, ["XRP", "SOL", "ETH"], mt.START4, years4, mt.SPLIT)
    table("REPLICATION: BTC, 4 years", conn, ["BTC"], mt.START4, years4, mt.SPLIT)
    conn.close()
    conn = sqlite3.connect(f"file:{mt.LONG}?mode=ro", uri=True)
    s = mt.START15
    years15 = [(s, s + 182 * mt.DAY), (s + 182 * mt.DAY, s + 365 * mt.DAY), (s + 365 * mt.DAY, s + 548 * mt.DAY)]
    table("REPLICATION: 10 check coins, 1.5 years", conn, ["BNB", "DOGE", "LTC", "ADA", "LINK", "AVAX", "NEAR", "SUI", "ZEC", "BTC"],
          s, years15, None)
    conn.close()


if __name__ == "__main__":
    main()
