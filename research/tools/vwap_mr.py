"""Test A of research/notes/2026-10-20-mr-and-drawdown-plan.md: VWAP #2 band mean reversion on the stored
TradingView snapshots (live journal: XRP, SOL, ETH; coin screen: eight coins), simulated with the project's
simulator on Binance 1m candles. Read-only.

    .venv\\Scripts\\python -I research\\tools\\vwap_mr.py
"""
from __future__ import annotations

import json
import random
import sqlite3
import statistics as st
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tradeagent.config import load_settings  # noqa: E402
from tradeagent.sim.simulator import Costs, close_now, open_trade, results, step  # noqa: E402

M = 60_000
TF = {"5m": 5 * M, "15m": 15 * M}
MIN_STOP = 0.005
MIN_REWARD_R = 0.5
TIME_STOP = 8 * 3_600_000
settings = load_settings(ROOT)
COSTS = Costs(settings.costs.maker_fee, settings.costs.taker_fee, settings.costs.slippage)


def open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def bars(conn: sqlite3.Connection, symbol: str, tf: str) -> list[tuple]:
    out = {}
    for r in conn.execute("SELECT bar_time, open, high, low, close, values_json FROM snapshots WHERE symbol = ? AND timeframe = ?"
                          " AND problems_json IS NULL ORDER BY bar_time, signal_version", (symbol, tf)):
        v = (json.loads(r["values_json"]).get("vwap") or {})
        if r["close"] is not None and v.get("vwap") is not None and v.get("upper2") is not None and v.get("lower2") is not None:
            out[r["bar_time"]] = (r["bar_time"], r["open"], r["high"], r["low"], r["close"], v["vwap"], v["upper2"], v["lower2"])
    return sorted(out.values())


def simulate(conn: sqlite3.Connection, symbol: str, tf: str) -> list[dict]:
    rows, trades, busy_until = bars(conn, symbol, tf), [], 0
    step_ms = TF[tf]
    for a, b in zip(rows, rows[1:]):
        if b[0] - a[0] != step_ms:
            continue
        if a[4] < a[7] and b[4] > b[7] and b[4] > b[1]:
            side, sign = "long", 1
        elif a[4] > a[6] and b[4] < b[6] and b[4] < b[1]:
            side, sign = "short", -1
        else:
            continue
        decision = b[0] + step_ms
        if decision < busy_until:
            continue
        entry = conn.execute("SELECT open, high, low FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time = ?",
                             (symbol, decision)).fetchone()
        if entry is None:
            continue
        price = entry["open"]
        if not (entry["low"] < price if sign > 0 else entry["high"] > price):
            continue  # the limit order at the open did not fill
        stop = min(a[3], b[3]) if sign > 0 else max(a[2], b[2])
        risk = sign * (price - stop)
        if risk <= 0 or risk / price < MIN_STOP:
            continue
        reward_r = sign * (b[5] - price) / risk
        if reward_r < MIN_REWARD_R:
            continue
        state = open_trade(side=side, mode="fixed", entry_time=decision, entry_ref=price, stop=stop, take_profit_r=reward_r,
                           partial_r=1.0, partial_fraction=0.5, trail_lookback=3, costs=COSTS, limit_entry=True)
        for c in conn.execute("SELECT open_time, open, high, low, close FROM candles WHERE symbol = ? AND timeframe = '1m'"
                              " AND open_time >= ? AND open_time <= ? ORDER BY open_time",
                              (symbol, decision, decision + TIME_STOP)):
            if c["open_time"] >= decision + TIME_STOP:
                close_now(state, c["open_time"], c["open"], COSTS, "time stop")
                break
            step(state, tuple(c), COSTS)
            if state.closed:
                break
        if not state.closed:
            continue
        busy_until = state.last_time + M
        trades.append({"symbol": symbol, "tf": tf, "side": side, "entry": decision, "exit": state.last_time,
                       "r": results(state, COSTS)["r_net"], "reason": state.exit_reason, "reward_r": reward_r})
    return trades


