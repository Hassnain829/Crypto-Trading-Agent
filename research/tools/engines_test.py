r"""The two candidate trade sources, tested again (the user, 2026-10-29: "isko bhi test krke dekh hi lo"). Research only.

1. Engine 2: a 4h chart-pattern breakout sets the direction; entry at the next 15m open after the first 15m candle that
   closes against it (within 8 h), the agent's 10-candle swing stop (at least 1.5%), target 1.5R. The research version
   (engine2_check.py) judged trades on 15m candles with a flat cost; here every trade is re-run with the agent's own
   rules on 1m candles: a limit entry at that open that fills only if the first minute trades through it, stop first
   when both are touched in a minute, no target in the fill minute, maker/taker fees, the 72 h hold.
2. Daily trend (outside_test.py T1-L): long after a daily close above the prior 20-day high, out after a close below the
   prior 10-day low, 2x ATR(20) hard stop = 1R. The daily candles are refreshed from Binance first.

Each alone and together with v4 in the account (user's rules: max 5 open, 2 a coin, opposite skipped, first position a
coin always, 12% open-risk budget, A 3% / B 2%; the simple account of engine2_check.py, checked against the agent's).
- 4 years (2022-10 to 2026-10-18): v4 = the design's trades minus those against a 2%+ BTC 12 h move, tier A = OI/Trendline
  or a 4h chart breakout or BTC's 12 h move the trade's way (factor_compare.py).
- Since 2026-08-01: v4 = the replay of the agent's engine on its own TradingView data (stop_dip_replay.py).
The daily trend holds for weeks, so it runs as its own part of the account (it never blocks a 15m trade): either half
of the money each, or on the whole balance next to the 15m trades.

    .venv\Scripts\python -u research\tools\engines_test.py [--no-fetch]
"""
from __future__ import annotations

import calendar
import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
DAY, H4 = 86_400_000, 14_400_000
HOLD = 72 * 3_600_000
START4 = 1664582400000  # 2022-10-01
SPLIT = 1727740800000  # 2024-10-01
END4 = 1792368000000  # 2026-10-19: the end of the 4-year design replay
AUG = calendar.timegm((2026, 8, 1, 0, 0, 0)) * 1000
CUT = 1792454400000  # 2026-10-20: the research journal's 1m candles before, the live journal's from here
TRADED = ["XRP", "SOL", "ETH"]
COLS = ["symbol", "side", "entry_time", "exit_time", "r", "quality"]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ws = _load("wide_stop_4y")
e2 = _load("engine2_check")
pa = e2.pa
ot = _load("outside_test")


def minutes(long4: sqlite3.Connection, live: sqlite3.Connection, coin: str, a: int, b: int) -> np.ndarray:
    q = ("SELECT open_time, open, high, low FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time >= ?"
         " AND open_time <= ? ORDER BY open_time")
    rows = []
    if a < CUT:
        rows += long4.execute(q, (coin, a, min(b, CUT - 1))).fetchall()
    if b >= CUT:
        rows += live.execute(q, (coin, max(a, CUT), b)).fetchall()
    return np.array(rows, dtype=float)


def exit_time(side: int, stop: float, target: float, t: np.ndarray, h: np.ndarray, l: np.ndarray, entry: int) -> int:
    inside = t < entry + HOLD
    hit_stop = ((l <= stop) if side > 0 else (h >= stop)) & inside
    hit_target = ((h >= target) if side > 0 else (l <= target)) & inside
    hit_target[:1] = False
    first = [int(np.argmax(x)) for x in (hit_stop, hit_target) if x.any()]
    return int(t[min(first)]) + 60_000 if first else entry + HOLD


