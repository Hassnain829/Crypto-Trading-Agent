"""Chart-pattern breakouts from candles: double/triple tops and bottoms, head and shoulders (and inverse), rectangles,
ascending/descending/symmetrical triangles, rising/falling wedges, bull and bear flags.

Ported unchanged from the research (research/tools/patterns_test.py chart_patterns and patterns_more.py chart_more,
2026-10-23; research/notes/2026-10-24-patterns-per-coin-plan.md). A 4h breakout in a trade's direction makes a tier-A
reason: on XRP/SOL/ETH those trades made +0.20R to +0.27R against +0.04R in two replays (but not on other coins).

Pivots are used only after their K confirming candles, so a breakout at index t uses nothing after t.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

K = 3  # a pivot high/low is the extreme of the K candles on each side


def _shift(x: np.ndarray, k: int) -> np.ndarray:
    y = np.roll(x.astype(float), k)
    y[:k] = np.nan
    return y


def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14) -> np.ndarray:
    prev = _shift(c, 1)
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
    return pd.Series(tr).rolling(n).mean().to_numpy()


def _pivots(h: np.ndarray, l: np.ndarray, k: int = K) -> tuple[list[int], list[int]]:
    n = len(h)
    highs = [i for i in range(k, n - k) if h[i] == h[i - k:i + k + 1].max()]
    lows = [i for i in range(k, n - k) if l[i] == l[i - k:i + k + 1].min()]
    return highs, lows


def breakouts(o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray,
              include_last: bool = False) -> dict[str, tuple[int, list[int]]]:
    """{pattern name: (direction +1/-1, indices of the candles whose close breaks out)}.

    The research version never checks the last candle for a breakout (it always had more history after it). Live, the
    last closed candle is the newest one, so include_last=True checks it too; earlier candles give the same result."""
    n, a = len(c), atr(h, l, c)
    end = n if include_last else n - 1  # candles up to end - 1 may break out
    hi, lo = _pivots(h, l)
    out: dict[str, tuple[int, list[int]]] = {}

    def add(name: str, d: int, t: int) -> None:
        out.setdefault(name, (d, []))[1].append(t)

    def first_break(start: int, level: float, d: int) -> int | None:
        for t in range(start, min(start + 20, end)):
            if (d > 0 and c[t] > level) or (d < 0 and c[t] < level):
                return t
        return None

    # double bottom / double top: two pivots within 1 ATR, 5-60 candles apart, then a close beyond the pivot between them
    for pivots, d, name in ((lo, 1, "double bottom"), (hi, -1, "double top")):
        ext = l if d > 0 else h
        for x2 in range(1, len(pivots)):
            j2 = pivots[x2]
            for x1 in range(x2 - 1, -1, -1):
                j1 = pivots[x1]
                if j2 - j1 > 60:
                    break
                if j2 - j1 < 5 or np.isnan(a[j2]) or abs(ext[j1] - ext[j2]) > a[j2]:
                    continue
                mid = h[j1:j2 + 1].max() if d > 0 else l[j1:j2 + 1].min()
                if d * (mid - ext[j2]) < a[j2]:
                    continue
                t = first_break(j2 + K, mid, d)
                if t is not None:
                    add(name, d, t)
                break
    # head and shoulders (bearish) / inverse (bullish): a head 0.5 ATR beyond two shoulders within 1 ATR of each other
    for pivots, d, name in ((hi, -1, "head and shoulders"), (lo, 1, "inverse head and shoulders")):
        ext = h if d < 0 else l
        for x in range(2, len(pivots)):
            s1, hd, s2 = pivots[x - 2], pivots[x - 1], pivots[x]
            if s2 - s1 > 80 or np.isnan(a[s2]) or abs(ext[s1] - ext[s2]) > a[s2]:
                continue
            if -d * (ext[hd] - (max(ext[s1], ext[s2]) if d < 0 else min(ext[s1], ext[s2]))) < 0.5 * a[s2]:
                continue
            neck = max(l[s1:hd + 1].min(), l[hd:s2 + 1].min()) if d < 0 else min(h[s1:hd + 1].max(), h[hd:s2 + 1].max())
            t = first_break(s2 + K, neck, d)
            if t is not None:
                add(name, d, t)
    # triple top / bottom: three pivots within 1 ATR in at most 100 candles, then a close through the neckline
    for pivots, d, name, ext in ((hi, -1, "triple top", h), (lo, 1, "triple bottom", l)):
        for x in range(2, len(pivots)):
            p1, p2, p3 = pivots[x - 2], pivots[x - 1], pivots[x]
            if p3 - p1 > 100 or np.isnan(a[p3]):
                continue
            vals = ext[[p1, p2, p3]]
            if vals.max() - vals.min() > a[p3]:
                continue
            neck = l[p1:p3 + 1].min() if d < 0 else h[p1:p3 + 1].max()
            t = first_break(p3 + K, neck, d)
            if t is not None:
                add(name, d, t)
    # rectangles, triangles and wedges: lines through the last 2-3 confirmed pivot highs and lows of the last 60 candles
    hi_arr, lo_arr = np.array(hi), np.array(lo)
    for t in range(60, end):
        if np.isnan(a[t]) or a[t] <= 0:
            continue
        ch = hi_arr[(hi_arr + K <= t - 1) & (hi_arr >= t - 60)][-3:]
        cl = lo_arr[(lo_arr + K <= t - 1) & (lo_arr >= t - 60)][-3:]
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
            add(f"{shape}, break up", 1, t)
        elif c[t] < lo_now and c[t - 1] >= lo_prev:
            add(f"{shape}, break down", -1, t)
    # flags: a pole of 3 ATR in at most 8 candles, then 4-20 candles that keep half of it, then a close beyond them
    p = 10
    while p < (end - 1 if include_last else n - 25):
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
        for t in range(p + 5, min(p + 21, end)):
            cons_h, cons_l = h[p + 1:t].max(), l[p + 1:t].min()
            if moved > 0 and cons_l < pole_hi - 0.5 * height:
                break
            if moved < 0 and cons_h > pole_lo + 0.5 * height:
                break
            if moved > 0 and c[t] > max(cons_h, pole_hi):
                found = ("bull flag", 1, t)
                break
            if moved < 0 and c[t] < min(cons_l, pole_lo):
                found = ("bear flag", -1, t)
                break
        if found:
            add(*found)
            p = found[2] + 1
        else:
            p += 1
    return out


def breakout_masks(o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray,
                   include_last: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """(bullish, bearish): True on the candles whose close is a chart-pattern breakout that way."""
    bull, bear = np.zeros(len(c), bool), np.zeros(len(c), bool)
    for d, idx in breakouts(o, h, l, c, include_last).values():
        (bull if d > 0 else bear)[idx] = True
    return bull, bear
