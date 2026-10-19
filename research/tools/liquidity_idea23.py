"""Ideas 2 and 3 of research/notes/2026-10-19-liquidity-plan.md on past trades: open interest context and OI flushes.
OI: data/research/oi_history.db (TradingView 15m, bar time = start, value at close). Price: the journal's Binance 15m
candles. Read-only.

    .venv\\Scripts\\python -I research\\tools\\liquidity_idea23.py
"""
from __future__ import annotations

import sqlite3
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tradeagent.config import load_settings  # noqa: E402

M, H = 60_000, 3_600_000
TF = {"5m": 5 * M, "15m": 15 * M}
Q = 15 * M

settings = load_settings(ROOT)
conn = sqlite3.connect(f"file:{settings.resolve(settings.journal.path)}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
oi_db = sqlite3.connect(ROOT / "data" / "research" / "oi_history.db")
OI = {coin: {t * 1000 + Q: c for t, c in oi_db.execute("SELECT time, c FROM oi WHERE symbol = ?", (coin,))}
      for coin in ("XRP", "SOL", "ETH")}  # key: the 15m bar's close time (ms) -> OI at that close
OI_BARS = {coin: {t * 1000: (o, c) for t, o, c in oi_db.execute("SELECT time, o, c FROM oi WHERE symbol = ?", (coin,))}
           for coin in ("XRP", "SOL", "ETH")}  # key: bar open time (ms) -> (OI open, OI close)


def price_close(symbol: str, close_time: int) -> float | None:
    row = conn.execute("SELECT close FROM candles WHERE symbol = ? AND timeframe = '15m' AND open_time = ?",
                       (symbol, close_time - Q)).fetchone()
    return row[0] if row else None


def describe(name: str, rs: list[float]) -> str:
    if not rs:
        return f"{name}: none"
    return f"{name}: n={len(rs):3d} win={sum(r > 0 for r in rs) / len(rs):.0%} exp={st.mean(rs):+.3f}R"


# --counterfactual: the same flags on the baseline's skipped signals (taken = 0, the minimum-stop filter): other
# trades with simulated results, as an independent check of an effect found on the taken ones.
TAKEN = 0 if "--counterfactual" in sys.argv else 1
trades = conn.execute("""
    SELECT t.symbol, t.timeframe, t.side, t.confirm_time, t.entry_time, t.r_net
    FROM trades t JOIN variants v ON v.id = t.variant_id
    WHERE v.role = 'baseline' AND t.taken = ? AND t.status = 'closed' AND t.symbol IN ('XRP', 'SOL', 'ETH')
    ORDER BY t.entry_time""", (TAKEN,)).fetchall()
print("sample:", "skipped signals (counterfactual)" if TAKEN == 0 else "taken trades")
rows, skipped = [], 0
for t in trades:
    sign = 1 if t["side"] == "long" else -1
    decision = t["confirm_time"] + TF[t["timeframe"]]
    last_close = decision - decision % Q  # the newest 15m close at or before the decision
    oi_now, oi_4h = OI[t["symbol"]].get(last_close), OI[t["symbol"]].get(last_close - 4 * H)
    p_now, p_4h = price_close(t["symbol"], last_close), price_close(t["symbol"], last_close - 4 * H)
    if None in (oi_now, oi_4h, p_now, p_4h):
        skipped += 1
        continue
    oi_chg, p_chg = oi_now / oi_4h - 1, p_now / p_4h - 1
    flush_against = flush_with = False
    for k in range(8):  # the 8 closed 15m bars of the last 2 hours
        bar_open = last_close - (k + 1) * Q
        oi_bar = OI_BARS[t["symbol"]].get(bar_open)
        pc = conn.execute("SELECT open, close FROM candles WHERE symbol = ? AND timeframe = '15m' AND open_time = ?",
                          (t["symbol"], bar_open)).fetchone()
        if not oi_bar or not pc:
            continue
        d_oi, d_p = oi_bar[1] / oi_bar[0] - 1, pc[1] / pc[0] - 1
        if d_oi < -0.015 and abs(d_p) > 0.01:
            if sign * d_p < 0:
                flush_against = True  # positions on the trade's side were forced out (capitulation)
            else:
                flush_with = True  # the other side was forced out (squeeze): the move may be spent
    aligned = sign * p_chg > 0
    rows.append({"t": t, "2a": oi_chg > 0.01, "2b": aligned and oi_chg > 0.01,
                 "3a": flush_against, "3b": flush_with, "oi": oi_chg, "p": p_chg, "aligned": aligned})

mid = rows[len(rows) // 2]["t"]["entry_time"]
print(f"trades with OI data: {len(rows)} (skipped {skipped} without OI history), halves split at {mid}\n")
labels = {"2a": "2a OI rose > 1% in the 4 h before (new positions)",
          "2b": "2b trade goes with the price move AND OI rose (with new positions)",
          "3a": "3a OI flush against the trade in the last 2 h (capitulation)",
          "3b": "3b OI flush with the trade in the last 2 h (squeeze, move spent?)"}
for flag, label in labels.items():
    print(f"== {label}")
    diffs = []
    for name, part in (("all", rows), ("half 1", [r for r in rows if r["t"]["entry_time"] < mid]),
                       ("half 2", [r for r in rows if r["t"]["entry_time"] >= mid])):
        yes = [r["t"]["r_net"] for r in part if r[flag]]
        no = [r["t"]["r_net"] for r in part if not r[flag]]
        print(f"  {name:6} {describe('flag', yes)} | {describe('other', no)}")
        if name != "all" and yes and no:
            diffs.append((st.mean(yes) - st.mean(no), len(yes), len(no)))
    for side in ("long", "short"):
        yes = [r["t"]["r_net"] for r in rows if r[flag] and r["t"]["side"] == side]
        no = [r["t"]["r_net"] for r in rows if not r[flag] and r["t"]["side"] == side]
        print(f"  {side:6} {describe('flag', yes)} | {describe('other', no)}")
    for coin in ("XRP", "SOL", "ETH"):
        yes = [r["t"]["r_net"] for r in rows if r[flag] and r["t"]["symbol"] == coin]
        no = [r["t"]["r_net"] for r in rows if not r[flag] and r["t"]["symbol"] == coin]
        print(f"  {coin:6} {describe('flag', yes)} | {describe('other', no)}")
    same = len(diffs) == 2 and (diffs[0][0] > 0) == (diffs[1][0] > 0)
    passed = same and all(abs(d) >= 0.15 and ny >= 25 and nn >= 25 for d, ny, nn in diffs)
    print(f"  half differences (flag - other): {[round(d, 3) for d, _, _ in diffs]} -> "
          f"{'PASS' if passed else 'no pass'} (needs >= 0.15R, same sign, >= 25 trades per group per half)\n")

print("== context: the four price/OI regimes over the 4 h before (descriptive only)")
for aligned in (True, False):
    for up in (True, False):
        rs = [r["t"]["r_net"] for r in rows if r["aligned"] == aligned and (r["oi"] > 0) == up]
        print(f"  trade {'with' if aligned else 'against'} the price move, OI {'up' if up else 'down'}: {describe('', rs)}")
