r"""Smart targets and exits for v4, stage 1: the data and the rule versions (2026-10-29). Research only.

The user asked (2026-10-29) for a target that follows the chart (swing highs/lows, support and resistance) instead of the
fixed 1.5R, and an exit plan for trades that turn out wrong, with ML if it helps. Plan, written before the results:
research/notes/2026-10-29-exits-plan.md.

Every trade is walked on 1m candles from the fill to the 72 h limit with the tracker's rules (wide_stop_4y.run: stop
first when both are touched in a minute, no target in the fill minute, maker entry and target, taker + slippage for
stops and market exits; funding left out). For each trade:
- the fixed plan (today) and the rule versions: support/resistance targets, runners after the target, early exits,
- for the ML stage (exit_tp_ml.py): the state at every 15m close while the trade is open with the result of exiting
  there, the state at the target touch with the runners' results, the state at the fill with the result of each fixed
  target from 1R to 3R.

Samples:
- 4 years: the design's trades (journal-news.db v0-e78944, XRP/SOL/ETH, 2022-10 to 2026-10-18) on the research
  journal's Binance candles (the live journal's after 2026-10-20); v4 = without the trades against a 2%+ BTC 12 h move,
  tier A from factor_compare.trades.
- Since 2026-08-01: v4 in the agent's own engine on its TradingView data (stop_dip_replay.py's journal).

    .venv\Scripts\python -u research\tools\exit_tp_data.py
"""
from __future__ import annotations

import calendar
import importlib.util
import json
import sqlite3
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "data" / "research" / "exit_tp"
M1, M15, H1, DAY = 60_000, 900_000, 3_600_000, 86_400_000
HOLD = 72 * H1
MAKER, TAKER, SLIP = 0.0002, 0.0005, 0.0002
AUG = calendar.timegm((2026, 8, 1, 0, 0, 0)) * 1000
CUT = 1792454400000  # 2026-10-20: the research journal's candles before, the live journal's from here
SPLIT = 1727740800000  # 2024-10-01
NEVER = np.iinfo(np.int64).max
LONG4 = ROOT / "data" / "research" / "long4" / "journal.db"
LIVE = ROOT / "data" / "journal.db"
NEWS = ROOT / "data" / "replay" / "journal-news.db"
REPLAY = ROOT / "data" / "replay" / "journal-stopdip-2026-08-01.db"
FIXED = [1.0, 1.25, 1.5, 2.0, 2.5, 3.0]  # targets in R from the fill, for the ML target model
RUNNERS = {"atr2_lock1": (1.0, "atr", 2.0), "atr3_lock125": (1.25, "atr", 3.0), "low4_lock1": (1.0, "low4", 0.0)}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ws = _load("wide_stop_4y")
li = _load("long_indicators")


def ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


class Source:
    """A sample's candles: (connection, first open time, last open time) parts, read in order."""

    def __init__(self, parts: list[tuple[sqlite3.Connection, int, int]]):
        self.parts = parts

    def rows(self, coin: str, tf: str, a: int = 0, b: int = NEVER) -> np.ndarray:
        out = []
        for conn, lo, hi in self.parts:
            x, y = max(a, lo), min(b, hi)
            if x <= y:
                out += conn.execute("SELECT open_time, open, high, low, close, volume FROM candles WHERE symbol = ?"
                                    " AND timeframe = ? AND open_time >= ? AND open_time <= ? ORDER BY open_time",
                                    (coin, tf, x, y)).fetchall()
        return np.array(out, dtype=float).reshape(-1, 6)


