r"""Indicators and candle patterns together (2026-10-23). Research only.

    .venv\Scripts\python -u research\tools\confluence_check.py > data\research\confluence.txt

1. BTC's last daily candles: which patterns they form and what the agent's indicators (Python copies) say.
2. The three-line strike traded in the direction of its strike candle (the user's example), 15m/1h/4h/1d, 4 coins.
3. How the agent's own 15m signals line up with 15m candle patterns: which patterns its signal candles are, and their R.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pt = _load("patterns_test", "patterns_test.py")
pm = _load("patterns_more", "patterns_more.py")
li = _load("long_indicators", "long_indicators.py")
pa = pm.pa


def btc(rule: str) -> pd.DataFrame:
    """BTC candles at `rule` (1D, 4h): research journal 15m before the cut, live 5m after."""
    q = ("SELECT open_time, open, high, low, close, volume FROM candles WHERE symbol = 'BTC' AND timeframe = ?"
         " AND open_time {} ? ORDER BY open_time")
    with sqlite3.connect(f"file:{pa.LONG}?mode=ro", uri=True) as a, sqlite3.connect(f"file:{pa.LIVE}?mode=ro", uri=True) as b:
        old = pd.read_sql_query(q.format("<"), a, params=("15m", pa.CUT_MS))
        new = pd.read_sql_query(q.format(">="), b, params=("5m", pa.CUT_MS))
    df = pd.concat([old, new])
    df.index = pd.to_datetime(df.pop("open_time"), unit="ms", utc=True)
    df = df[~df.index.duplicated()].sort_index()
    return df.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()


def last_flip(index, qt) -> tuple[str | None, object]:
    side, when = None, None
    for i, x in enumerate(qt):
        if x["buy"]:
            side, when = "buy (long)", index[i]
        if x["sell"]:
            side, when = "sell (short)", index[i]
    return side, when


def part1() -> None:
    print("######## 1. BTC: the last daily candles, their patterns, and the agent's indicators (Python copies) ########")
    df = btc("1D")
    o, h, l, c, v = (df[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close", "volume"))
    pats = {**pt.candle_patterns(o, h, l, c), **pm.extra_patterns(o, h, l, c)}
    qt = li.qtrend(list(o), list(h), list(l), list(c))
    kv = li.klinger(list(h), list(l), list(c), list(v))
    for i in range(len(df) - 7, len(df)):
        names = [f"{n} ({'bull' if d > 0 else 'bear'})" for n, (d, s, m) in pats.items() if m[i]]
        color = "green" if c[i] > o[i] else "red"
        print(f"   {df.index[i]:%m-%d} O {o[i]:>8,.0f} H {h[i]:>8,.0f} L {l[i]:>8,.0f} C {c[i]:>8,.0f} {color:5}"
              f" | Klinger {'above' if kv[i]['hist'] > 0 else 'below'} its signal"
              f" | patterns: {', '.join(names) or 'none'}")
    print("   (the last row is today's daily candle, still open)")
    side, when = last_flip(df.index, qt)
    print(f"   Q-Trend daily: last flip {side} on {when:%Y-%m-%d}; trend line {qt[-1]['trend_line']:,.0f}, price {c[-1]:,.0f}")
    d4 = btc("4h")
    o4, h4, l4, c4, v4 = (d4[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close", "volume"))
    q4 = li.qtrend(list(o4), list(h4), list(l4), list(c4))
    k4 = li.klinger(list(h4), list(l4), list(c4), list(v4))
    side4, when4 = last_flip(d4.index, q4)
    print(f"   Q-Trend 4h: last flip {side4} on {when4:%Y-%m-%d %H:%M} UTC; Klinger 4h {'above' if k4[-1]['hist'] > 0 else 'below'}"
          f" its signal")


def part2(conn) -> None:
    print("\n######## 2. THREE-LINE STRIKE traded in the direction of its strike candle (4 coins, 4 years) ########")
    print("   3 green + 1 big red -> short; 3 red + 1 big green -> long. Stop beyond the 4 candles, 1.5R, 24 candles, costs.")
    rng = np.random.default_rng(3)
    for tf in ("15m", "1h", "4h", "1d"):
        out = {"short": [], "long": [], "chance short": [], "chance long": []}
        for coin in pt.COINS:
            df = pt.load(conn, coin, tf)
            o, h, l, c = (df[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
            times = df.index
            valid = np.where(times >= pt.START)[0]
            valid = valid[(valid > 20) & (valid + pt.HOLD < len(c))]
            p = pm.extra_patterns(o, h, l, c)
            for label, name, d in (("short", "bullish three-line strike", -1), ("long", "bearish three-line strike", 1)):
                idx = valid[p[name][2][valid]]
                r, used = pt.simulate(o, h, l, c, idx, d, pt.pattern_stop(l, h, idx, d, 4))
                out[label].append((r, times[used] < pt.SPLIT))
                sample = np.sort(rng.choice(valid, min(len(valid), 20000), replace=False))
                br, bused = pt.simulate(o, h, l, c, sample, d, pt.pattern_stop(l, h, sample, d, 4))
                out["chance " + label].append((br, times[bused] < pt.SPLIT))
        print(f"   {tf}:")
        for label, parts in out.items():
            r = np.concatenate([x for x, _ in parts])
            h1 = np.concatenate([np.asarray(y) for _, y in parts])
            f = lambda x: f"{x.mean():+.3f}" if len(x) else "  -  "
            won = (r > 0).mean() if len(r) else 0
            print(f"      {label:13} {len(r):5d} trades, won {won:.0%}, {f(r)}R | {f(r[h1])} / {f(r[~h1])}")


def part3() -> None:
    print("\n######## 3. THE AGENT'S OWN 15m SIGNALS (the design, 4 years) and the candle pattern of their signal candle ########")
    tr = pa.load_trades(pa.REPLAY / "journal-news.db", "v0-e78944")
    rows = []
    for coin in tr["symbol"].unique():
        df = pa.candles15(coin)
        o, h, l, c = (df[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
        pats = {**pt.candle_patterns(o, h, l, c), **pm.extra_patterns(o, h, l, c)}
        close_ms = ((df.index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy(dtype="int64") + 900_000
        sel = np.where(tr["symbol"].to_numpy() == coin)[0]
        pos = np.searchsorted(close_ms, tr["decision"].to_numpy()[sel], side="right") - 1  # the signal (confirmation) candle
        for j, p_ in zip(sel, pos):
            d = tr["d"].iat[j]
            found = [(n, dd) for n, (dd, s, m) in pats.items() if m[p_]]
            rows.append((d, tr["r_net"].iat[j], tr["decision"].iat[j], found))
    n = len(rows)
    with_ = [x for x in rows if any(dd == x[0] for _, dd in x[3])]
    against = [x for x in rows if x[3] and not any(dd == x[0] for _, dd in x[3])]
    none = [x for x in rows if not x[3]]
    f = lambda xs: f"{len(xs):5d} ({len(xs) / n:.0%}) {np.mean([x[1] for x in xs]):+.3f}R" if xs else "0"
    print(f"   the signal candle is a pattern in the trade's direction: {f(with_)}")
    print(f"   it is only a pattern against the trade:                  {f(against)}")
    print(f"   no pattern on the signal candle:                         {f(none)}")
    by: dict[tuple[str, str], list] = {}
    for d, r, t, found in rows:
        for name, dd in found:
            by.setdefault((name, "same way" if dd == d else "opposite"), []).append((r, t))
    print("   the most common patterns on the agent's signal candles (30+ trades): trades, R | 2022-24 / 2024-26")
    for (name, way), xs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        if len(xs) < 30:
            continue
        r = np.array([x[0] for x in xs])
        t = np.array([x[1] for x in xs])
        h1 = t < pa.SPLIT_MS
        g = lambda m: f"{r[m].mean():+.3f}" if m.any() else "  -  "
        print(f"      {name:30} {way:8} {len(xs):5d}  {r.mean():+.3f}R | {g(h1)} / {g(~h1)}")


def main() -> None:
    part1()
    conn = sqlite3.connect(f"file:{pt.LONG}?mode=ro", uri=True)
    part2(conn)
    conn.close()
    part3()


if __name__ == "__main__":
    main()
