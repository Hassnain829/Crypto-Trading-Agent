r"""The remaining candlestick and chart patterns (2026-10-23, second pass). Research only.

    .venv\Scripts\python -u research\tools\patterns_more.py > data\research\patterns_more.txt

Plan, written before the results: research/notes/2026-10-23-patterns2-plan.md (part 3). The same trade rule and chance
baselines as patterns_test.py, plus the patterns as context for the planned design's trades.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import psutil

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("patterns_test", HERE / "patterns_test.py")
pt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pt)
_spec2 = importlib.util.spec_from_file_location("patterns_account", HERE / "patterns_account.py")
pa = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(pa)

S = pt.shift
NO_TREND = {"bullish three-line strike", "bearish three-line strike", "rising three methods", "falling three methods"}
WITH_TREND = {"bullish separating lines": "up", "bearish separating lines": "down", "on-neck": "down", "in-neck": "down",
              "thrusting": "down"}  # continuation patterns: the trend they continue


def extra_patterns(o, h, l, c) -> dict[str, tuple[int, int, np.ndarray]]:
    body, rng = np.abs(c - o), h - l
    upper, lower = h - np.maximum(o, c), np.minimum(o, c) - l
    bull, bear = c > o, c < o
    avgb = pd.Series(body).shift(1).rolling(10).mean().to_numpy()
    avgr = pd.Series(rng).shift(1).rolling(10).mean().to_numpy()
    down = lambda n: S(c, n) < S(c, n + 10)
    up = lambda n: S(c, n) > S(c, n + 10)
    o1, h1, l1, c1, b1, bu1, be1, ab1, ar1, u1 = (S(x, 1) for x in (o, h, l, c, body, bull, bear, avgb, avgr, upper))
    o2, h2, l2, c2, b2, bu2, be2, ab2, ar2, u2 = (S(x, 2) for x in (o, h, l, c, body, bull, bear, avgb, avgr, upper))
    o3, h3, l3, c3, bu3, be3 = (S(x, 3) for x in (o, h, l, c, bull, bear))
    o4, h4, l4, c4, b4, bu4, be4, ab4 = (S(x, 4) for x in (o, h, l, c, body, bull, bear, avgb))
    doji = (rng > 0) & (body <= 0.1 * rng)
    d1, d2 = S(doji, 1), S(doji, 2)
    tol = 0.05 * ar1
    spin = (rng > 0) & (body <= 0.3 * rng) & (body > 0.1 * rng) & (upper >= body) & (lower >= body)
    legs = doji & (upper >= 0.3 * rng) & (lower >= 0.3 * rng)
    wave = (rng > 0) & (body <= 0.15 * rng) & (upper >= 3 * body) & (lower >= 3 * body) & (rng > 1.5 * avgr)
    inside3 = (np.fmax(np.fmax(h3, h2), h1) < h4) & (np.fmin(np.fmin(l3, l2), l1) > l4)
    p = {
        "bullish belt hold": (1, 1, bull & (o - l <= 0.05 * rng) & (body >= 0.6 * rng) & (body > avgb) & down(1)),
        "bearish belt hold": (-1, 1, bear & (h - o <= 0.05 * rng) & (body >= 0.6 * rng) & (body > avgb) & up(1)),
        "bullish spinning top": (1, 1, spin & down(1)),
        "bearish spinning top": (-1, 1, spin & up(1)),
        "long-legged doji after a fall": (1, 1, legs & down(1)),
        "long-legged doji after a rise": (-1, 1, legs & up(1)),
        "high wave after a fall": (1, 1, wave & down(1)),
        "high wave after a rise": (-1, 1, wave & up(1)),
        "bullish harami cross": (1, 2, be1 & (b1 > ab1) & doji & (np.maximum(o, c) <= o1) & (np.minimum(o, c) >= c1) & down(2)),
        "bearish harami cross": (-1, 2, bu1 & (b1 > ab1) & doji & (np.maximum(o, c) <= c1) & (np.minimum(o, c) >= o1) & up(2)),
        "bullish separating lines": (1, 2, be1 & bull & (np.abs(o - o1) <= tol) & (body > ab1) & up(2)),
        "bearish separating lines": (-1, 2, bu1 & bear & (np.abs(o - o1) <= tol) & (body > ab1) & down(2)),
        "bullish counterattack": (1, 2, be1 & (b1 > ab1) & bull & (body > ab1) & (np.abs(c - c1) <= tol) & down(2)),
        "bearish counterattack": (-1, 2, bu1 & (b1 > ab1) & bear & (body > ab1) & (np.abs(c - c1) <= tol) & up(2)),
        "on-neck": (-1, 2, be1 & (b1 > ab1) & bull & (o < l1) & (np.abs(c - l1) <= 0.1 * ar1) & down(2)),
        "in-neck": (-1, 2, be1 & (b1 > ab1) & bull & (o < l1) & (c >= c1) & (c <= c1 + 0.1 * b1) & down(2)),
        "thrusting": (-1, 2, be1 & (b1 > ab1) & bull & (o < l1) & (c > c1 + 0.1 * b1) & (c < (o1 + c1) / 2) & down(2)),
        "matching low": (1, 2, be1 & (b1 > ab1) & bear & (np.abs(c - c1) <= tol) & down(2)),
        "matching high": (-1, 2, bu1 & (b1 > ab1) & bull & (np.abs(c - c1) <= tol) & up(2)),
        "homing pigeon": (1, 2, be1 & (b1 > ab1) & bear & (o <= o1) & (c >= c1) & (body < 0.5 * b1) & down(2)),
        "descending hawk": (-1, 2, bu1 & (b1 > ab1) & bull & (o >= o1) & (c <= c1) & (body < 0.5 * b1) & up(2)),
        "morning doji star": (1, 3, be2 & (b2 > ab2) & d1 & bull & (c > (o2 + c2) / 2) & down(3)),
        "evening doji star": (-1, 3, bu2 & (b2 > ab2) & d1 & bear & (c < (o2 + c2) / 2) & up(3)),
        "bullish abandoned baby": (1, 3, be2 & (b2 > ab2) & d1 & (h1 < l2) & (l > h1) & bull & down(3)),
        "bearish abandoned baby": (-1, 3, bu2 & (b2 > ab2) & d1 & (l1 > h2) & (h < l1) & bear & up(3)),
        "bullish tri-star": (1, 3, d2 & d1 & doji & (l1 < np.minimum(l2, l)) & down(3)),
        "bearish tri-star": (-1, 3, d2 & d1 & doji & (h1 > np.maximum(h2, h)) & up(3)),
        "advance block": (-1, 3, bu2 & bu1 & bull & (c1 > c2) & (c > c1) & (b1 < b2) & (body < b1) & (u1 > u2) & (upper > u1) & up(3)),
        "deliberation": (-1, 3, bu2 & bu1 & bull & (b2 > ab2) & (b1 > ab2) & (body < 0.5 * b1) & (c > c1) & up(3)),
        "upside gap two crows": (-1, 3, bu2 & (b2 > ab2) & be1 & (c1 > c2) & bear & (o >= o1) & (c < c1) & (c > c2) & up(3)),
        "unique three river": (1, 3, be2 & (b2 > ab2) & be1 & (l1 < l2) & (c1 > c2) & (o1 < o2) & bull & (body < 0.5 * b1)
                               & (c < c1) & down(3)),
        "stick sandwich": (1, 3, be2 & bu1 & bear & (np.abs(c - c2) <= 0.05 * ar2) & (c1 > o2) & down(3)),
        "identical three crows": (-1, 3, be2 & be1 & bear & (np.abs(o1 - c2) <= tol) & (np.abs(o - c1) <= tol) & (c1 < c2) & (c < c1)
                                  & (np.minimum(np.minimum(b2, b1), body) > 0.5 * ab2) & up(3)),
        "bullish three-line strike": (1, 4, bu3 & bu2 & bu1 & (c2 > c3) & (c1 > c2) & bear & (o >= c1) & (c <= o3)),
        "bearish three-line strike": (-1, 4, be3 & be2 & be1 & (c2 < c3) & (c1 < c2) & bull & (o <= c1) & (c >= o3)),
        "rising three methods": (1, 5, bu4 & (b4 > ab4) & inside3 & bull & (c > c4) & (body > ab4)),
        "falling three methods": (-1, 5, be4 & (b4 > ab4) & inside3 & bear & (c < c4) & (body > ab4)),
        "ladder bottom": (1, 5, be4 & be3 & be2 & (c3 < c4) & (c2 < c3) & be1 & (u1 > b1) & bull & (o > o1) & down(5)),
    }
    return {k: (d, n, np.nan_to_num(m, nan=0).astype(bool)) for k, (d, n, m) in p.items()}


def pivots(h, l, k=3):
    n = len(h)
    hi = [i for i in range(k, n - k) if h[i] == h[i - k:i + k + 1].max()]
    lo = [i for i in range(k, n - k) if l[i] == l[i - k:i + k + 1].min()]
    return hi, lo


def chart_more(o, h, l, c, k=3) -> dict[str, tuple[int, np.ndarray, np.ndarray]]:
    """{name: (direction, signal indices, stops)} for triple tops/bottoms, rectangles, triangles, wedges and flags."""
    n, a = len(c), pt.atr(h, l, c)
    hi, lo = pivots(h, l, k)
    out: dict[str, tuple[int, list, list]] = {}

    def add(name, d, t, stop):
        out.setdefault(name, (d, [], []))
        out[name][1].append(t)
        out[name][2].append(stop)

    for piv, d, name, ext in ((hi, -1, "triple top", h), (lo, 1, "triple bottom", l)):
        for x in range(2, len(piv)):
            p1, p2, p3 = piv[x - 2], piv[x - 1], piv[x]
            if p3 - p1 > 100 or np.isnan(a[p3]):
                continue
            vals = ext[[p1, p2, p3]]
            if vals.max() - vals.min() > a[p3]:
                continue
            neck = l[p1:p3 + 1].min() if d < 0 else h[p1:p3 + 1].max()
            for t in range(p3 + k, min(p3 + k + 20, n - 1)):
                if (d < 0 and c[t] < neck) or (d > 0 and c[t] > neck):
                    add(name, d, t, vals.max() if d < 0 else vals.min())
                    break

    hi_arr, lo_arr = np.array(hi), np.array(lo)
    for t in range(60, n - 1):
        if np.isnan(a[t]) or a[t] <= 0:
            continue
        ch = hi_arr[(hi_arr + k <= t - 1) & (hi_arr >= t - 60)][-3:]
        cl = lo_arr[(lo_arr + k <= t - 1) & (lo_arr >= t - 60)][-3:]
        if len(ch) < 2 or len(cl) < 2:
            continue
        su, iu = np.polyfit(ch, h[ch], 1)
        sl, il = np.polyfit(cl, l[cl], 1)
        nu, nl = su / a[t], sl / a[t]
        flat_u, flat_l = abs(nu) < 0.03, abs(nl) < 0.03
        if flat_u and flat_l:
            shape = "rectangle"
        elif flat_u and nl > 0.03:
            shape = "ascending triangle"
        elif nu < -0.03 and flat_l:
            shape = "descending triangle"
        elif nu < -0.03 and nl > 0.03:
            shape = "symmetrical triangle"
        elif nu > 0.03 and nl > 0.03 and nl > nu:
            shape = "rising wedge"
        elif nu < -0.03 and nl < -0.03 and nu < nl:
            shape = "falling wedge"
        else:
            continue
        up_now, up_prev = iu + su * t, iu + su * (t - 1)
        lo_now, lo_prev = il + sl * t, il + sl * (t - 1)
        if up_now <= lo_now:
            continue
        if c[t] > up_now and c[t - 1] <= up_prev:
            add(f"{shape}, break up", 1, t, l[cl[-1]])
        elif c[t] < lo_now and c[t - 1] >= lo_prev:
            add(f"{shape}, break down", -1, t, h[ch[-1]])

    t0 = 10
    p = t0
    while p < n - 25:
        if np.isnan(a[p]):
            p += 1
            continue
        moved = None
        for m in range(2, 9):
            if c[p] - c[p - m] >= 3 * a[p]:
                moved = 1
                break
            if c[p - m] - c[p] >= 3 * a[p]:
                moved = -1
                break
        if moved is None:
            p += 1
            continue
        pole_hi, pole_lo = h[p - m:p + 1].max(), l[p - m:p + 1].min()
        height = pole_hi - pole_lo
        found = None
        for t in range(p + 5, min(p + 21, n - 1)):
            cons_h, cons_l = h[p + 1:t].max(), l[p + 1:t].min()
            if moved > 0 and cons_l < pole_hi - 0.5 * height:
                break
            if moved < 0 and cons_h > pole_lo + 0.5 * height:
                break
            if moved > 0 and c[t] > max(cons_h, pole_hi):
                found = ("bull flag", 1, t, cons_l)
                break
            if moved < 0 and c[t] < min(cons_l, pole_lo):
                found = ("bear flag", -1, t, cons_h)
                break
        if found:
            add(found[0], found[1], found[2], found[3])
            p = found[2] + 1
        else:
            p += 1
    return {name: (d, np.array(idx, dtype=int), np.array(st, dtype=float)) for name, (d, idx, st) in out.items()}


def standalone(conn) -> None:
    print("######## 3a. THE REMAINING PATTERNS ON THEIR OWN (next open, stop beyond the pattern, 1.5R, 24 candles, costs) ########")
    rng = np.random.default_rng(7)
    for tf in pt.TIMEFRAMES:
        rows: dict[str, list] = {}
        for coin in pt.COINS:
            df = pt.load(conn, coin, tf)
            o, h, l, c = (df[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
            times = df.index
            valid = np.where(times >= pt.START)[0]
            valid = valid[(valid > 20) & (valid + pt.HOLD < len(c))]
            down = lambda n: S(c, n) < S(c, n + 10)
            up = lambda n: S(c, n) > S(c, n + 10)
            base_cache = {}
            items = [(name, d, span, mask, None) for name, (d, span, mask) in extra_patterns(o, h, l, c).items()]
            if tf in ("1h", "4h", "1d"):
                items += [("chart: " + name, d, 10, None, (idx, stop)) for name, (d, idx, stop) in chart_more(o, h, l, c).items()]
            for name, d, span, mask, chart in items:
                if chart is None:
                    idx = valid[mask[valid]]
                    stop = pt.pattern_stop(l, h, idx, d, span)
                    ctx_kind = "none" if name in NO_TREND else WITH_TREND.get(name, "down" if d > 0 else "up")
                else:
                    idx, stop = chart
                    keep = np.isin(idx, valid)
                    idx, stop = idx[keep], stop[keep]
                    ctx_kind = "none"
                r, used = pt.simulate(o, h, l, c, idx, d, stop)
                key = (d, span, ctx_kind)
                if key not in base_cache:
                    ctx = valid if ctx_kind == "none" else valid[(down(span) if ctx_kind == "down" else up(span))[valid]]
                    sample = ctx if len(ctx) <= pt.BASE_SAMPLE else np.sort(rng.choice(ctx, pt.BASE_SAMPLE, replace=False))
                    br, bused = pt.simulate(o, h, l, c, sample, d, pt.pattern_stop(l, h, sample, d, span))
                    base_cache[key] = (br, times[bused])
                rows.setdefault(name, []).append((coin, r, times[used]) + base_cache[key])
        print(f"\n=== {tf} === pattern: trades, net R a trade (chance), edge 2022-24 / 2024-26, coins beating chance in both halves")
        for name, per in rows.items():
            r_all = np.concatenate([x[1] for x in per])
            b_all = np.concatenate([x[3] for x in per])
            if len(r_all) == 0:
                print(f"   {name:40}      0  (never formed)")
                continue
            e = []
            coins_ok = 0
            for half in (lambda t: t < pt.SPLIT, lambda t: t >= pt.SPLIT):
                rr = np.concatenate([x[1][half(x[2])] for x in per])
                bb = np.concatenate([x[3][half(x[4])] for x in per])
                e.append(pt.mean(rr) - pt.mean(bb))
            for coin, r, t, br, bt in per:
                h1, h2 = t < pt.SPLIT, t >= pt.SPLIT
                if h1.sum() >= 10 and h2.sum() >= 10 and pt.mean(r[h1]) > pt.mean(br[bt < pt.SPLIT]) \
                        and pt.mean(r[h2]) > pt.mean(br[bt >= pt.SPLIT]):
                    coins_ok += 1
            flag = "WORKS" if coins_ok >= 3 and e[0] > 0 and e[1] > 0 else ""
            print(f"   {name:40} {len(r_all):6d}  {pt.mean(r_all):+.3f}R ({pt.mean(b_all):+.3f})  {e[0]:+.3f} / {e[1]:+.3f}  {coins_ok}/4 {flag}")


def context() -> None:
    print("\n\n######## 3b. AS CONTEXT FOR THE DESIGN'S 4-YEAR TRADES ########")
    tr = pa.load_trades(pa.REPLAY / "journal-news.db", "v0-e78944")
    r, t = tr["r_net"].to_numpy(), tr["decision"].to_numpy()
    print("   group: trades R | 2022-24 | 2024-26")
    # the remaining candlestick patterns on the coin's last 1h / 1d candle
    for tf in ("1h", "1d"):
        w = np.zeros(len(tr), bool)
        a = np.zeros(len(tr), bool)
        for coin in tr["symbol"].unique():
            df = pa.candles15(coin)
            if tf in pa.RULE:
                df = df.resample(pa.RULE[tf], label="left", closed="left").agg(
                    {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
            o, h, l, c = (df[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
            bull = np.zeros(len(c), bool)
            bear = np.zeros(len(c), bool)
            for name, (d, span, m) in extra_patterns(o, h, l, c).items():
                (bull if d > 0 else bear)[:] |= m
            close_ms = ((df.index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy(dtype="int64") + pa.STEP[tf]
            sel = np.where(tr["symbol"].to_numpy() == coin)[0]
            pos = np.searchsorted(close_ms, t[sel], side="right") - 1
            d = tr["d"].to_numpy()[sel]
            b, s = bull[pos], bear[pos]
            w[sel] = np.where(d > 0, b, s)
            a[sel] = np.where(d > 0, s, b)
        print(f"   remaining candlestick patterns, coin {tf} last candle:")
        for g, m in (("with", w & ~a), ("against", a & ~w), ("none", ~w & ~a)):
            print(f"      {g:8} {pa.split_line(r, t, m, pa.SPLIT_MS)}")
    # chart-pattern breakouts in the trade's direction in the last 8 candles of the coin's 1h / 4h
    for tf in ("1h", "4h"):
        w = np.zeros(len(tr), bool)
        a = np.zeros(len(tr), bool)
        for coin in tr["symbol"].unique():
            df = pa.candles15(coin).resample(pa.RULE[tf], label="left", closed="left").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
            o, h, l, c = (df[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
            bull = np.zeros(len(c), bool)
            bear = np.zeros(len(c), bool)
            for name, (d, idx, _stop) in list(chart_more(o, h, l, c).items()) + list(pt.chart_patterns(o, h, l, c).items()):
                (bull if d > 0 else bear)[idx] = True
            close_ms = ((df.index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy(dtype="int64") + pa.STEP[tf]
            sel = np.where(tr["symbol"].to_numpy() == coin)[0]
            pos = np.searchsorted(close_ms, t[sel], side="right") - 1
            d = tr["d"].to_numpy()[sel]
            b = np.zeros(len(sel), bool)
            s = np.zeros(len(sel), bool)
            for j in range(8):
                p_ = pos - j
                ok = p_ >= 0
                b[ok] |= bull[p_[ok]]
                s[ok] |= bear[p_[ok]]
            w[sel] = np.where(d > 0, b, s)
            a[sel] = np.where(d > 0, s, b)
        print(f"   chart-pattern breakout in the last 8 candles of the coin's {tf}:")
        for g, m in (("with", w & ~a), ("against", a & ~w), ("none", ~w & ~a)):
            print(f"      {g:8} {pa.split_line(r, t, m, pa.SPLIT_MS)}")


def main() -> None:
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)  # the live agent comes first
    conn = sqlite3.connect(f"file:{pt.LONG}?mode=ro", uri=True)
    standalone(conn)
    conn.close()
    context()


if __name__ == "__main__":
    main()
