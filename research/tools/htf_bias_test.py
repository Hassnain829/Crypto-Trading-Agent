r"""Higher-timeframe candle patterns as the direction, scalps on 15m/5m (2026-10-23). Research only.

    .venv\Scripts\python -u research\tools\htf_bias_test.py > data\research\htf_bias.txt

Plan, written before the results: research/notes/2026-10-23-htf-bias-plan.md.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import psutil

HERE = Path(__file__).resolve().parent
def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pt = _load("patterns_test", "patterns_test.py")
pm = _load("patterns_more", "patterns_more.py")
pa = pm.pa

COINS = ["XRP", "SOL", "ETH", "BTC"]
TRADED = ["XRP", "SOL", "ETH"]
COST, TARGET, SWING = 0.0014, 1.5, 10
SPLIT = pt.SPLIT
HTF_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
LTF_MS = {"15m": 900_000, "5m": 300_000}
HOLD_MS = 2 * 86_400_000
rng = np.random.default_rng(5)


def ms(index) -> np.ndarray:
    return ((index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy(dtype="int64")


def bias_events(conn, coin: str, tf: str, kind: str) -> tuple[np.ndarray, np.ndarray]:
    """(close time ms, direction) of the HTF candles that set a bias; kind = 'candle', 'chart' or 'random'."""
    df = pt.load(conn, coin, tf)
    o, h, l, c = (df[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
    close = ms(df.index) + HTF_MS[tf]
    bull, bear = np.zeros(len(c), bool), np.zeros(len(c), bool)
    if kind in ("candle", "random"):
        for name, (d, span, m) in pt.candle_patterns(o, h, l, c).items():
            (bull if d > 0 else bear)[:] |= m
    if kind == "chart":
        for name, (d, idx, _stop) in list(pm.chart_more(o, h, l, c).items()) + list(pt.chart_patterns(o, h, l, c).items()):
            (bull if d > 0 else bear)[idx] = True
    if kind == "random":
        free = np.where(~bull & ~bear)[0]
        free = free[free > 20]
        pick = np.sort(rng.choice(free, min(len(free), int((bull | bear).sum())), replace=False))
        return close[pick], rng.choice([-1, 1], len(pick))
    one = bull ^ bear
    return close[one], np.where(bull[one], 1, -1)


def scalp(ltf: pd.DataFrame, events: tuple[np.ndarray, np.ndarray], window_ms: int, min_stop: float) -> pd.DataFrame:
    """One trade per bias window: the first qualifying pullback candle, entry at the next open, 10-candle swing stop, 1.5R."""
    o, h, l, c = (ltf[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
    t_open = ms(ltf.index)
    step = int(t_open[1] - t_open[0])
    hold = HOLD_MS // step
    rows = []
    for at, d in zip(*events):
        i = np.searchsorted(t_open, at)  # the first LTF candle opening at or after the bias candle's close
        end = np.searchsorted(t_open, at + window_ms)
        while i < end and i + hold + 1 < len(c):
            against = c[i] < o[i] if d > 0 else c[i] > o[i]
            if against and i >= SWING:
                entry = o[i + 1]
                stop = l[i - SWING + 1:i + 1].min() if d > 0 else h[i - SWING + 1:i + 1].max()
                risk = d * (entry - stop)
                if risk > min_stop * entry:
                    target = entry + d * TARGET * risk
                    hh, ll = h[i + 1:i + 1 + hold], l[i + 1:i + 1 + hold]
                    sh = (ll <= stop) if d > 0 else (hh >= stop)
                    th = (hh >= target) if d > 0 else (ll <= target)
                    fs = sh.argmax() if sh.any() else hold
                    ft = th.argmax() if th.any() else hold
                    r = -1.0 if fs < hold and fs <= ft else (TARGET if ft < hold else d * (c[i + hold] - entry) / risk)
                    rows.append((t_open[i + 1], d, r - COST * entry / risk))
                    break
            i += 1
    return pd.DataFrame(rows, columns=["time", "d", "r"])


def line(x: pd.DataFrame, days: float) -> str:
    if x.empty:
        return "no trades"
    h1, h2 = x[x["time"] < SPLIT.value // 1_000_000], x[x["time"] >= SPLIT.value // 1_000_000]
    f = lambda v: f"{v['r'].mean():+.3f}" if len(v) else "  -  "
    return (f"{len(x):6d} trades ({len(x) / days:4.1f}/day) won {(x['r'] > 0).mean():.0%} {x['r'].mean():+.3f}R"
            f" | {f(h1)} / {f(h2)}")


def part_a(conn) -> None:
    print("######## A. PURE PATTERN SCALPING: bias from the HTF, entry on the first LTF pullback (all 3 coins pooled, then per coin) ########")
    print("   trades (per day for 3 coins), won, R a trade | 2022-24 / 2024-26")
    ltfs = {coin: {ltf: pt.load(conn, coin, ltf) for ltf in LTF_MS} for coin in COINS}
    days = {coin: (ltfs[coin]["15m"].index[-1] - pt.START).days for coin in COINS}
    for kind in ("candle", "chart"):
        for htf in (("1h", "4h", "1d") if kind == "candle" else ("1h", "4h")):
            ev = {coin: bias_events(conn, coin, htf, kind) for coin in COINS}
            ev_rand = {coin: bias_events(conn, coin, htf, "random") for coin in COINS}
            for ltf in ("15m", "5m"):
                for label, min_stop in (("agent stop (>= 1.5%)", 0.015), ("scalper stop (>= 0.2%)", 0.002)):
                    for w in (2, 1, 4):
                        res = {coin: scalp(ltfs[coin][ltf], ev[coin], w * HTF_MS[htf], min_stop) for coin in COINS}
                        start = pt.START.value // 1_000_000
                        res = {k: v[v["time"] >= start] for k, v in res.items()}
                        pooled = pd.concat([res[c_] for c_ in TRADED])
                        tag = f"{kind} {htf} -> {ltf}, {label}, window {w}"
                        if w != 2:
                            print(f"      (window {w}: {line(pooled, days['XRP'])})")
                            continue
                        rand = pd.concat([scalp(ltfs[c_][ltf], ev_rand[c_], w * HTF_MS[htf], min_stop) for c_ in TRADED])
                        rand = rand[rand["time"] >= start]
                        print(f"\n   {tag}")
                        print(f"      XRP+SOL+ETH  {line(pooled, days['XRP'])}")
                        print(f"      chance       {line(rand, days['XRP'])}")
                        for coin in COINS:
                            print(f"      {coin:4}         {line(res[coin], days[coin])}")


def part_b(conn) -> None:
    print("\n\n######## B. THE AGENT'S DESIGN WITH THE HTF BIAS (4-year trades, XRP/SOL/ETH) ########")
    tr = pa.load_trades(pa.REPLAY / "journal-news.db", "v0-e78944")
    r, t = tr["r_net"].to_numpy(), tr["decision"].to_numpy()
    days = (t.max() - t.min()) / 86_400_000
    print(f"   all design trades: {len(tr)} ({len(tr) / days:.2f}/day), {r.mean():+.3f}R")
    for kind in ("candle", "chart"):
        for htf in (("1h", "4h", "1d") if kind == "candle" else ("1h", "4h")):
            w_ = np.zeros(len(tr), bool)
            a_ = np.zeros(len(tr), bool)
            for coin in TRADED:
                close, d = bias_events(conn, coin, htf, kind)
                sel = np.where(tr["symbol"].to_numpy() == coin)[0]
                for j in sel:
                    k = np.searchsorted(close, t[j], side="right")  # bias events closed at or before the decision
                    recent = slice(max(0, k - 50), k)
                    live = (close[recent] > t[j] - 2 * HTF_MS[htf])
                    dirs = d[recent][live]
                    if len(dirs):
                        last = dirs[-1]  # the newest bias wins
                        if last == tr["d"].iat[j]:
                            w_[j] = True
                        else:
                            a_[j] = True
            print(f"   {kind} bias from {htf} (2 candles):")
            for g, m in (("with", w_), ("against", a_), ("none", ~w_ & ~a_)):
                print(f"      {g:8} {pa.split_line(r, t, m, pa.SPLIT_MS)}  ({m.sum() / days:.2f}/day)")


def main() -> None:
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)  # the live agent comes first
    conn = sqlite3.connect(f"file:{pt.LONG}?mode=ro", uri=True)
    part_b(conn)
    part_a(conn)
    conn.close()


if __name__ == "__main__":
    main()
