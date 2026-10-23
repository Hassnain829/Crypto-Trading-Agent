r"""Daily news, measured two ways on 4 years of the planned design's trades (the user, 2026-10-21). Research only.

    .venv\Scripts\python -u research\tools\news_proxy_test.py

A. Price shocks as a proxy for unscheduled news (fixed before the run):
   - coin shock: a 15m candle at least 3x the median range of the coin's previous 96 15m candles (one day)
   - market shock: BTC moving 2% or more within one 5m candle
   trades entered within 1 hour after a shock, and a rule that waits 1 hour after a shock.
B. The Crypto Fear & Greed Index (alternative.me, daily since 2018): each trade gets the index value known at its
   entry (the newest daily value at or before it). Rules: no trades in extremes (< 20 or > 80); contrarian (longs only
   below 50, shorts only above 50); trend-following (longs only above 50, shorts only below 50).
Trades: the planned design through the demo account with the user's rules (events_test.design_trades), money at
A 3% / B 2%, 12% budget, $150.
"""
from __future__ import annotations

import bisect
import importlib.util
import json
import sqlite3
import statistics as st
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location("events_test", HERE / "events_test.py")
et = importlib.util.module_from_spec(spec)
spec.loader.exec_module(et)
FNG = ROOT / "data" / "research" / "fear_greed.json"
M5, M15, H = 300_000, 900_000, 3_600_000


def coin_shocks(conn, coin: str) -> list[int]:
    """Close times of 15m candles at least 3x the median range of the previous 96."""
    rows = conn.execute("SELECT open_time, high, low, open FROM candles WHERE symbol = ? AND timeframe = '15m' ORDER BY open_time",
                        (coin,)).fetchall()
    ranges = [(h - l) / o for _, h, l, o in rows]
    out = []
    for i in range(96, len(rows)):
        med = st.median(ranges[i - 96:i])
        if med > 0 and ranges[i] >= 3 * med:
            out.append(rows[i][0] + M15)
    return out


def btc_shocks(conn) -> list[int]:
    return [t + M5 for t, o, c in conn.execute("SELECT open_time, open, close FROM candles WHERE symbol = 'BTC' AND timeframe = '5m'")
            if o and abs(c / o - 1) >= 0.02]


def after(t: int, shocks: list[int], window: int) -> bool:
    i = bisect.bisect_right(shocks, t)
    return i > 0 and t - shocks[i - 1] <= window


def fear_greed() -> list[tuple[int, int]]:
    if not FNG.exists():
        with urllib.request.urlopen("https://api.alternative.me/fng/?limit=0&format=json", timeout=60) as r:
            FNG.write_bytes(r.read())
    data = json.loads(FNG.read_text(encoding="utf-8"))["data"]
    return sorted((int(d["timestamp"]) * 1000, int(d["value"])) for d in data)


def report(name: str, sel: list[dict], mid: int) -> str:
    if not sel:
        return f"   {name:58} none"
    rs = [t["r"] for t in sel]
    h1 = sum(t["r"] for t in sel if t["entry"] < mid)
    h2 = sum(t["r"] for t in sel if t["entry"] >= mid)
    bal, dd = et.account(sel)
    return (f"   {name:58} {len(sel):5d} trades won {sum(r > 0 for r in rs) / len(rs):4.0%} {st.mean(rs):+.3f}R |"
            f" half 1 {h1:+6.1f}R half 2 {h2:+6.1f}R | $150 -> ${bal:,.0f} ({bal / 150 - 1:+.0%}) DD {dd:.1%}")


def group(name: str, sel: list[dict]) -> str:
    if not sel:
        return f"   {name:40} none"
    rs = [t["r"] for t in sel]
    return f"   {name:40} {len(sel):5d} trades won {sum(r > 0 for r in rs) / len(rs):4.0%} {st.mean(rs):+.3f}R a trade"


def main() -> None:
    conn = sqlite3.connect(f"file:{et.DB}?mode=ro", uri=True)
    trades = et.design_trades(conn)
    mid = trades[len(trades) // 2]["entry"]
    shocks = {c: coin_shocks(conn, c) for c in ("XRP", "SOL", "ETH")}
    btc = sorted(btc_shocks(conn))
    print(f"A. PRICE SHOCKS: coin shocks {', '.join(f'{c} {len(v)}' for c, v in shocks.items())} (15m candle >= 3x the day's"
          f" median); BTC 2%+ in 5 minutes: {len(btc)}")
    near_coin = [t for t in trades if after(t["entry"], shocks[t["symbol"]], H)]
    near_btc = [t for t in trades if after(t["entry"], btc, H)]
    print(group("entered within 1 h after a coin shock", near_coin))
    print(group("entered within 1 h after a BTC 2% move", near_btc))
    print(group("entered after no shock", [t for t in trades if t not in near_coin and t not in near_btc]))
    print(report("now (no shock rule)", trades, mid))
    print(report("wait 1 h after a coin shock", [t for t in trades if t not in near_coin], mid))
    print(report("wait 1 h after a BTC 2% move", [t for t in trades if t not in near_btc], mid))
    print(report("wait 1 h after either", [t for t in trades if t not in near_coin and t not in near_btc], mid))

    fng = fear_greed()
    times = [t for t, _ in fng]
    for t in trades:
        i = bisect.bisect_right(times, t["entry"]) - 1
        t["fng"] = fng[i][1] if i >= 0 else None
    print(f"\nB. FEAR & GREED (alternative.me, {len(fng)} days since"
          f" {__import__('time').strftime('%Y-%m-%d', __import__('time').gmtime(fng[0][0] / 1000))})")
    bands = (("extreme fear (< 25)", 0, 25), ("fear (25-44)", 25, 45), ("neutral (45-55)", 45, 56),
             ("greed (56-75)", 56, 76), ("extreme greed (> 75)", 76, 101))
    for label, lo, hi in bands:
        sel = [t for t in trades if t["fng"] is not None and lo <= t["fng"] < hi]
        longs = [t for t in sel if t["side"] == "long"]
        shorts = [t for t in sel if t["side"] == "short"]
        print(group(label, sel) + f" | longs {st.mean([t['r'] for t in longs]) if longs else 0:+.3f}R ({len(longs)})"
              f" shorts {st.mean([t['r'] for t in shorts]) if shorts else 0:+.3f}R ({len(shorts)})")
    print(report("now (no Fear & Greed rule)", trades, mid))
    print(report("F1 no trades in extremes (< 20 or > 80)", [t for t in trades if t["fng"] is None or 20 <= t["fng"] <= 80], mid))
    print(report("F2 contrarian: longs below 50, shorts above 50", [t for t in trades if t["fng"] is None
          or (t["side"] == "long" and t["fng"] < 50) or (t["side"] == "short" and t["fng"] > 50)], mid))
    print(report("F3 with the crowd: longs above 50, shorts below 50", [t for t in trades if t["fng"] is None
          or (t["side"] == "long" and t["fng"] > 50) or (t["side"] == "short" and t["fng"] < 50)], mid))
    conn.close()


if __name__ == "__main__":
    main()
