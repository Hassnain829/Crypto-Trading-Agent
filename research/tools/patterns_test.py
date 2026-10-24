r"""Candlestick and chart patterns on 4 years of XRP/SOL/ETH/BTC (2026-10-23). Research only.

    .venv\Scripts\python -u research\tools\patterns_test.py > data\research\patterns.txt

Plan and rules, written before the results: research/notes/2026-10-23-patterns-plan.md.
Test 1: each pattern traded on its own (next open, stop beyond the pattern, 1.5R, 24 candles), against chance.
Test 2: the planned design's 4-year trades split by patterns of the coin (15m, 1h, 4h, 1d) and of BTC (4h, 1d).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import psutil
from numpy.lib.stride_tricks import sliding_window_view

ROOT = Path(__file__).resolve().parents[2]
LONG = ROOT / "data" / "research" / "long4" / "journal.db"
NEWS = ROOT / "data" / "replay" / "journal-news.db"
COINS = ["XRP", "SOL", "ETH", "BTC"]
START = pd.Timestamp("2022-10-01", tz="UTC")
SPLIT = pd.Timestamp("2024-10-01", tz="UTC")
COST, TARGET, HOLD, MIN_RISK = 0.0014, 1.5, 24, 0.002
TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]
RULE = {"1h": "1h", "4h": "4h", "1d": "1D"}
BASE_SAMPLE = 30_000
rng_ = np.random.default_rng(7)


def load(conn: sqlite3.Connection, coin: str, tf: str) -> pd.DataFrame:
    src = tf if tf in ("5m", "15m") else "15m"
    df = pd.read_sql_query("SELECT open_time, open, high, low, close FROM candles WHERE symbol = ? AND timeframe = ?"
                           " ORDER BY open_time", conn, params=(coin, src))
    df.index = pd.to_datetime(df.pop("open_time"), unit="ms", utc=True)
    if tf in RULE:
        df = df.resample(RULE[tf], label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return df[df.index >= START - pd.Timedelta(days=30)]


def shift(x: np.ndarray, k: int) -> np.ndarray:
    y = np.roll(x, k)
    y[:k] = False if x.dtype == bool else np.nan
    return y


def candle_patterns(o, h, l, c) -> dict[str, tuple[int, int, np.ndarray]]:
    """{name: (direction, span, mask of the candle that completes it)}"""
    body, rng = np.abs(c - o), h - l
    upper, lower = h - np.maximum(o, c), np.minimum(o, c) - l
    bull, bear = c > o, c < o
    avgb = pd.Series(body).shift(1).rolling(10).mean().to_numpy()
    avgr = pd.Series(rng).shift(1).rolling(10).mean().to_numpy()
    down = lambda n: shift(c, n) < shift(c, n + 10)  # trend before the pattern's first candle
    up = lambda n: shift(c, n) > shift(c, n + 10)
    o1, h1, l1, c1, b1, bu1, be1, ab1, ar1, up1, lo1 = (shift(x, 1) for x in (o, h, l, c, body, bull, bear, avgb, avgr, upper, lower))
    o2, c2, b2, bu2, be2, ab2, up2, lo2 = (shift(x, 2) for x in (o, c, body, bull, bear, avgb, upper, lower))
    small = (rng > 0) & (body <= 0.35 * rng)
    hammer = small & (lower >= 2 * body) & (upper <= 0.15 * rng)
    inverted = small & (upper >= 2 * body) & (lower <= 0.15 * rng)
    doji = (rng > 0) & (body <= 0.1 * rng)
    p = {
        "hammer": (1, 1, hammer & down(1)),
        "inverted hammer": (1, 1, inverted & down(1)),
        "dragonfly doji": (1, 1, doji & (upper <= 0.1 * rng) & (lower >= 0.6 * rng) & down(1)),
        "bullish marubozu": (1, 1, bull & (body >= 0.9 * rng) & (body > 1.5 * avgb)),
        "hanging man": (-1, 1, hammer & up(1)),
        "shooting star": (-1, 1, inverted & up(1)),
        "gravestone doji": (-1, 1, doji & (lower <= 0.1 * rng) & (upper >= 0.6 * rng) & up(1)),
        "bearish marubozu": (-1, 1, bear & (body >= 0.9 * rng) & (body > 1.5 * avgb)),
        "bullish engulfing": (1, 2, be1 & bull & (o <= c1) & (c >= o1) & (body > b1) & down(2)),
        "bearish engulfing": (-1, 2, bu1 & bear & (o >= c1) & (c <= o1) & (body > b1) & up(2)),
        "bullish harami": (1, 2, be1 & (b1 > ab1) & bull & (o >= c1) & (c <= o1) & (body < 0.5 * b1) & down(2)),
        "bearish harami": (-1, 2, bu1 & (b1 > ab1) & bear & (o <= c1) & (c >= o1) & (body < 0.5 * b1) & up(2)),
        "piercing line": (1, 2, be1 & (b1 > ab1) & bull & (o <= c1) & (c > (o1 + c1) / 2) & (c < o1) & down(2)),
        "dark cloud cover": (-1, 2, bu1 & (b1 > ab1) & bear & (o >= c1) & (c < (o1 + c1) / 2) & (c > o1) & up(2)),
        "tweezer bottom": (1, 2, be1 & bull & (np.abs(l - l1) <= 0.1 * ar1) & down(2)),
        "tweezer top": (-1, 2, bu1 & bear & (np.abs(h - h1) <= 0.1 * ar1) & up(2)),
        "bullish kicker": (1, 2, be1 & (b1 > ab1) & bull & (o >= o1) & (body > ab1) & down(2)),
        "bearish kicker": (-1, 2, bu1 & (b1 > ab1) & bear & (o <= o1) & (body > ab1) & up(2)),
        "morning star": (1, 3, be2 & (b2 > ab2) & (b1 < 0.3 * b2) & bull & (c > (o2 + c2) / 2) & down(3)),
        "evening star": (-1, 3, bu2 & (b2 > ab2) & (b1 < 0.3 * b2) & bear & (c < (o2 + c2) / 2) & up(3)),
        "three white soldiers": (1, 3, bu2 & bu1 & bull & (c1 > c2) & (c > c1) & (o1 >= o2) & (o1 <= c2) & (o >= o1) & (o <= c1)
                                 & (np.minimum(np.minimum(b2, b1), body) > 0.5 * ab2) & (upper <= 0.3 * body)
                                 & (up1 <= 0.3 * b1) & (up2 <= 0.3 * b2)),
        "three black crows": (-1, 3, be2 & be1 & bear & (c1 < c2) & (c < c1) & (o1 <= o2) & (o1 >= c2) & (o <= o1) & (o >= c1)
                              & (np.minimum(np.minimum(b2, b1), body) > 0.5 * ab2) & (lower <= 0.3 * body)
                              & (lo1 <= 0.3 * b1) & (lo2 <= 0.3 * b2)),
    }
    p["three inside up"] = (1, 3, shift(p["bullish harami"][2], 1) & bull & (c > o2))
    p["three inside down"] = (-1, 3, shift(p["bearish harami"][2], 1) & bear & (c < o2))
    p["three outside up"] = (1, 3, shift(p["bullish engulfing"][2], 1) & bull & (c > c1))
    p["three outside down"] = (-1, 3, shift(p["bearish engulfing"][2], 1) & bear & (c < c1))
    return {k: (d, n, np.nan_to_num(m, nan=0).astype(bool)) for k, (d, n, m) in p.items()}


def atr(h, l, c, n=14) -> np.ndarray:
    tr = np.maximum(h - l, np.maximum(np.abs(h - shift(c, 1)), np.abs(l - shift(c, 1))))
    return pd.Series(tr).rolling(n).mean().to_numpy()


def chart_patterns(o, h, l, c, k=3) -> dict[str, tuple[int, np.ndarray, np.ndarray]]:
    """{name: (direction, signal indices, stop prices)}; pivots are used only after their k confirming candles."""
    n, a = len(c), atr(h, l, c)
    ph = [i for i in range(k, n - k) if h[i] == h[i - k:i + k + 1].max()]
    pl = [i for i in range(k, n - k) if l[i] == l[i - k:i + k + 1].min()]
    out: dict[str, tuple[int, list, list]] = {name: (d, [], []) for name, d in
                                              (("double bottom", 1), ("double top", -1), ("inverse head and shoulders", 1),
                                               ("head and shoulders", -1))}

    def breakout(start, level, d):
        for t in range(start, min(start + 20, n - 1)):
            if (d > 0 and c[t] > level) or (d < 0 and c[t] < level):
                return t
        return None

    for lows, highs, d, name in ((pl, ph, 1, "double bottom"), (ph, pl, -1, "double top")):
        ext = l if d > 0 else h
        for x2 in range(1, len(lows)):
            j2 = lows[x2]
            for x1 in range(x2 - 1, -1, -1):
                j1 = lows[x1]
                if j2 - j1 > 60:
                    break
                if j2 - j1 < 5 or np.isnan(a[j2]) or abs(ext[j1] - ext[j2]) > a[j2]:
                    continue
                mid = h[j1:j2 + 1].max() if d > 0 else l[j1:j2 + 1].min()
                if d * (mid - ext[j2]) < a[j2]:
                    continue
                t = breakout(j2 + k, mid, d)
                if t is not None:
                    out[name][1].append(t)
                    out[name][2].append(min(ext[j1], ext[j2]) if d > 0 else max(ext[j1], ext[j2]))
                break
    for piv, d, name in ((ph, -1, "head and shoulders"), (pl, 1, "inverse head and shoulders")):
        ext = h if d < 0 else l
        for x in range(2, len(piv)):
            s1, hd, s2 = piv[x - 2], piv[x - 1], piv[x]
            if s2 - s1 > 80 or np.isnan(a[s2]) or abs(ext[s1] - ext[s2]) > a[s2]:
                continue
            if -d * (ext[hd] - (max(ext[s1], ext[s2]) if d < 0 else min(ext[s1], ext[s2]))) < 0.5 * a[s2]:
                continue
            if d < 0:
                neck = max(l[s1:hd + 1].min(), l[hd:s2 + 1].min())
            else:
                neck = min(h[s1:hd + 1].max(), h[hd:s2 + 1].max())
            t = breakout(s2 + k, neck, d)
            if t is not None:
                out[name][1].append(t)
                out[name][2].append(ext[s2])
    return {name: (d, np.array(idx, dtype=int), np.array(st, dtype=float)) for name, (d, idx, st) in out.items()}


def simulate(o, h, l, c, idx, d, stop) -> tuple[np.ndarray, np.ndarray]:
    """Net R of each signal and the index of its entry candle; skips stops closer than MIN_RISK."""
    keep = idx + HOLD < len(c)
    idx, stop = idx[keep], stop[keep]
    entry = o[idx + 1]
    risk = d * (entry - stop)
    ok = risk > MIN_RISK * entry
    idx, stop, entry, risk = idx[ok], stop[ok], entry[ok], risk[ok]
    if not len(idx):
        return np.array([]), idx
    wh, wl = sliding_window_view(h, HOLD)[idx + 1], sliding_window_view(l, HOLD)[idx + 1]
    target = entry + d * TARGET * risk
    stop_hit = (wl <= stop[:, None]) if d > 0 else (wh >= stop[:, None])
    tgt_hit = (wh >= target[:, None]) if d > 0 else (wl <= target[:, None])
    fs = np.where(stop_hit.any(1), stop_hit.argmax(1), HOLD)
    ft = np.where(tgt_hit.any(1), tgt_hit.argmax(1), HOLD)
    r = np.where((fs < HOLD) & (fs <= ft), -1.0, np.where(ft < HOLD, TARGET, d * (c[idx + HOLD] - entry) / risk))
    return r - COST * entry / risk, idx


def pattern_stop(l, h, idx, d, span) -> np.ndarray:
    if d > 0:
        return np.min(np.stack([l[idx - j] for j in range(span)]), axis=0)
    return np.max(np.stack([h[idx - j] for j in range(span)]), axis=0)


def test1(conn) -> dict:
    """{(tf, pattern): {coin: (r array, entry times)}, ...} plus chance baselines."""
    res, base = {}, {}
    for tf in TIMEFRAMES:
        for coin in COINS:
            df = load(conn, coin, tf)
            o, h, l, c = (df[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
            times = df.index
            valid = np.where(times >= START)[0]
            valid = valid[(valid > 15) & (valid + HOLD < len(c))]
            pats = candle_patterns(o, h, l, c)
            down = lambda n: shift(c, n) < shift(c, n + 10)
            up = lambda n: shift(c, n) > shift(c, n + 10)
            for name, (d, span, mask) in pats.items():
                idx = valid[mask[valid]]
                r, used = simulate(o, h, l, c, idx, d, pattern_stop(l, h, idx, d, span))
                res[(tf, name)] = res.get((tf, name), {}) | {coin: (r, times[used])}
                momentum = name in ("bullish marubozu", "bearish marubozu", "three white soldiers", "three black crows")
                bkey = (tf, d, span, momentum)
                if (bkey, coin) not in base:
                    ctx = valid if momentum else valid[(down(span) if d > 0 else up(span))[valid]]
                    sample = ctx if len(ctx) <= BASE_SAMPLE else np.sort(rng_.choice(ctx, BASE_SAMPLE, replace=False))
                    br, bused = simulate(o, h, l, c, sample, d, pattern_stop(l, h, sample, d, span))
                    base[(bkey, coin)] = (br, times[bused])
                res[(tf, name)][coin] = res[(tf, name)][coin] + (bkey,)
            if tf in ("4h", "1d"):
                for name, (d, idx, stop) in chart_patterns(o, h, l, c).items():
                    sel = times[idx] >= START if len(idx) else np.array([], dtype=bool)
                    r, used = simulate(o, h, l, c, idx[sel], d, stop[sel])
                    bkey = (tf, d, 10, True)
                    if (bkey, coin) not in base:
                        sample = valid if len(valid) <= BASE_SAMPLE else np.sort(rng_.choice(valid, BASE_SAMPLE, replace=False))
                        br, bused = simulate(o, h, l, c, sample, d, pattern_stop(l, h, sample, d, 10))
                        base[(bkey, coin)] = (br, times[bused])
                    res[(tf, "chart: " + name)] = res.get((tf, "chart: " + name), {}) | {coin: (r, times[used], bkey)}
    return res, base


def mean(x) -> float:
    return float(np.mean(x)) if len(x) else float("nan")


def report1(res, base) -> list[tuple]:
    working = []
    for tf in TIMEFRAMES:
        print(f"\n=== {tf} === pattern: trades, net R a trade (chance), edge 2022-24 / 2024-26, coins beating chance in both halves")
        for (t, name), by in res.items():
            if t != tf:
                continue
            all_r, all_b, e1, e2, coins_ok = [], [], [], [], 0
            for coin, (r, tm, bkey) in by.items():
                br, btm = base[(bkey, coin)]
                h1, h2 = tm < SPLIT, tm >= SPLIT
                bh1, bh2 = btm < SPLIT, btm >= SPLIT
                d1, d2 = mean(r[h1]) - mean(br[bh1]), mean(r[h2]) - mean(br[bh2])
                if h1.sum() >= 10 and h2.sum() >= 10 and d1 > 0 and d2 > 0:
                    coins_ok += 1
                all_r.append(r)
                all_b.append(br)
                e1.append((r[h1], br[bh1]))
                e2.append((r[h2], br[bh2]))
            r = np.concatenate(all_r)
            b = np.concatenate(all_b)
            ed1 = mean(np.concatenate([x for x, _ in e1])) - mean(np.concatenate([y for _, y in e1]))
            ed2 = mean(np.concatenate([x for x, _ in e2])) - mean(np.concatenate([y for _, y in e2]))
            flag = "WORKS" if coins_ok >= 3 and ed1 > 0 and ed2 > 0 else ""
            print(f"   {name:34} {len(r):6d}  {mean(r):+.3f}R ({mean(b):+.3f})  {ed1:+.3f} / {ed2:+.3f}  {coins_ok}/4 {flag}")
            if flag:
                working.append((tf, name, len(r), mean(r), mean(b)))
    return working


def test2(conn) -> None:
    """The design's trades split by patterns at the decision."""
    news = sqlite3.connect(f"file:{NEWS}?mode=ro", uri=True)
    tr = pd.read_sql_query("SELECT symbol, side, trigger_time, r_net FROM trades WHERE variant_id = 'v0-e78944'"
                           " AND taken = 1 AND status = 'closed'", news)
    news.close()
    tr["decision"] = tr["trigger_time"] + 900_000  # the 15m signal candle's close, ms
    tr["d"] = np.where(tr["side"] == "long", 1, -1)
    tr["half"] = np.where(tr["decision"] < SPLIT.value // 1_000_000, 1, 2)
    step = {"15m": pd.Timedelta(minutes=15), "1h": pd.Timedelta(hours=1), "4h": pd.Timedelta(hours=4), "1d": pd.Timedelta(days=1)}
    sources = [("coin", tf, 3 if tf == "15m" else 1) for tf in ("15m", "1h", "4h", "1d")] + [("BTC", tf, 1) for tf in ("4h", "1d")]
    print("\n\n######## TEST 2: the planned design's 4-year trades (3 coins) split by patterns at the decision ########")
    print("   source: group trades R a trade | 2022-24 | 2024-26")
    for who, tf, last in sources:
        flags = {"with": np.zeros(len(tr), bool), "against": np.zeros(len(tr), bool)}
        rev = {"with": np.zeros(len(tr), bool), "against": np.zeros(len(tr), bool)}
        for coin in (["BTC"] if who == "BTC" else ["XRP", "SOL", "ETH"]):
            df = load(conn, coin, tf)
            o, h, l, c = (df[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
            close_time = ((df.index + step[tf] - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy(dtype="int64")
            bull = np.zeros(len(c), bool)
            bear = np.zeros(len(c), bool)
            bull_rev = np.zeros(len(c), bool)
            bear_rev = np.zeros(len(c), bool)
            for name, (d, span, mask) in candle_patterns(o, h, l, c).items():
                momentum = name in ("bullish marubozu", "bearish marubozu", "three white soldiers", "three black crows")
                (bull if d > 0 else bear)[:] |= mask
                if not momentum:
                    (bull_rev if d > 0 else bear_rev)[:] |= mask
            sel = tr.index if who == "BTC" else tr.index[tr["symbol"] == coin]
            # the last `last` candles closed at the decision
            pos = np.searchsorted(close_time, tr.loc[sel, "decision"].to_numpy(dtype="int64"), side="right") - 1
            for i, p_, d in zip(sel, pos, tr.loc[sel, "d"].to_numpy()):
                window = range(max(0, p_ - last + 1), p_ + 1)
                b = any(bull[j] for j in window)
                s = any(bear[j] for j in window)
                br = any(bull_rev[j] for j in window)
                sr = any(bear_rev[j] for j in window)
                flags["with"][i] |= (b if d > 0 else s)
                flags["against"][i] |= (s if d > 0 else b)
                rev["with"][i] |= (br if d > 0 else sr)
                rev["against"][i] |= (sr if d > 0 else br)
        for label, f in (("any pattern", flags), ("reversal patterns", rev)):
            groups = {"with": f["with"] & ~f["against"], "against": f["against"] & ~f["with"], "none": ~f["with"] & ~f["against"]}
            print(f"   {who} {tf} ({label}):")
            for g, m in groups.items():
                x = tr[m]
                h1, h2 = x[x["half"] == 1]["r_net"], x[x["half"] == 2]["r_net"]
                print(f"      {g:8} {len(x):5d} trades {x['r_net'].mean():+.3f}R | {h1.mean():+.3f} ({len(h1)}) | {h2.mean():+.3f} ({len(h2)})")


def main() -> None:
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)  # the live agent comes first
    conn = sqlite3.connect(f"file:{LONG}?mode=ro", uri=True)
    print("######## TEST 1: each pattern traded on its own (next open, stop beyond the pattern, 1.5R, 24 candles, costs) ########")
    res, base = test1(conn)
    working = report1(res, base)
    print("\nPatterns that WORK (beat chance after costs in both halves on 3+ of 4 coins):")
    for tf, name, n, r, b in working:
        print(f"   {tf:4} {name:34} {n:6d} trades {r:+.3f}R vs chance {b:+.3f}R")
    if not working:
        print("   none")
    test2(conn)
    conn.close()


if __name__ == "__main__":
    main()