def engine2_setups(df15: pd.DataFrame, coin: str, start_ms: int, window: int = 2) -> list[tuple]:
    """engine2_check.engine2's entries, without its 15m outcome: (coin, direction, entry time, entry, stop, target)."""
    at_list, dirs = e2.chart_events(df15)
    o, h, l, c = (df15[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
    t_open = e2.ms(df15.index)
    out = []
    for at, d in zip(at_list, dirs):
        if at < start_ms:
            continue
        i, end = np.searchsorted(t_open, at), np.searchsorted(t_open, at + window * H4)
        while i < end and i + 1 < len(c):
            against = c[i] < o[i] if d > 0 else c[i] > o[i]
            if against and i >= e2.SWING:
                entry = o[i + 1]
                stop = l[i - e2.SWING + 1:i + 1].min() if d > 0 else h[i - e2.SWING + 1:i + 1].max()
                risk = d * (entry - stop)
                if risk > e2.MIN_STOP * entry:
                    out.append((coin, int(d), int(t_open[i + 1]), float(entry), float(stop), float(entry + d * e2.TARGET * risk)))
                    break
            i += 1
    return out


def engine2_trades(start_ms: int) -> tuple[pd.DataFrame, dict]:
    long4 = sqlite3.connect(f"file:{(ROOT / 'data/research/long4/journal.db').as_posix()}?mode=ro", uri=True)
    live = sqlite3.connect(f"file:{(ROOT / 'data/journal.db').as_posix()}?mode=ro", uri=True)
    rows, counts = [], {"setups": 0, "missed": 0, "open": 0}
    for coin in TRADED:
        for coin_, d, t0, entry, stop, target in engine2_setups(pa.candles15(coin), coin, start_ms):
            counts["setups"] += 1
            m = minutes(long4, live, coin, t0, t0 + HOLD)
            if len(m) == 0 or int(m[0, 0]) != t0:
                counts["open"] += 1  # no data yet
                continue
            t, o, h, l = m[:, 0].astype(np.int64), m[:, 1], m[:, 2], m[:, 3]
            if not (l[0] < entry if d > 0 else h[0] > entry):
                counts["missed"] += 1  # the limit order at the open was not traded through in its first minute
                continue
            r, reason = ws.run(d, entry, stop, target, t, o, h, l, t0)
            if reason == "timeout" and t[-1] < t0 + HOLD - 60_000:
                counts["open"] += 1  # still open at the end of the data
                continue
            rows.append((coin, "long" if d > 0 else "short", t0, exit_time(d, stop, target, t, h, l, t0), r, "B"))
    return pd.DataFrame(rows, columns=COLS).sort_values("entry_time").reset_index(drop=True), counts


def daily_trades(coins: list[str]) -> tuple[pd.DataFrame, list[str]]:
    conn = sqlite3.connect(ot.DB)
    out, now = [], []
    for coin in coins:
        rows = ot.bars(conn, coin, "1d")
        fund = conn.execute("SELECT time, rate FROM funding WHERE symbol = ? ORDER BY time", (coin,)).fetchall()
        trades = ot.trend_trades(coin, rows, fund, "don", ("long",), DAY)
        out += [(t["symbol"], t["side"], t["entry"], t["exit"], t["r"], "B") for t in trades]
        pos = open_position(rows)
        closed = rows[:-1] if rows[-1][0] + DAY > time.time() * 1000 else rows  # the last row may be today's candle
        hi20, lo10 = max(r[2] for r in closed[-20:]), min(r[3] for r in closed[-10:])
        day = time.strftime("%m-%d", time.gmtime(closed[-1][0] / 1000))
        state = (f"LONG since {time.strftime('%m-%d', time.gmtime(pos['entry'] / 1000))} at {pos['px']:.6g}, stop {pos['stop']:.6g}"
                 if pos else "no trade")
        now.append(f"{coin}: {state}; close {day} {closed[-1][4]:.6g}, 20-day high {hi20:.6g} (a close above starts a long),"
                   f" 10-day low {lo10:.6g} (a close below ends it)")
    return pd.DataFrame(out, columns=COLS).sort_values("entry_time").reset_index(drop=True), now


def open_position(rows: list[tuple]) -> dict | None:
    """The long trend_trades holds after the last closed day (same rules), or None."""
    a = ot.atr(rows)
    pos = None
    for i in range(101, len(rows) - 1):
        t, _o, _h, l, c = rows[i]
        if pos is not None and l <= pos["stop"] and t >= pos["entry"]:
            pos = None
            continue
        if pos is not None and c < min(r[3] for r in rows[i - 10:i]):
            pos = None
        if pos is None and a[i] and c > max(r[2] for r in rows[i - 20:i]):
            px = rows[i + 1][1] * (1 + ot.SLIP)
            pos = {"entry": rows[i + 1][0], "px": px, "stop": px - 2 * a[i]}
    return pos


def v4_four_years() -> pd.DataFrame:
    fc = _load("factor_compare")
    tr = fc.trades(ROOT / "data" / "replay" / "journal-news.db", "v0-e78944")
    tr = tr[~tr["against"].to_numpy()]
    tr = tr.assign(quality=np.where(tr["a"] | tr["c"] | tr["d_btc"], "A", "B"))
    return tr[COLS].sort_values("entry_time").reset_index(drop=True)


def v4_since_aug() -> pd.DataFrame:
    db = sqlite3.connect(f"file:{(ROOT / 'data/replay/journal-stopdip-2026-08-01.db').as_posix()}?mode=ro", uri=True)
    rows = [(s, side, et, xt, r, json.loads(cj).get("quality") or "B") for s, side, et, xt, r, cj in db.execute(
        "SELECT symbol, side, entry_time, exit_time, r_net, context_json FROM trades WHERE variant_id = 'v0-d1d9b2'"
        " AND taken = 1 AND status = 'closed'")]
    return pd.DataFrame(rows, columns=COLS).sort_values("entry_time").reset_index(drop=True)


def portfolio(sleeves: list[tuple[pd.DataFrame, bool, float]], start: float = 150.0) -> tuple[int, float, float, list]:
    """One balance, several parts. Each part: (trades, user_rules, budget). A part with the user's rules has max 5 open,
    2 a coin (same direction), opposite skipped, the first position of a coin always allowed; the daily part holds one
    position a coin. A 3% / B 2% of the balance, made smaller to fit the part's open-risk budget (skipped under 25%).
    With one 15m part this is engine2_check.account. Returns (trades, end, max DD, [(time, balance)])."""
    events = sorted(((row.entry_time, k, row) for k, (df, _, _) in enumerate(sleeves) for row in df.itertuples(index=False)),
                    key=lambda e: (e[0], e[1]))
    bal = peak = start
    dd, n, open_, curve = 0.0, 0, [], []

    def settle(until: float) -> None:
        nonlocal bal, peak, dd, open_
        for pos in sorted(p for p in open_ if p[0] <= until):
            bal += pos[4] * pos[5]
            peak = max(peak, bal)
            dd = max(dd, 1 - bal / peak)
            curve.append((pos[0], bal))
        open_ = [p for p in open_ if p[0] > until]

    for at, k, row in events:
        settle(at)
        _, user_rules, budget = sleeves[k]
        mine = [p for p in open_ if p[1] == k]
        on_coin = [p for p in mine if p[2] == row.symbol]
        if any(p[3] != row.side for p in on_coin) or len(on_coin) >= (2 if user_rules else 1):
            continue
        if user_rules and len(mine) >= 5 and on_coin:
            continue
        want = bal * (0.03 if row.quality == "A" else 0.02)
        risk = min(want, budget * bal - sum(p[4] for p in mine))
        if risk < 0.25 * want:
            continue
        open_.append((row.exit_time, k, row.symbol, row.side, risk, row.r))
        n += 1
    settle(float("inf"))
    return n, bal, dd, curve


def split_money(parts: list[tuple[pd.DataFrame, bool, float]], start: float = 150.0) -> tuple[float, float]:
    """Each part on its own share of the money; the sum's end balance and max drawdown."""
    share = start / len(parts)
    curves = [portfolio([p], share)[3] for p in parts]
    times = sorted({t for c in curves for t, _ in c})
    idx, bals, peak, dd, total = [0] * len(curves), [share] * len(curves), start, 0.0, start
    for t in times:
        for j, c in enumerate(curves):
            while idx[j] < len(c) and c[idx[j]][0] <= t:
                bals[j] = c[idx[j]][1]
                idx[j] += 1
        total = sum(bals)
        peak = max(peak, total)
        dd = max(dd, 1 - total / peak)
    return total, dd


def stats(df: pd.DataFrame, a: int, b: int) -> str:
    x = df[(df["entry_time"] >= a) & (df["entry_time"] < b)]
    if x.empty:
        return "no trades"
    days = (min(b, time.time() * 1000) - a) / DAY
    r = x["r"].to_numpy()
    return (f"{len(x)} trades ({len(x) / days:.2f} a day), won {(r > 0).mean():.0%}, {r.mean():+.3f}R a trade,"
            f" total {r.sum():+.1f}R")


def main() -> None:
    import psutil

    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    t0 = time.monotonic()
    if "--no-fetch" not in sys.argv:
        ot.data()  # Binance 1d/4h candles and funding, refreshed to today
    v4_4y, v4_aug = v4_four_years(), v4_since_aug()
    e2_all, counts = engine2_trades(START4)
    daily3, now3 = daily_trades(TRADED)
    daily4, now4 = daily_trades(TRADED + ["BTC"])
    print(f"data and trades: {time.monotonic() - t0:.0f} s; engine 2 setups {counts['setups']}, limit not filled"
          f" {counts['missed']}, still open/no data {counts['open']}")
    windows = [("4 years 2022-10 to 2026-10-18", START4, END4), ("2022-10 to 2024-10", START4, SPLIT),
               ("2024-10 to 2026-10-18", SPLIT, END4), ("since 2026-08-01 (to 10-29)", AUG, int(time.time() * 1000))]
    print("\n== each source on its own (R a trade after costs) ==")
    for name, a, b in windows:
        v4 = v4_aug if a == AUG else v4_4y
        print(f"{name}:")
        print(f"   v4                       {stats(v4, a, b)}")
        print(f"   engine 2 (1m, agent)     {stats(e2_all, a, b)}")
        print(f"   daily trend XRP/SOL/ETH  {stats(daily3, a, b)}")
        print(f"   daily trend + BTC        {stats(daily4, a, b)}")
    print("\n== the account, $150 (user's rules; the daily part one position a coin, 2% a trade) ==")
    check = e2.account(v4_4y)
    mine = portfolio([(v4_4y, True, 0.12)])
    print(f"check: engine2_check.account on v4 4 years ${check[1]:,.0f} DD {check[2]:.1%}; this simulator ${mine[1]:,.0f}"
          f" DD {mine[2]:.1%}")
    for name, a, b in windows:
        cut = lambda df: df[(df["entry_time"] >= a) & (df["entry_time"] < b)]
        v4 = cut(v4_aug if a == AUG else v4_4y)
        e2w, d3, d4 = cut(e2_all), cut(daily3), cut(daily4)
        print(f"{name}:")
        rows = [("v4 alone (as now)", portfolio([(v4, True, 0.12)])),
                ("engine 2 alone", portfolio([(e2w, True, 0.12)])),
                ("daily trend alone (XRP/SOL/ETH)", portfolio([(d3, False, 0.12)])),
                ("v4 + engine 2, one account", portfolio([(pd.concat([v4, e2w]), True, 0.12)])),
                ("v4 + daily on the whole balance", portfolio([(v4, True, 0.12), (d3, False, 0.06)])),
                ("v4 + engine 2 + daily, whole balance", portfolio([(pd.concat([v4, e2w]), True, 0.12), (d3, False, 0.06)]))]
        for label, (n, bal, dd, _c) in rows:
            print(f"   {label:40} {n:5d} trades  ${bal:10,.2f} ({bal / 150 - 1:+7.0%})  max DD {dd:5.1%}")
        for label, parts in (("v4 | daily, half the money each", [(v4, True, 0.12), (d3, False, 0.12)]),
                             ("v4 + engine 2 | daily, half each", [(pd.concat([v4, e2w]), True, 0.12), (d3, False, 0.12)])):
            bal, dd = split_money(parts)
            print(f"   {label:40}        ${bal:10,.2f} ({bal / 150 - 1:+7.0%})  max DD {dd:5.1%}")
    print("\n== the daily trend today ==")
    for line in now4:
        print("   " + line)
    print(f"\n{time.monotonic() - t0:.0f} s")


if __name__ == "__main__":
    main()
