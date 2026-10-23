"""One decision per coin from the 5m and 15m charts, on 4 years (research/notes/2026-10-21-mtf-plan.md).

    .venv\\Scripts\\python -u research\\tools\\mtf_test.py

Trades come from the long backtests (the agent's engine on the Python copies of the open-source indicators). The 1h
and 4h Q-Trend directions are computed from 15m candles with the same inputs (long_indicators.qtrend). Research only.
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
li = _load("long_indicators")
LONG4 = ROOT / "data" / "research" / "long4" / "journal.db"
LONG = ROOT / "data" / "research" / "long" / "journal.db"
START4, SPLIT = 1664582400000, 1727740800000  # 2022-10-01, 2024-10-01
START15 = 1745107200000  # 2025-04-20 (the 1.5-year set)
H, DAY = 3_600_000, 86_400_000


def flips_15m(conn: sqlite3.Connection) -> dict[str, list[tuple[int, str]]]:
    out: dict[str, list[tuple[int, str]]] = {}
    for sym, side, t in conn.execute("SELECT symbol, side, trigger_time FROM setups WHERE variant_id = ? AND timeframe = '15m'"
                                     " ORDER BY trigger_time", (ct.BASELINE,)):
        out.setdefault(sym, []).append((t + 900_000, side))
    return out


def htf_dirs(conn: sqlite3.Connection, coins: list[str], hours: int) -> dict[str, list[tuple[int, str]]]:
    """Q-Trend flips on `hours`-hour candles built from the 15m candles: (known at = candle close, side)."""
    out = {}
    step = hours * H
    for coin in coins:
        bars: dict[int, list[float]] = {}
        for t, o, h, l, c, v in conn.execute("SELECT open_time, open, high, low, close, volume FROM candles WHERE symbol = ?"
                                             " AND timeframe = '15m' ORDER BY open_time", (coin,)):
            k = t // step * step
            b = bars.get(k)
            if b is None:
                bars[k] = [k, o, h, l, c, v, 1]
            else:
                b[2], b[3], b[4], b[5], b[6] = max(b[2], h), min(b[3], l), c, b[5] + v, b[6] + 1
        rows = [tuple(b[:6]) for k, b in sorted(bars.items()) if b[6] == step // 900_000]
        q = li.qtrend([r[1] for r in rows], [r[2] for r in rows], [r[3] for r in rows], [r[4] for r in rows])
        flips = []
        for r, v in list(zip(rows, q))[250:]:  # after the trend period has warmed up
            if v["buy"]:
                flips.append((r[0] + step, "long"))
            elif v["sell"]:
                flips.append((r[0] + step, "short"))
        out[coin] = flips
    return out


def direction_at(flips: list[tuple[int, str]], at: int) -> str | None:
    lo, hi, last = 0, len(flips) - 1, None
    while lo <= hi:  # binary search for the last flip known at `at`
        mid = (lo + hi) // 2
        if flips[mid][0] <= at:
            last, lo = flips[mid][1], mid + 1
        else:
            hi = mid - 1
    return last


def next_opposite(flips: list[tuple[int, str]], side: str, after: int, before: int) -> int | None:
    lo, hi = 0, len(flips)
    while lo < hi:
        mid = (lo + hi) // 2
        if flips[mid][0] <= after:
            lo = mid + 1
        else:
            hi = mid
    for known, s in flips[lo:]:
        if known >= before:
            return None
        if s != side:
            return known
    return None


def one_per_coin(trades: list[dict], same_only: bool) -> list[dict]:
    """Sequential: skip a signal while the coin has an open position (same_only: only one in the same direction)."""
    out, active = [], {}
    for t in sorted(trades, key=lambda x: (x["entry"], x["tf"] != "15m", x["id"])):
        live = [o for o in active.get(t["symbol"], []) if o["exit"] > t["entry"]]
        active[t["symbol"]] = live
        if any((o["side"] == t["side"]) if same_only else True for o in live):
            continue
        out.append(t)
        live.append(t)
    return out


def candidates(conn: sqlite3.Connection, trades: list[dict], coins: list[str]) -> dict[str, list[dict]]:
    f15 = flips_15m(conn)
    for t in trades:
        t["d15"] = direction_at(f15.get(t["symbol"], []), t["entry"])
    h1, h4 = htf_dirs(conn, coins, 1), htf_dirs(conn, coins, 4)
    for t in trades:
        t["d1h"] = direction_at(h1.get(t["symbol"], []), t["entry"])
        t["d4h"] = direction_at(h4.get(t["symbol"], []), t["entry"])
    c1 = [dict(t) for t in trades if t["tf"] == "15m" or t["d15"] is None or t["d15"] == t["side"]]
    c3 = []
    for t in c1:
        t = dict(t)
        flip = next_opposite(f15.get(t["symbol"], []), t["side"], t["entry"], t["exit"])
        if flip is not None:
            r = ct.price_r(conn, t, flip)
            if r is not None:
                t["r"], t["exit"] = r, flip
        c3.append(t)
    only15 = [dict(t) for t in trades if t["tf"] == "15m"]
    return {
        "C0 now (every signal)": [dict(t) for t in trades],
        "C1 15m decides": c1,
        "C2 C1 + one position per coin": one_per_coin(c1, False),
        "C3 C1 + exit on the 15m flip": c3,
        "C4 C3 + no duplicates (user's design)": one_per_coin(c3, True),
        "C5 15m only": only15,
        "C6 15m only + one position per coin": one_per_coin(only15, False),
        "C7 C1 + the 1h Q-Trend agrees": [t for t in c1 if t["d1h"] is None or t["d1h"] == t["side"]],
        "C8 C1 + the 4h Q-Trend agrees": [t for t in c1 if t["d4h"] is None or t["d4h"] == t["side"]],
        "C9 C1 + skip B without a squeeze release": [t for t in c1 if not (t["q"] == "B" and t["sqz"] is not True)],
    }


def maxdd_r(taken: list[dict]) -> float:
    cum = peak = dd = 0.0
    for t in sorted(taken, key=lambda x: x["exit"]):
        cum += t["r"]
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return dd


def table(title: str, conn: sqlite3.Connection, coins: list[str], start: int, years: list[tuple[int, int]],
          split: int | None) -> None:
    op = _load("one_position_test")
    trades = [t for t in ct.load(conn, 1, start, tuple(coins)) if t["closed"]]
    fmt = lambda ms: time.strftime("%Y-%m", time.gmtime(ms / 1000))
    print(f"\n== {title}: {len(trades)} trades, {time.strftime('%Y-%m-%d', time.gmtime(trades[0]['entry'] / 1000))} .."
          f" {time.strftime('%Y-%m-%d', time.gmtime(trades[-1]['entry'] / 1000))}")
    head = f"   {'candidate':42} {'trades':>6} {'R/tr':>7} " + " ".join(f"{fmt(a):>8}" for a, _ in years)
    head += f" {'total':>7} {'DD R':>6} {'2xSL':>5} | {'$150 whole':>16} {'DD':>6}"
    if split:
        head += " | in-sample $150      | out-of-sample $150"
    print(head)
    for name, taken in candidates(conn, trades, coins).items():
        line = f"   {name:42} {len(taken):6d} {sum(t['r'] for t in taken) / max(len(taken), 1):+7.3f} "
        for a, b in years:
            rs = [t["r"] for t in taken if a <= t["entry"] < b]
            line += f" {sum(rs) / len(rs) if rs else 0:+7.3f}"
        bal, dd = dt.account(taken)
        line += f" {sum(t['r'] for t in taken):+7.1f} {maxdd_r(taken):6.1f} {op.both_stopped(taken):5d} | ${bal:9,.0f} ({bal / 150 - 1:+5.0%}) {dd:5.1%}"
        if split:
            b1, d1 = dt.account([t for t in taken if t["entry"] < split])
            b2, d2 = dt.account([t for t in taken if t["entry"] >= split])
            line += f" | {b1 / 150 - 1:+6.0%} DD {d1:4.0%} | {b2 / 150 - 1:+6.0%} DD {d2:4.0%}"
        print(line, flush=True)


def main() -> None:
    years4 = [(START4 + k * 365 * DAY, START4 + (k + 1) * 365 * DAY) for k in range(4)]
    conn = sqlite3.connect(f"file:{LONG4}?mode=ro", uri=True)
    table("MAIN: XRP, SOL, ETH, 4 years (in-sample before 2024-10-01)", conn, ["XRP", "SOL", "ETH"], START4, years4, SPLIT)
    table("REPLICATION: BTC, 4 years", conn, ["BTC"], START4, years4, SPLIT)
    conn.close()
    conn = sqlite3.connect(f"file:{LONG}?mode=ro", uri=True)
    years15 = [(START15, START15 + 182 * DAY), (START15 + 182 * DAY, START15 + 365 * DAY), (START15 + 365 * DAY, START15 + 548 * DAY)]
    table("REPLICATION: 10 check coins, 1.5 years", conn,
          ["BNB", "DOGE", "LTC", "ADA", "LINK", "AVAX", "NEAR", "SUI", "ZEC", "BTC"], START15, years15, None)
    conn.close()


if __name__ == "__main__":
    main()