def group(rows: np.ndarray, step: int, complete: int = 0) -> np.ndarray:
    """Candles of a longer timeframe (open time, o, h, l, c, v); with `complete`, only groups of that many candles."""
    df = pd.DataFrame(rows[:, 1:], columns=["o", "h", "l", "c", "v"]).assign(k=(rows[:, 0] // step * step).astype(np.int64))
    g = df.groupby("k").agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"), v=("v", "sum"), n=("o", "size"))
    if complete:
        g = g[g["n"] == complete]
    return np.column_stack([g.index.to_numpy(dtype=float), g[["o", "h", "l", "c", "v"]].to_numpy(dtype=float)])


def rma(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        out[n - 1] = x[:n].mean()
        for i in range(n, len(x)):
            out[i] = out[i - 1] + (x[i] - out[i - 1]) / n
    return out


def pivots(t: np.ndarray, h: np.ndarray, l: np.ndarray, step: int, n: int) -> dict:
    """Swing highs (+1) and lows (-1): the highest high (lowest low) of the n candles on each side. Known when the n-th
    candle after it closes; broken when a later candle that traded beyond it has closed (no look-ahead inside a
    candle). {side: (price, formed, known, broken)}."""
    out = {}
    for sign, x in ((1, h), (-1, l)):
        y = sign * x
        ext = pd.Series(y).rolling(2 * n + 1, center=True).max().to_numpy()
        idx = np.nonzero(y == ext)[0]
        nxt = np.full(len(y), -1)
        stack: list[int] = []
        for i, yi in enumerate(y):
            while stack and yi > y[stack[-1]]:
                nxt[stack.pop()] = i
            stack.append(i)
        nb = nxt[idx]
        broken = np.where(nb >= 0, t[np.maximum(nb, 0)] + step, NEVER)
        out[sign] = (x[idx], t[idx], t[idx + n] + step, broken)
    return out


def beyond(piv: dict, d: int, ms: int, ref: float) -> np.ndarray:
    """Price distances from ref to the unbroken swing levels beyond it in the trade's direction (highs above for a long,
    lows below for a short), known at ms and at most 10 days old, nearest first."""
    price, formed, known, broken = piv[d]
    m = (known <= ms) & (broken > ms) & (formed >= ms - 10 * DAY) & (d * (price - ref) > 0)
    return np.sort(d * (price[m] - ref))


class Bars:
    """15m candles of one coin and what a rule can read at a 15m close: ATR(14), Q-Trend's direction (the side of its
    last signal), Klinger's histogram, the last hour's volume against the day before, and the swing levels."""

    def __init__(self, rows: np.ndarray, indicators: bool = True):
        self.t = rows[:, 0].astype(np.int64)
        self.o, self.h, self.l, self.c, self.v = (rows[:, k] for k in range(1, 6))
        self.close_t = self.t + M15
        prev = np.concatenate([[self.c[0]], self.c[:-1]])
        self.atr = rma(np.maximum(self.h - self.l, np.maximum(np.abs(self.h - prev), np.abs(self.l - prev))), 14)
        if not indicators:
            return
        state, qs = 0, []
        for x in li.qtrend(*(list(a) for a in (self.o, self.h, self.l, self.c))):
            state = 1 if x["buy"] else -1 if x["sell"] else state
            qs.append(state)
        self.qt = np.array(qs)
        vol = np.nan_to_num(self.v)
        self.kl = np.array([x["hist"] for x in li.klinger(*(list(a) for a in (self.h, self.l, self.c, vol)))])
        v = pd.Series(vol)
        self.volr = (v.rolling(4).sum() / (v.shift(4).rolling(96).mean() * 4).replace(0, np.nan)).to_numpy()
        hourly = group(rows, H1, complete=4)
        self.piv = {"15m": pivots(self.t, self.h, self.l, M15, 5),
                    "1h": pivots(hourly[:, 0].astype(np.int64), hourly[:, 2], hourly[:, 3], H1, 3)}

    def at(self, ms):
        """Index of the last candle closed at or before ms."""
        return np.searchsorted(self.close_t, ms, side="right") - 1


def market_r(d: int, fill: float, risk: float, price):
    """R of a market exit at `price` (slippage and taker fee; maker entry)."""
    xf = price * (1 - d * SLIP)
    return d * (xf - fill) / risk - (fill * MAKER + xf * TAKER) / risk


def plan_exit(d: int, stop: float, target: float, t: np.ndarray, h: np.ndarray, l: np.ndarray, entry: int) -> tuple[int, str]:
    """(minute index, reason) of the exit, as wide_stop_4y.run decides it; a timeout exits at the first minute at or
    after the 72 h limit."""
    inside = t < entry + HOLD
    hs = ((l <= stop) if d > 0 else (h >= stop)) & inside
    ht = ((h >= target) if d > 0 else (l <= target)) & inside
    ht[:1] = False
    i_s = int(np.argmax(hs)) if hs.any() else None
    i_t = int(np.argmax(ht)) if ht.any() else None
    if i_s is not None and (i_t is None or i_s <= i_t):
        return i_s, "stop"
    if i_t is not None:
        return i_t, "target"
    out = np.nonzero(~inside)[0]
    return (int(out[0]) if len(out) else len(t) - 1), "timeout"


def runner(d, fill, risk, t, o, h, l, i_touch, entry, bars: Bars, lock_r: float, mode: str, k: float) -> tuple[float, int]:
    """The trade stays open at the target touch: from the next minute the stop is at fill + lock_r R, and at every 15m
    close it trails ('atr': k x the 15m ATR at the touch from the best price since the touch; 'low4': beyond the last
    four closed 15m candles), never loosening. Exits at the stop (taker + slippage, at the open if it gapped) or at the
    72 h limit. Returns (R, exit time)."""
    lock = fill + d * lock_r * risk
    after = np.arange(i_touch + 1, len(t))
    after = after[t[after] < entry + HOLD]
    taus = np.arange((int(t[i_touch]) // M15 + 1) * M15, entry + HOLD, M15)
    jb = np.searchsorted(t, taus)
    keep = (jb < len(t)) & (jb > i_touch)
    taus, jb = taus[keep], jb[keep]
    if mode == "atr":
        atr = bars.atr[bars.at(int(t[i_touch]))]
        best = np.maximum.accumulate(h[i_touch:]) if d > 0 else np.minimum.accumulate(l[i_touch:])
        cand = best[jb - 1 - i_touch] - d * k * atr
    else:
        bi = bars.at(taus)
        cand = np.array([bars.l[x - 3:x + 1].min() if d > 0 else bars.h[x - 3:x + 1].max() for x in bi])
    lvl = np.maximum(lock, np.maximum.accumulate(cand)) if d > 0 else np.minimum(lock, np.minimum.accumulate(cand))
    kidx = np.searchsorted(jb, after, side="right") - 1
    stop = np.where(kidx >= 0, lvl[np.maximum(kidx, 0)] if len(lvl) else lock, lock)
    hit = (l[after] <= stop) if d > 0 else (h[after] >= stop)
    if hit.any():
        q = int(np.argmax(hit))
        m, s = after[q], stop[q]
        ref = o[m] if (o[m] <= s if d > 0 else o[m] >= s) else s
        return float(market_r(d, fill, risk, ref)), int(t[m]) + M1
    out = np.nonzero(t >= entry + HOLD)[0]
    return float(market_r(d, fill, risk, o[out[0]] if len(out) else o[-1])), entry + HOLD


def walk(tr: dict, m: np.ndarray, bars: Bars, btc: Bars) -> tuple[dict, pd.DataFrame | None, dict | None]:
    d = 1 if tr["side"] == "long" else -1
    fill, stop, target, entry = tr["fill"], tr["stop"], tr["target"], tr["entry_time"]
    risk = abs(fill - stop)
    t = m[:, 0].astype(np.int64)
    o, h, l, c = m[:, 1], m[:, 2], m[:, 3], m[:, 4]

    def outcome(tgt: float) -> tuple[float, int]:
        r, _ = ws.run(d, fill, stop, tgt, t, o, h, l, entry)
        i, why = plan_exit(d, stop, tgt, t, h, l, entry)
        return r, (int(t[i]) + M1 if why != "timeout" else entry + HOLD)

    r0, why0 = ws.run(d, fill, stop, target, t, o, h, l, entry)
    ix, why = plan_exit(d, stop, target, t, h, l, entry)
    x0 = int(t[ix]) + M1 if why != "timeout" else entry + HOLD
    t_r = d * (target - fill) / risk
    rec = {k: tr[k] for k in ("id", "sample", "symbol", "side", "entry_time", "quality", "v4", "fa", "fc", "fd", "r_check")}
    rec.update(long=int(d > 0), q_a=int(tr["quality"] == "A"), t_r=t_r, stop_pct=risk / fill * 100, r_plan=r0, x_plan=x0,
               why_plan=why, why_check=why0)

    for k in FIXED:
        rec[f"r_fix{k:g}"], rec[f"x_fix{k:g}"] = outcome(fill + d * k * risk)

    # support/resistance targets, known at the fill
    b, bb = int(bars.at(entry)), int(btc.at(entry))
    buf = 0.1 * bars.atr[b]
    for src in ("15m", "1h"):
        cand = (beyond(bars.piv[src], d, entry, fill) - buf) / risk
        near = cand[cand >= 0.8]
        first = float(near[0]) if len(near) else np.inf
        rec[f"e_lvl_{src}"] = min(first, 9.0)
        rec[f"e_n3_{src}"] = int(((cand > 0) & (cand <= 3)).sum())
        for name, ok in (("front", first < t_r), ("extend", t_r <= first <= 3.0), ("both", first <= 3.0)):
            rec[f"r_sr_{name}_{src}"], rec[f"x_sr_{name}_{src}"] = outcome(fill + d * first * risk) if ok else (r0, x0)

    # the state at the fill (ML target model)
    btc_at = lambda ms: btc.c[btc.at(ms)]
    rec.update(e_atr_r=bars.atr[b] / risk, e_volr=bars.volr[b], e_qt=bars.qt[b] * d, e_kl=np.sign(bars.kl[b]) * d,
               e_ret1h=d * (bars.c[b] - bars.c[b - 4]) / risk, e_ret4h=d * (bars.c[b] - bars.c[b - 16]) / risk,
               e_btc1h=d * (btc.c[bb] / btc_at(entry - H1) - 1) * 100, e_btc4h=d * (btc.c[bb] / btc_at(entry - 4 * H1) - 1) * 100,
               e_btc12h=d * (btc.c[bb] / btc_at(entry - 12 * H1) - 1) * 100, e_hour=(entry // H1) % 24)

    # the state at every 15m close while the trade is open, and the result of a market exit at the next minute's open
    taus = np.arange((entry // M15 + 1) * M15, entry + HOLD, M15)
    j = np.searchsorted(t, taus)
    keep = (j < len(t)) & (j <= ix) & (j >= 1)
    taus, j = taus[keep], j[keep]
    cps = None
    for name in ("qt_against", "qt_against_loss", "noprog_2h", "noprog_4h", "noprog_8h", "btc_against", "qt_kl_against",
                 "fast_to_stop"):
        rec[f"r_ex_{name}"], rec[f"x_ex_{name}"] = r0, x0
    if len(j):
        p = j - 1
        cmax, cmin = np.maximum.accumulate(h), np.minimum.accumulate(l)
        bi, bt = bars.at(taus), btc.at(taus)
        cps = pd.DataFrame(dict(
            id=tr["id"], tau=taus, el=(taus - entry) / H1, r_now=d * (c[p] - fill) / risk,
            mfe=((cmax[p] - fill) if d > 0 else (fill - cmin[p])) / risk,
            mae=((fill - cmin[p]) if d > 0 else (cmax[p] - fill)) / risk,
            r_exit=market_r(d, fill, risk, o[j]), x_exit=t[j],
            atr_r=bars.atr[bi] / risk, volr=bars.volr[bi], qt=bars.qt[bi] * d, kl=np.sign(bars.kl[bi]) * d,
            ret1h=d * (bars.c[bi] - bars.c[bi - 4]) / risk, ret4h=d * (bars.c[bi] - bars.c[bi - 16]) / risk,
            btc_since=d * (btc.c[bt] / btc.c[bb] - 1) * 100, btc1h=d * (btc.c[bt] / btc.c[btc.at(taus - H1)] - 1) * 100,
            btc4h=d * (btc.c[bt] / btc.c[btc.at(taus - 4 * H1)] - 1) * 100, coin_since=d * (c[p] / fill - 1) * 100,
            hour=(taus // H1) % 24))
        el, rn, mfe = cps["el"].to_numpy(), cps["r_now"].to_numpy(), cps["mfe"].to_numpy()
        qt, kl, ret1h, bs = (cps[x].to_numpy() for x in ("qt", "kl", "ret1h", "btc_since"))
        rules = {"qt_against": qt < 0, "qt_against_loss": (qt < 0) & (rn < 0), "btc_against": (bs <= -1.0) & (rn < 0),
                 "qt_kl_against": (qt < 0) & (kl < 0) & (rn <= -0.3), "fast_to_stop": (rn <= -0.5) & (ret1h <= -0.3)}
        for hours in (2, 4, 8):
            once = np.zeros(len(el), bool)
            if (el >= hours).any():
                once[int(np.argmax(el >= hours))] = True
            rules[f"noprog_{hours}h"] = once & (mfe < 0.5) & (rn < 0)
        for name, fire in rules.items():
            if fire.any():
                q = int(np.argmax(fire))
                rec[f"r_ex_{name}"], rec[f"x_ex_{name}"] = float(cps["r_exit"].iat[q]), int(cps["x_exit"].iat[q])

    # the target touch: its state and the runners
    touch = None
    for name in RUNNERS:
        rec[f"r_run_{name}"], rec[f"x_run_{name}"] = r0, x0
    if why == "target":
        tt = int(t[ix])
        bi, bt = int(bars.at(tt)), int(btc.at(tt))
        touch = dict(id=tr["id"], t_touch=tt, el=(tt - entry) / H1, speed1h=d * (target - c[max(ix - 60, 0)]) / risk,
                     mae=((fill - l[:ix].min()) if d > 0 else (h[:ix].max() - fill)) / risk if ix > 0 else 0.0,
                     atr_r=bars.atr[bi] / risk, volr=bars.volr[bi], qt=bars.qt[bi] * d, kl=np.sign(bars.kl[bi]) * d,
                     ret1h=d * (bars.c[bi] - bars.c[bi - 4]) / risk, ret4h=d * (bars.c[bi] - bars.c[bi - 16]) / risk,
                     btc_since=d * (btc.c[bt] / btc.c[bb] - 1) * 100, btc1h=d * (btc.c[bt] / btc_at(tt - H1) - 1) * 100,
                     btc4h=d * (btc.c[bt] / btc_at(tt - 4 * H1) - 1) * 100, hour=(tt // H1) % 24, r_take=r0)
        for src in ("15m", "1h"):
            dist = beyond(bars.piv[src], d, tt, target)
            touch[f"next_{src}"] = min(float(dist[0]) / risk, 9.0) if len(dist) else 9.0
        # how far the price went on after the touch (within the loaded 72 h): in 24 h, and before it came back to +1R
        day = (t >= tt) & (t < tt + 24 * H1)
        fav = ((h - fill) if d > 0 else (fill - l)) / risk
        back = np.nonzero(((l <= fill + risk) if d > 0 else (h >= fill - risk)) & (t > tt))[0]
        end = back[0] if len(back) else len(t)
        touch.update(after24=float(fav[day].max()), before1=float(fav[ix:end].max()),
                     back1_24=int(len(back) > 0 and t[back[0]] < tt + 24 * H1))
        for name, (lock_r, mode, k) in RUNNERS.items():
            r, x = runner(d, fill, risk, t, o, h, l, ix, entry, bars, lock_r, mode, k)
            touch[f"r_{name}"], touch[f"x_{name}"] = r, x
            rec[f"r_run_{name}"], rec[f"x_run_{name}"] = r, x
    return rec, cps, touch


def sample_4y() -> tuple[list[dict], Source, Bars, dict]:
    fc = _load("factor_compare")
    f = fc.trades(NEWS, "v0-e78944")  # the tier-A reasons and the BTC skip flag of each design trade
    info = {int(i): (not ag, a, c, db) for i, ag, a, c, db in zip(f["id"], f["against"], f["a"], f["c"], f["d_btc"])}
    rows = ro(NEWS).execute("SELECT id, symbol, side, entry_time, entry_ref, stop_initial, target,"
                            " r_net + coalesce(funding_r, 0) FROM trades WHERE variant_id = 'v0-e78944' AND taken = 1"
                            " AND status = 'closed' ORDER BY entry_time").fetchall()
    trades = []
    for tid, sym, side, entry, fill, stop, target, r_check in rows:
        if tid not in info:
            continue
        v4, a, c, db = info[tid]
        trades.append(dict(id=tid, sample="4y", symbol=sym, side=side, entry_time=entry, fill=fill, stop=stop, target=target,
                           quality="A" if (a or c or db) else "B", v4=bool(v4), fa=int(a), fc=int(c), fd=int(db), r_check=r_check))
    long4, live = ro(LONG4), ro(LIVE)
    src = Source([(long4, 0, CUT - 1), (live, CUT, NEVER)])
    btc = Bars(np.vstack([Source([(long4, 0, CUT - 1)]).rows("BTC", "15m"),
                          group(Source([(live, CUT, NEVER)]).rows("BTC", "5m"), M15)]), indicators=False)
    return trades, src, btc, {c: Bars(src.rows(c, "15m")) for c in ("XRP", "SOL", "ETH")}


def sample_aug() -> tuple[list[dict], Source, Bars, dict]:
    db = ro(REPLAY)
    rows = db.execute("SELECT id, symbol, side, entry_time, entry_ref, stop_initial, target, r_net + coalesce(funding_r, 0),"
                      " context_json FROM trades WHERE variant_id = 'v0-d1d9b2' AND taken = 1 AND status = 'closed'"
                      " AND entry_time >= ? ORDER BY entry_time", (AUG,)).fetchall()
    trades = [dict(id=tid, sample="aug", symbol=sym, side=side, entry_time=entry, fill=fill, stop=stop, target=target,
                   quality=json.loads(ctx or "{}").get("quality") or "B", v4=True, fa=-1, fc=-1, fd=-1, r_check=r_check)
              for tid, sym, side, entry, fill, stop, target, r_check, ctx in rows]
    src = Source([(db, 0, NEVER)])
    btc = Bars(group(src.rows("BTC", "5m"), M15), indicators=False)
    return trades, src, btc, {c: Bars(src.rows(c, "15m")) for c in ("XRP", "SOL", "ETH")}


def main() -> None:
    import psutil

    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)  # the live agent comes first
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    recs, cps, touches = [], [], []
    for loader in (sample_4y, sample_aug):
        trades, src, btc, bars = loader()
        print(f"{loader.__name__}: {len(trades)} trades, candles ready {time.monotonic() - t0:.0f} s", flush=True)
        for n, tr in enumerate(trades):
            m = src.rows(tr["symbol"], "1m", tr["entry_time"], tr["entry_time"] + HOLD)
            if len(m) == 0:
                continue
            rec, cp, touch = walk(tr, m, bars[tr["symbol"]], btc)
            recs.append(rec)
            if cp is not None:
                cps.append(cp.assign(sample=tr["sample"]))
            if touch is not None:
                touches.append(touch | {"sample": tr["sample"]})
            if n % 500 == 0:
                print(f"   {n}/{len(trades)} {time.monotonic() - t0:.0f} s", flush=True)
    df = pd.DataFrame(recs)
    df.to_csv(OUT / "trades.csv", index=False)
    pd.concat(cps).to_csv(OUT / "checkpoints.csv", index=False)
    pd.DataFrame(touches).to_csv(OUT / "touches.csv", index=False)
    chk = df[df["sample"] == "4y"]
    diff = (chk["r_plan"] - chk["r_check"]).abs()
    print(f"check vs the tracker (funding added back): {int((diff < 1e-6).sum())}/{len(chk)} the same, mean |dR| {diff.mean():.4f};"
          f" exit reasons agree {int((chk['why_plan'] == chk['why_check']).sum())}/{len(chk)}")
    print(f"{len(df)} trades, {sum(len(c) for c in cps)} checkpoints, {len(touches)} target touches; {time.monotonic() - t0:.0f} s")


if __name__ == "__main__":
    main()
