"""Do the test indicators improve the agent's own trades? (research, read-only)

For every closed baseline trade since the 15m indicator history starts, look at the 15m chart's flags in the
last N bars before the confirmation: was there a same-direction signal of each indicator? Compare the trades
with and without that confirmation.
"""

from __future__ import annotations

import bisect
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RDB = sqlite3.connect(ROOT / "data" / "research" / "indicators_history.db")
JDB = sqlite3.connect(f"file:{ROOT / 'data' / 'journal.db'}?mode=ro", uri=True)
JDB.row_factory = sqlite3.Row
M15 = 900_000
GROUPS = {
    "LuxAlgo internal BOS/CHoCH": ("Smart Money Concepts [LuxAlgo]", {
        "long": ("Internal Bullish BOS", "Internal Bullish CHoCH"),
        "short": ("Internal Bearish BOS", "Internal Bearish CHoCH")}),
    "LuxAlgo swing BOS/CHoCH": ("Smart Money Concepts [LuxAlgo]", {
        "long": ("Bullish BOS", "Bullish CHoCH"), "short": ("Bearish BOS", "Bearish CHoCH")}),
    "LiqSweep any setup": ("Liquidity Sweep | RitishFX", {
        "long": ("Any Bullish Setup",), "short": ("Any Bearish Setup",)}),
    "LiqSweep sweep only": ("Liquidity Sweep | RitishFX", {
        "long": ("Bullish Liquidity Sweep",), "short": ("Bearish Liquidity Sweep",)}),
    "Trendline breakout": ("Dynamic Trendline Breakout [RFX]", {"long": ("LONG SIGNAL",), "short": ("SHORT SIGNAL",)}),
}


def stats(r):
    if not r:
        return "   0"
    w = sum(1 for x in r if x > 0)
    return f"{len(r):3} tr {w / len(r):4.0%} {sum(r) / len(r):+.3f}R"


def main() -> None:
    start = RDB.execute("SELECT min(time) FROM bars WHERE tf='15m'").fetchone()[0] + 20 * M15
    base = JDB.execute("SELECT id FROM variants WHERE role='baseline'").fetchone()[0]
    fwd = JDB.execute("SELECT started_at FROM account_state WHERE account='paper'").fetchone()[0]
    trades = JDB.execute("SELECT * FROM trades WHERE book='exploration' AND variant_id=? AND taken=1 AND status='closed'"
                         " AND entry_time>=? AND symbol IN ('XRP','SOL','ETH') ORDER BY entry_time", (base, start)).fetchall()
    flags = defaultdict(list)  # (coin, study, title) -> sorted bar times
    for coin, t, study, plot in RDB.execute("SELECT symbol, time, study, plot FROM flags WHERE tf='15m' ORDER BY time"):
        flags[(coin, study, plot.split(":", 2)[2])].append(t)
    mid = trades[len(trades) // 2]["entry_time"]
    print(f"Agent's baseline trades since the 15m indicator history: {stats([t['r_net'] for t in trades])}")
    print(f"  1st half {stats([t['r_net'] for t in trades if t['entry_time'] < mid])}   "
          f"2nd half {stats([t['r_net'] for t in trades if t['entry_time'] >= mid])}")
    for lookback in (4, 8, 16):
        print(f"\nsame-direction signal on the 15m chart within the last {lookback} bars ({lookback * 15} min) before the confirmation")
        for name, (study, titles) in GROUPS.items():
            yes, no = [], []
            for t in trades:
                close = t["confirm_time"] + (300_000 if t["timeframe"] == "5m" else M15)  # the confirming candle's close
                lo = close - lookback * M15
                hit = False
                for title in titles[t["side"]]:
                    times = flags.get((t["symbol"], study, title), [])
                    i = bisect.bisect_left(times, lo)
                    if i < len(times) and times[i] + M15 <= close:  # that 15m bar had closed by then
                        hit = True
                        break
                (yes if hit else no).append(t)
            y1 = [t["r_net"] for t in yes if t["entry_time"] < mid]
            y2 = [t["r_net"] for t in yes if t["entry_time"] >= mid]
            print(f"  {name:<28} with: {stats([t['r_net'] for t in yes])}  (halves {stats(y1)} | {stats(y2)})"
                  f"   without: {stats([t['r_net'] for t in no])}")


if __name__ == "__main__":
    main()
