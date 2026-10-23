"""Python copies of three open-source TradingView indicators, for the 1.5-year research test only (approved by the
user on 2026-10-20; the agent itself reads every indicator from TradingView and never imports this file).

Ported line by line from the Pine code in research/pine/ with the AGENT charts' inputs:
- Q-Trend (tarasenko_, v15): source EMA 10 of the close, trend period 200, ATR 32, multiplier 1, Type A
- Klinger Volume Oscillator (everget, v2): 38 / 60, EMA signal 13
- Squeeze Momentum Indicator [LazyBear]: BB 20 (the script uses the KC factor 1.5 for the bands), KC 20 x 1.5, true range

    .venv\\Scripts\\python -u research\\tools\\long_indicators.py validate   # against TradingView's own history
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import deque
from pathlib import Path

NA = float("nan")
SQZ_STATE = {"on": 5, "off": 6, "none": 4}  # colorer codes of the cross plot (checked in validate)


def na(x: float) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def ema(xs: list[float], length: int) -> list[float]:
    """Pine ta.ema: alpha 2/(n+1), seeded with the first value."""
    a, out, s = 2 / (length + 1), [], NA
    for x in xs:
        if na(x):
            out.append(s)
            continue
        s = x if na(s) else a * x + (1 - a) * s
        out.append(s)
    return out


def rma(xs: list[float], length: int) -> list[float]:
    """Pine ta.rma: alpha 1/n, seeded with the SMA of the first n values."""
    out, s, buf = [], NA, []
    for x in xs:
        if na(s):
            if not na(x):
                buf.append(x)
            if len(buf) == length:
                s = sum(buf) / length
            out.append(s)
        else:
            s = (x + (length - 1) * s) / length
            out.append(s)
    return out


def sma(xs: list[float], length: int) -> list[float]:
    out, q, total = [], deque(), 0.0
    for x in xs:
        if na(x):
            out.append(NA)
            continue
        q.append(x)
        total += x
        if len(q) > length:
            total -= q.popleft()
        out.append(total / length if len(q) == length else NA)
    return out


def rolling(xs: list[float], length: int, fn) -> list[float]:
    out, q = [], deque()
    for x in xs:
        q.append(x)
        if len(q) > length:
            q.popleft()
        out.append(fn(q) if len(q) == length else NA)
    return out


def true_range(h: list[float], l: list[float], c: list[float], handle_na: bool) -> list[float]:
    out = []
    for i in range(len(h)):
        if i == 0:
            out.append(h[0] - l[0] if handle_na else NA)
        else:
            out.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return out


def qtrend(o: list[float], h: list[float], l: list[float], c: list[float], p: int = 200, atr_p: int = 32,
           mult: float = 1.0, smooth: int | None = 10) -> list[dict]:
    src = ema(c, smooth) if smooth else list(c)
    hh = rolling(src, p, max)
    ll = rolling(src, p, min)
    atr = rma(true_range(h, l, c, True), atr_p)
    out = []
    m_prev, ls_prev = NA, ""
    sb_hist, ss_hist = deque(maxlen=5), deque(maxlen=5)
    for i in range(len(c)):
        hi, lo = hh[i], ll[i]
        d = hi - lo
        m = (hi + lo) / 2
        if i > p:
            m = m_prev
        eps = mult * (atr[i - 1] if i >= 1 else NA)
        up = (not na(m) and not na(eps)) and src[i] > m + eps
        down = (not na(m) and not na(eps)) and src[i] < m - eps
        sb = (not na(d)) and o[i] < lo + d / 8 and o[i] >= lo
        ss = (not na(d)) and o[i] > hi - d / 8 and o[i] <= hi
        sb_hist.append(sb)
        ss_hist.append(ss)
        strong_buy, strong_sell = any(sb_hist), any(ss_hist)
        if (up or down) and not na(m_prev) and m != m_prev:
            m_new = m
        elif (up or down) and na(m_prev) and not na(m):
            m_new = m
        elif up:
            m_new = m + eps
        elif down:
            m_new = m - eps
        else:
            m_new = m if na(m_prev) else m_prev
        ls = "B" if up else "S" if down else ls_prev
        buy = up and ls_prev != "B"
        sell = down and ls_prev != "S"
        out.append({"buy": int(buy), "sell": int(sell), "strong_buy": int(buy and strong_buy),
                    "strong_sell": int(sell and strong_sell), "trend_line": None if na(m_new) else m_new})
        m_prev, ls_prev = m_new, ls
    return out


def klinger(h: list[float], l: list[float], c: list[float], v: list[float], fast: int = 38, slow: int = 60,
            sig: int = 13) -> list[dict]:
    hlc3 = [(h[i] + l[i] + c[i]) / 3 for i in range(len(c))]
    trend, cm, vf = [], [], []
    for i in range(len(c)):
        dm = h[i] - l[i]
        if i == 0:
            t, m = 0.0, 0.0
        else:
            mom = hlc3[i] - hlc3[i - 1]
            t = 1.0 if mom > 0 else -1.0 if mom < 0 else trend[-1]
            m = cm[-1] + dm if t == trend[-1] else dm + (h[i - 1] - l[i - 1])
        trend.append(t)
        cm.append(m)
        vf.append(100 * v[i] * t * abs(2 * dm / m - 1) if m != 0 else 0.0)
    kvo = [a - b for a, b in zip(ema(vf, fast), ema(vf, slow))]
    signal = ema(kvo, sig)
    return [{"hist": k - s, "kvo": k, "signal": s} for k, s in zip(kvo, signal)]


def linreg(xs: deque) -> float:
    n = len(xs)
    sx = n * (n - 1) / 2
    sxx = (n - 1) * n * (2 * n - 1) / 6
    sy = sum(xs)
    sxy = sum(i * y for i, y in enumerate(xs))
    slope = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    intercept = (sy - slope * sx) / n
    return intercept + slope * (n - 1)


def squeeze(h: list[float], l: list[float], c: list[float], length: int = 20, mult_kc: float = 1.5) -> list[dict]:
    basis = sma(c, length)
    dev = [mult_kc * x for x in rolling(c, length, lambda q: math.sqrt(sum((y - sum(q) / len(q)) ** 2 for y in q) / len(q)))]
    rng = sma(true_range(h, l, c, False), length)
    hh = rolling(h, length, max)
    ll = rolling(l, length, min)
    x = [c[i] - ((hh[i] + ll[i]) / 2 + basis[i]) / 2 for i in range(len(c))]
    out, q = [], deque(maxlen=length)
    for i in range(len(c)):
        if not na(x[i]):
            q.append(x[i])
        val = linreg(q) if len(q) == length and not na(x[i]) else NA
        if na(basis[i]) or na(rng[i]):
            state = None
        else:
            lbb, ubb = basis[i] - dev[i], basis[i] + dev[i]
            lkc, ukc = basis[i] - rng[i] * mult_kc, basis[i] + rng[i] * mult_kc
            on = lbb > lkc and ubb < ukc
            off = lbb < lkc and ubb > ukc
            state = SQZ_STATE["on"] if on else SQZ_STATE["off"] if off else SQZ_STATE["none"]
        out.append({"momentum": None if na(val) else val, "state": state})
    return out


def zerolag(h: list[float], l: list[float], c: list[float], length: int = 70, mult: float = 1.2) -> list[dict]:
    """Zero Lag Trend Signals (MTF) [AlgoAlpha] v4, the AGENT charts' inputs (70, 1.2): the basis, and the band the
    script draws (the lower band in a bullish trend, the upper one in a bearish trend; none before the first cross)."""
    lag = (length - 1) // 2
    shifted = [c[i] + (c[i] - c[i - lag]) if i >= lag else NA for i in range(len(c))]
    zlema = ema(shifted, length)
    vol = [x * mult if not na(x) else NA for x in rolling(rma(true_range(h, l, c, True), length), length * 3,
                                                           lambda q: NA if any(na(y) for y in q) else max(q))]
    out, trend = [], 0
    for i in range(len(c)):
        if i > 0 and not (na(zlema[i]) or na(vol[i]) or na(zlema[i - 1]) or na(vol[i - 1])):
            up_now, up_before = zlema[i] + vol[i], zlema[i - 1] + vol[i - 1]
            dn_now, dn_before = zlema[i] - vol[i], zlema[i - 1] - vol[i - 1]
            if c[i] > up_now and c[i - 1] <= up_before:
                trend = 1
            if c[i] < dn_now and c[i - 1] >= dn_before:
                trend = -1
        basis = None if na(zlema[i]) else zlema[i]
        upper = zlema[i] + vol[i] if trend == -1 and basis is not None and not na(vol[i]) else None
        lower = zlema[i] - vol[i] if trend == 1 and basis is not None and not na(vol[i]) else None
        out.append({"basis": basis, "upper_band": upper, "lower_band": lower})
    return out


def compute(rows: list[tuple], with_zerolag: bool = True) -> list[dict]:
    """rows: (open_time, open, high, low, close, volume). Returns the values of every bar, as the agent stores them."""
    o = [r[1] for r in rows]
    h = [r[2] for r in rows]
    l = [r[3] for r in rows]
    c = [r[4] for r in rows]
    v = [r[5] for r in rows]
    out = [{"qtrend": q, "klinger": k, "squeeze": s} for q, k, s in zip(qtrend(o, h, l, c), klinger(h, l, c, v), squeeze(h, l, c))]
    if with_zerolag:
        for d, z in zip(out, zerolag(h, l, c)):
            d["zerolag"] = z
    return out


def htf_bars(rows15: list[tuple], hours: int) -> list[tuple]:
    """1h or 4h candles (open_time, open, high, low, close, volume) built from complete groups of 15m candles."""
    step, groups = hours * 3_600_000, {}
    for t, o, h, l, c, v in rows15:
        k = t // step * step
        g = groups.get(k)
        if g is None:
            groups[k] = [k, o, h, l, c, v, 1]
        else:
            g[2], g[3], g[4], g[5], g[6] = max(g[2], h), min(g[3], l), c, g[5] + v, g[6] + 1
    need = step // 900_000
    return [tuple(g[:6]) for _, g in sorted(groups.items()) if g[6] == need]


# ---------------------------------------------------------------------------------------------------- validation
ROOT = Path(__file__).resolve().parents[2]
TV = ROOT / "data" / "research" / "v6_snapshots.db"
LONG = ROOT / "data" / "research" / "long" / "journal.db"


def validate() -> None:
    tv = sqlite3.connect(f"file:{TV}?mode=ro", uri=True)
    lg = sqlite3.connect(f"file:{LONG}?mode=ro", uri=True)
    step = {"5m": 300_000, "15m": 900_000}
    codes: dict = {}
    for coin in ("XRP", "SOL", "ETH"):
        for tf in ("5m", "15m"):
            tvrows = {t: json.loads(v) for t, v in tv.execute(
                "SELECT bar_time, values_json FROM snapshots WHERE symbol = ? AND timeframe = ? ORDER BY bar_time", (coin, tf))}
            if not tvrows:
                continue
            first_tv, last_tv = min(tvrows), max(tvrows)
            candles = lg.execute("SELECT open_time, open, high, low, close, volume FROM candles WHERE symbol = ? AND timeframe = ?"
                                 " AND open_time <= ? ORDER BY open_time", (coin, tf, last_tv)).fetchall()
            if not candles or candles[0][0] > first_tv:
                print(f"{coin} {tf}: candles not there yet")
                continue
            # (a) the same start as TradingView's loaded chart (10,000 bars, the first 300 were warm-up in the read)
            start_a = first_tv - 300 * step[tf]
            runs = {"same start as TradingView": [r for r in candles if r[0] >= start_a], "1.5-year history": candles}
            for label, rows in runs.items():
                vals = dict(zip((r[0] for r in rows), compute(rows)))
                both = [t for t in tvrows if t in vals]
                res = {}
                for flag in ("buy", "sell"):
                    tv_on = {t for t in both if (tvrows[t].get("qtrend") or {}).get(flag) == 1}
                    py_on = {t for t in both if vals[t]["qtrend"][flag] == 1}
                    res[flag] = (len(tv_on), len(py_on), len(tv_on & py_on))
                kl = [t for t in both if (tvrows[t].get("klinger") or {}).get("hist") is not None]
                k_agree = sum((tvrows[t]["klinger"]["hist"] >= 0) == (vals[t]["klinger"]["hist"] >= 0) for t in kl) / max(len(kl), 1)
                sq = [t for t in both if (tvrows[t].get("squeeze") or {}).get("state") is not None and vals[t]["squeeze"]["state"] is not None]
                for t in sq:
                    key = (tvrows[t]["squeeze"]["state"], vals[t]["squeeze"]["state"])
                    codes[key] = codes.get(key, 0) + 1
                s_agree = sum(tvrows[t]["squeeze"]["state"] == vals[t]["squeeze"]["state"] for t in sq) / max(len(sq), 1)
                tl = [t for t in both if (tvrows[t].get("qtrend") or {}).get("trend_line") and vals[t]["qtrend"]["trend_line"]]
                tl_err = sorted(abs(vals[t]["qtrend"]["trend_line"] / tvrows[t]["qtrend"]["trend_line"] - 1) for t in tl)
                print(f"{coin} {tf} [{label}] bars {len(both)} | buy TV {res['buy'][0]} Py {res['buy'][1]} same {res['buy'][2]}"
                      f" | sell TV {res['sell'][0]} Py {res['sell'][1]} same {res['sell'][2]} | Klinger sign {k_agree:.1%}"
                      f" | squeeze state {s_agree:.1%} | trend line median err {tl_err[len(tl_err) // 2] if tl_err else 0:.2e}", flush=True)
    print("squeeze codes (TV, Py):", codes)


if __name__ == "__main__":
    if sys.argv[1] == "validate":
        validate()
