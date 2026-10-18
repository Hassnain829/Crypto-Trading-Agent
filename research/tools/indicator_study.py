"""Backtest the test indicators' signals with the agent's risk rules (research, not part of the agent).

Every signal becomes a trade: entry at the next bar's open, stop at the 10-bar swing (skipped when closer than
1.5%), target 1.5R, 72 h time limit, the agent's fees. One trade at a time per coin, chart and signal type.
1h signals are settled on Binance 15m candles (stop first when both are hit inside one candle: conservative);
15m signals on the journal's 1m candles.

Run:  .venv\\Scripts\\python research\\tools\\indicator_study.py
"""

from __future__ import annotations

import bisect
import sqlite3
from collections import defaultdict
from pathlib import Path

from tradeagent.config import load_settings

ROOT = Path(__file__).resolve().parents[2]
RDB = sqlite3.connect(ROOT / "data" / "research" / "indicators_history.db")
JDB = sqlite3.connect(f"file:{ROOT / 'data' / 'journal.db'}?mode=ro", uri=True)
COSTS = load_settings().costs
COINS = ("XRP", "SOL", "ETH")
LOOKBACK, MIN_STOP_PCT, TARGET_R, MAX_HOLD = 10, 1.5, 1.5, 72 * 3_600_000
TF_MS = {"1h": 3_600_000, "15m": 900_000}

# (study, plot title) -> side. Pivot "dots" are left out: they are drawn on the pivot bar after the fact.
SIGNALS = {
    ("Smart Money Concepts [LuxAlgo]", "Internal Bullish BOS"): "long",
    ("Smart Money Concepts [LuxAlgo]", "Internal Bearish BOS"): "short",
    ("Smart Money Concepts [LuxAlgo]", "Internal Bullish CHoCH"): "long",
    ("Smart Money Concepts [LuxAlgo]", "Internal Bearish CHoCH"): "short",
    ("Smart Money Concepts [LuxAlgo]", "Bullish BOS"): "long",
    ("Smart Money Concepts [LuxAlgo]", "Bearish BOS"): "short",
    ("Smart Money Concepts [LuxAlgo]", "Bullish CHoCH"): "long",
    ("Smart Money Concepts [LuxAlgo]", "Bearish CHoCH"): "short",
    ("Smart Money Concepts [LuxAlgo]", "Bullish Internal OB Breakout"): "long",
    ("Smart Money Concepts [LuxAlgo]", "Bearish Internal OB Breakout"): "short",
    ("Liquidity Sweep | RitishFX", "Bullish Liquidity Sweep"): "long",
    ("Liquidity Sweep | RitishFX", "Bearish Liquidity Sweep"): "short",
    ("Liquidity Sweep | RitishFX", "BOS Confirmed Bullish"): "long",
    ("Liquidity Sweep | RitishFX", "BOS Confirmed Bearish"): "short",
    ("Liquidity Sweep | RitishFX", "Any Bullish Setup"): "long",
    ("Liquidity Sweep | RitishFX", "Any Bearish Setup"): "short",
    ("Dynamic Trendline Breakout [RFX]", "LONG SIGNAL"): "long",
    ("Dynamic Trendline Breakout [RFX]", "SHORT SIGNAL"): "short",
    ("Q-Trend", "Q-Trend BUY"): "long",
    ("Q-Trend", "Q-Trend SELL"): "short",
}
SHORT_NAMES = {"Smart Money Concepts [LuxAlgo]": "LuxAlgo", "Liquidity Sweep | RitishFX": "LiqSweep",
               "Dynamic Trendline Breakout [RFX]": "Trendline", "Q-Trend": "Q-Trend"}


def load_outcome_candles(coin: str, tf: str):
    if tf == "1h":
        rows = RDB.execute("SELECT time, open, high, low, close FROM candles WHERE symbol=? AND tf='15m' ORDER BY time",
                           (coin,)).fetchall()
    else:
        rows = JDB.execute("SELECT open_time, open, high, low, close FROM candles WHERE symbol=? AND timeframe='1m'"
                           " ORDER BY open_time", (coin,)).fetchall()
    return [r[0] for r in rows], rows


