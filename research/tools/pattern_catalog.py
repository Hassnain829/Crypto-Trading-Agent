r"""Every candlestick pattern and every chart pattern on XRP, SOL, ETH, BTC and ZEC: how often each formed, and how it
did traded on its own (2026-10-24). Research only.

    .venv\Scripts\python -u research\tools\pattern_catalog.py

XRP/SOL/ETH/BTC: the 4-year research journal (2022-10 to 2026-10). ZEC: the 1.5-year 13-coin journal (2025-04 to 2026-10).
Trade rule (as research/notes/2026-10-23-patterns-plan.md): enter at the next candle's open in the pattern's direction,
stop beyond the pattern, target 1.5R, at most 24 candles, 0.14% costs, stops closer than 0.2% skipped; chance = the same
rule on random candles in the same direction and trend context.
Writes data/research/pattern_catalog.csv and .json.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import psutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pt = _load("patterns_test", "patterns_test.py")
pm = _load("patterns_more", "patterns_more.py")
SOURCES = {"XRP": pt.LONG, "SOL": pt.LONG, "ETH": pt.LONG, "BTC": pt.LONG, "ZEC": ROOT / "data" / "research" / "long" / "journal.db"}
CANDLE_TF = ["5m", "15m", "1h", "4h", "1d"]
CHART_TF = ["15m", "1h", "4h", "1d"]
RULE = {"1h": "1h", "4h": "4h", "1d": "1D"}
MOMENTUM = {"bullish marubozu", "bearish marubozu", "three white soldiers", "three black crows"} | pm.NO_TREND


def load(coin: str, tf: str) -> pd.DataFrame:
    src = tf if tf in ("5m", "15m") else "15m"
    with sqlite3.connect(f"file:{SOURCES[coin]}?mode=ro", uri=True) as c:
        df = pd.read_sql_query("SELECT open_time, open, high, low, close FROM candles WHERE symbol = ? AND timeframe = ?"
                               " ORDER BY open_time", c, params=(coin, src))
    df.index = pd.to_datetime(df.pop("open_time"), unit="ms", utc=True)
    df = df[df.index < pd.Timestamp("2026-10-20 06:00", tz="UTC")]
    if tf in RULE:
        df = df.resample(RULE[tf], label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return df


def main() -> None:
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)  # the live agent comes first
    rng = np.random.default_rng(9)
    rows = []
    for coin in SOURCES:
        for tf in CANDLE_TF:
            df = load(coin, tf)
            start = pt.START if coin != "ZEC" else df.index[0] + pd.Timedelta(days=10)
            o, h, l, c = (df[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
            times = df.index
            valid = np.where(times >= start)[0]
            valid = valid[(valid > 20) & (valid + pt.HOLD < len(c))]
            mid = times[valid[len(valid) // 2]]
            months = (times[valid[-1]] - times[valid[0]]).days / 30.44
            down = lambda n: pt.shift(c, n) < pt.shift(c, n + 10)
            up = lambda n: pt.shift(c, n) > pt.shift(c, n + 10)
            base: dict = {}

            def chance(d, span, ctx):
                if (d, span, ctx) not in base:
                    pool = valid if ctx == "none" else valid[(down(span) if ctx == "down" else up(span))[valid]]
                    sample = pool if len(pool) <= 20000 else np.sort(rng.choice(pool, 20000, replace=False))
                    br, _ = pt.simulate(o, h, l, c, sample, d, pt.pattern_stop(l, h, sample, d, span))
                    base[(d, span, ctx)] = float(br.mean()) if len(br) else float("nan")
                return base[(d, span, ctx)]

            items = [("candlestick", n, d, s, m, None) for n, (d, s, m) in
                     {**pt.candle_patterns(o, h, l, c), **pm.extra_patterns(o, h, l, c)}.items()]
            if tf in CHART_TF:
                items += [("chart", n, d, 10, None, (idx, st)) for n, (d, idx, st) in
                          {**pt.chart_patterns(o, h, l, c), **pm.chart_more(o, h, l, c)}.items()]
            for kind, name, d, span, mask, chart in items:
                if chart is None:
                    idx = valid[mask[valid]]
                    stop = pt.pattern_stop(l, h, idx, d, span)
                    ctx = "none" if name in MOMENTUM else pm.WITH_TREND.get(name, "down" if d > 0 else "up")
                else:
                    idx, stop = chart
                    keep = np.isin(idx, valid)
                    idx, stop = idx[keep], stop[keep]
                    ctx = "none"
                r, used = pt.simulate(o, h, l, c, idx, d, stop)
                h1 = np.asarray(times[used] < mid)
                rows.append({
                    "kind": kind, "pattern": name, "direction": "bullish" if d > 0 else "bearish", "coin": coin, "tf": tf,
                    "count": int(len(idx)), "per_month": round(len(idx) / months, 2), "trades": int(len(r)),
                    "win": round(float((r > 0).mean()), 3) if len(r) else None,
                    "r": round(float(r.mean()), 3) if len(r) else None,
                    "chance": round(chance(d, span, ctx), 3),
                    "r_h1": round(float(r[h1].mean()), 3) if h1.any() else None,
                    "r_h2": round(float(r[~h1].mean()), 3) if (~h1).any() else None,
                    "period": f"{times[valid[0]]:%Y-%m} to {times[valid[-1]]:%Y-%m}",
                })
            print(f"{coin} {tf}: done", flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(ROOT / "data" / "research" / "pattern_catalog.csv", index=False)
    (ROOT / "data" / "research" / "pattern_catalog.json").write_text(json.dumps(rows), encoding="utf-8")
    print("\nTOTALS (occurrences)")
    tot = out.groupby(["coin", "kind"])["count"].sum().unstack()
    print(tot)
    print("\nper timeframe")
    print(out.groupby(["coin", "kind", "tf"])["count"].sum().unstack())


if __name__ == "__main__":
    main()