def summary(name: str, ts: list[dict]) -> str:
    if not ts:
        return f"  {name:28} no trades"
    rs = [t["r"] for t in ts]
    wins, losses = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    pf = f"{wins / losses:.2f}" if losses else "-"
    return (f"  {name:28} n={len(rs):4d} win={sum(r > 0 for r in rs) / len(rs):.0%} exp={st.mean(rs):+.3f}R PF={pf}"
            f" avg target {st.mean(t['reward_r'] for t in ts):.2f}R")


live = open_db(settings.resolve(settings.journal.path))
screen = open_db(ROOT / "data" / "research" / "coin_screen.db")
all_trades = []
started = time.monotonic()
for conn, coins in ((live, ["XRP", "SOL", "ETH"]), (screen, ["ZEC", "NEAR", "1000PEPE", "ENA", "INJ", "TIA", "ARB", "TAO"])):
    for coin in coins:
        for tf in TF:
            all_trades += simulate(conn, coin, tf)
print(f"simulated in {time.monotonic() - started:.0f} s\n")
all_trades.sort(key=lambda t: t["entry"])
current = [t for t in all_trades if t["symbol"] in ("XRP", "SOL", "ETH")]
others = [t for t in all_trades if t["symbol"] not in ("XRP", "SOL", "ETH")]
print(summary("ALL coins", all_trades))
print(summary("XRP + SOL + ETH", current))
print(summary("the eight screen coins", others))
for tf in TF:
    print(summary(f"current coins {tf}", [t for t in current if t["tf"] == tf]))
for coin in ("XRP", "SOL", "ETH", "ZEC", "NEAR", "1000PEPE", "ENA", "INJ", "TIA", "ARB", "TAO"):
    print(summary(coin, [t for t in all_trades if t["symbol"] == coin]))
reasons = defaultdict(int)
for t in all_trades:
    reasons[t["reason"]] += 1
print("  exits:", dict(reasons))
mid = all_trades[len(all_trades) // 2]["entry"]
h1 = [t["r"] for t in all_trades if t["entry"] < mid]
h2 = [t["r"] for t in all_trades if t["entry"] >= mid]
ch = current[len(current) // 2]["entry"] if current else 0
c1 = [t["r"] for t in current if t["entry"] < ch]
c2 = [t["r"] for t in current if t["entry"] >= ch]
print(f"\n  halves, all coins: {st.mean(h1):+.3f} / {st.mean(h2):+.3f} | current coins: {st.mean(c1):+.3f} / {st.mean(c2):+.3f}")

# Daily R correlation with the trend engine (baseline taken trades) on the current coins
day = lambda ms: ms // 86_400_000  # noqa: E731
trend = defaultdict(float)
for r in live.execute("""SELECT t.exit_time, t.r_net FROM trades t JOIN variants v ON v.id = t.variant_id WHERE v.role = 'baseline'
        AND t.taken = 1 AND t.status = 'closed' AND t.symbol IN ('XRP', 'SOL', 'ETH')"""):
    trend[day(r[0])] += r[1]
mr = defaultdict(float)
for t in current:
    mr[day(t["exit"])] += t["r"]
days = sorted(d for d in set(trend) | set(mr) if min(mr or {0: 0}) <= d <= max(mr or {0: 0}))
corr = st.correlation([trend.get(d, 0.0) for d in days], [mr.get(d, 0.0) for d in days]) if len(days) > 10 else None
print(f"  correlation of daily R with the trend engine (current coins, {len(days)} days): {corr:+.2f}" if corr is not None else "")

all_rs = [t["r"] for t in all_trades]
cur_rs = [t["r"] for t in current]
wins, losses = sum(r for r in all_rs if r > 0), -sum(r for r in all_rs if r < 0)
checks = {"exp >= +0.15R": st.mean(all_rs) >= 0.15, "PF >= 1.3": losses > 0 and wins / losses >= 1.3,
          "win >= 60%": sum(r > 0 for r in all_rs) / len(all_rs) >= 0.60,
          "both halves > 0": st.mean(h1) > 0 and st.mean(h2) > 0, "current coins > 0": bool(cur_rs) and st.mean(cur_rs) > 0,
          "corr <= 0.3": corr is not None and corr <= 0.3}
print("\n  verdict:", "PASS" if all(checks.values()) else "no", "-", ", ".join(f"{k} {'ok' if v else 'FAIL'}" for k, v in checks.items()))