def settle(candles, entry_time, side, stop, target):
    times, rows = candles
    i = bisect.bisect_left(times, entry_time)
    if i >= len(rows) or rows[i][0] - entry_time > 3_600_000:
        return None
    entry = rows[i][1]
    sign = 1 if side == "long" else -1
    for j in range(i, len(rows)):
        t, o, h, l, c = rows[j]
        if t - entry_time >= MAX_HOLD:
            return t, sign * (o - entry), "timeout", entry
        if (l <= stop) if sign > 0 else (h >= stop):
            return t, sign * (stop - entry), "stop", entry
        if target is not None and ((h >= target) if sign > 0 else (l <= target)):
            return t, sign * (target - entry), "target", entry
    return None


def run(coin: str, tf: str, candles) -> dict[tuple[str, str], list[tuple[int, float]]]:
    bars = RDB.execute("SELECT time, open, high, low, close FROM bars WHERE symbol=? AND tf=? ORDER BY time",
                       (coin, tf)).fetchall()
    index = {b[0]: k for k, b in enumerate(bars)}
    flags = defaultdict(list)
    for t, study, plot in RDB.execute("SELECT time, study, plot FROM flags WHERE symbol=? AND tf=? ORDER BY time", (coin, tf)):
        title = plot.split(":", 2)[2]
        if (study, title) in SIGNALS:
            flags[(study, title)].append(t)
    out = {}
    for key, times in flags.items():
        side, trades, busy_until = SIGNALS[key], [], 0
        sign = 1 if side == "long" else -1
        for t in times:
            k = index.get(t)
            if k is None or k < LOOKBACK:
                continue
            entry_time = t + TF_MS[tf]
            if entry_time < busy_until:
                continue
            window = bars[k - LOOKBACK + 1:k + 1]
            stop = min(b[3] for b in window) if side == "long" else max(b[2] for b in window)
            probe = settle(candles, entry_time, side, stop, None) if False else None
            times_c, rows_c = candles
            i = bisect.bisect_left(times_c, entry_time)
            if i >= len(rows_c):
                continue
            entry = rows_c[i][1]
            risk = sign * (entry - stop)
            if risk <= 0 or risk / entry * 100 < MIN_STOP_PCT:
                continue
            res = settle(candles, entry_time, side, stop, entry + sign * TARGET_R * risk)
            if res is None:
                continue
            exit_time, pnl, kind, entry = res
            fee = COSTS.maker_fee * entry + (COSTS.maker_fee if kind == "target" else COSTS.taker_fee + COSTS.slippage) * entry
            trades.append((entry_time, (pnl - fee) / risk))
            busy_until = exit_time
        out[key] = trades
    return out


def summary(r: list[float]) -> str:
    if not r:
        return f"{'0':>4}"
    w = sum(1 for x in r if x > 0)
    return f"{len(r):4} {w / len(r):4.0%} {sum(r) / len(r):+.3f}"


def main() -> None:
    for tf in ("1h", "15m"):
        results = defaultdict(list)
        for coin in COINS:
            candles = load_outcome_candles(coin, tf)
            for key, trades in run(coin, tf, candles).items():
                results[key] += trades
        all_times = sorted(t for trades in results.values() for t, _ in trades)
        if not all_times:
            continue
        lo, hi = all_times[0], all_times[-1] + 1
        n_parts = 4 if tf == "1h" else 2
        edges = [lo + (hi - lo) * i // n_parts for i in range(n_parts + 1)]
        print(f"\n===== {tf} signals on XRP+SOL+ETH, {n_parts} equal time periods "
              f"(columns: trades, win rate, R per trade)")
        print(f"{'signal':<44}{'ALL':>18}" + "".join(f"{'P' + str(i + 1):>18}" for i in range(n_parts)) + "  positive periods")
        rows = []
        for key, trades in results.items():
            r = [x for _, x in sorted(trades)]
            parts = [[x for t, x in trades if edges[i] <= t < edges[i + 1]] for i in range(n_parts)]
            positive = sum(1 for p in parts if p and sum(p) > 0)
            rows.append((sum(r) / len(r) if r else -9, key, r, parts, positive))
        for _, key, r, parts, positive in sorted(rows, key=lambda x: -x[0]):
            name = f"{SHORT_NAMES[key[0]]}: {key[1]}"
            print(f"{name:<44}{summary(r):>18}" + "".join(f"{summary(p):>18}" for p in parts) + f"  {positive}/{n_parts}")


if __name__ == "__main__":
    main()
