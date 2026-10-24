r"""Pattern counts per coin, and higher-timeframe patterns with the new design per coin (2026-10-24). Research only.

    .venv\Scripts\python -u research\tools\pattern_coins.py > data\research\pattern_coins.txt

Plan: research/notes/2026-10-24-patterns-per-coin-plan.md (parts 2 and 3). Counts also go to
data/research/pattern_counts.csv.
"""
from __future__ import annotations

import functools
import importlib.util
import sqlite3
import sys
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
pa = pm.pa
COINS = ["XRP", "SOL", "ETH", "BTC"]
HTF = {"1h": ("1h", 3_600_000), "4h": ("4h", 14_400_000), "1d": ("1D", 86_400_000)}


def ms(index) -> np.ndarray:
    return ((index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy(dtype="int64")


def all_candle(o, h, l, c) -> dict:
    return {**pt.candle_patterns(o, h, l, c), **pm.extra_patterns(o, h, l, c)}


def all_chart(o, h, l, c) -> dict:
    return {**pt.chart_patterns(o, h, l, c), **pm.chart_more(o, h, l, c)}


def part2(conn) -> None:
    print("######## 2. HOW OFTEN EACH PATTERN FORMED (4 years, 2022-10 to 2026-10) ########")
    rows = []
    for tf in ("5m", "15m", "1h", "4h", "1d"):
        for coin in COINS:
            df = pt.load(conn, coin, tf)
            o, h, l, c = (df[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
            keep = np.asarray(df.index >= pt.START)
            months = (df.index[-1] - pt.START).days / 30.44
            for name, (d, span, m) in all_candle(o, h, l, c).items():
                rows.append(("candle", name, "bull" if d > 0 else "bear", tf, coin, int((m & keep).sum()), months))
            if tf in ("1h", "4h", "1d"):
                for name, (d, idx, _s) in all_chart(o, h, l, c).items():
                    n = int(keep[idx].sum()) if len(idx) else 0
                    rows.append(("chart", name, "bull" if d > 0 else "bear", tf, coin, n, months))
    df = pd.DataFrame(rows, columns=["kind", "pattern", "direction", "timeframe", "coin", "count", "months"])
    df["per_month"] = (df["count"] / df["months"]).round(2)
    df.drop(columns="months").to_csv(ROOT / "data" / "research" / "pattern_counts.csv", index=False)
    wide = df.pivot_table(index=["kind", "pattern", "timeframe"], columns="coin", values="count", aggfunc="sum").fillna(0).astype(int)
    for tf in ("1h", "4h", "1d"):
        print(f"\n   {tf}: count over 4 years per coin (and a month, all 4 coins together)")
        sub = wide.xs(tf, level="timeframe").copy()
        sub["all/month"] = (sub.sum(axis=1) / (4 * 12)).round(1)
        sub = sub.sort_values("all/month", ascending=False)
        for (kind, name), r in sub.iterrows():
            print(f"      {kind:6} {name:38} " + " ".join(f"{c_} {int(r[c_]):5d}" for c_ in COINS) + f"   {r['all/month']:6.1f}/month")
    never = wide[wide.sum(axis=1) == 0].reset_index()
    print("\n   never formed on any coin and timeframe: "
          + ", ".join(sorted(set(never["pattern"]) - set(wide[wide.sum(axis=1) > 0].reset_index()["pattern"]))))
    for tf in ("5m", "15m"):
        sub = wide.xs(tf, level="timeframe")
        print(f"   {tf}: all candlestick patterns together, per coin a day: "
              + ", ".join(f"{c_} {sub[c_].sum() / (4 * 365):.1f}" for c_ in COINS))


@functools.lru_cache(maxsize=None)
def htf_masks(coin: str, tf: str, source: str):
    """Close times and per-pattern masks (candle) or signal arrays (chart) of one coin's HTF candles (computed once)."""
    rule, step = HTF[tf]
    df = pa.candles15(coin) if source == "live" else pm_other15(coin)
    df = df.resample(rule, label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    o, h, l, c = (df[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
    close = ms(df.index) + step
    candle = all_candle(o, h, l, c)
    chart_bull, chart_bear = np.zeros(len(c), bool), np.zeros(len(c), bool)
    for name, (d, idx, _s) in all_chart(o, h, l, c).items():
        (chart_bull if d > 0 else chart_bear)[idx] = True
    return close, candle, chart_bull, chart_bear


def pm_other15(coin: str) -> pd.DataFrame:
    with sqlite3.connect(f"file:{ROOT / 'data' / 'research' / 'long' / 'journal.db'}?mode=ro", uri=True) as c:
        df = pd.read_sql_query("SELECT open_time, open, high, low, close FROM candles WHERE symbol = ? AND timeframe = '15m'"
                               " ORDER BY open_time", c, params=(coin,))
    df.index = pd.to_datetime(df.pop("open_time"), unit="ms", utc=True)
    return df


def split_by_htf(tr: pd.DataFrame, source: str = "live", per_pattern: dict | None = None) -> dict:
    """For each HTF: (candle with, candle against, chart with) masks over the trades; fills per_pattern[(tf, name)]."""
    out = {}
    for tf, (_rule, step) in HTF.items():
        cw, ca, chw = (np.zeros(len(tr), bool) for _ in range(3))
        for coin in tr["symbol"].unique():
            close, candle, cbull, cbear = htf_masks(coin, tf, source)
            sel = np.where(tr["symbol"].to_numpy() == coin)[0]
            t = tr["decision"].to_numpy()[sel]
            d = tr["d"].to_numpy()[sel]
            pos = np.searchsorted(close, t, side="right") - 1
            ok = pos >= 1
            bull = np.zeros(len(sel), bool)
            bear = np.zeros(len(sel), bool)
            for name, (pd_, span, m) in candle.items():
                hit = np.zeros(len(sel), bool)
                hit[ok] = m[pos[ok]]
                (bull if pd_ > 0 else bear)[:] |= hit
                if per_pattern is not None:
                    same = hit & (d == pd_)
                    for j in np.where(same)[0]:
                        per_pattern.setdefault((tf, name), []).append(sel[j])
            cw[sel] = np.where(d > 0, bull, bear)
            ca[sel] = np.where(d > 0, bear, bull)
            cb = np.zeros(len(sel), bool)
            cs = np.zeros(len(sel), bool)
            for back in range(2):
                p_ = pos - back
                okb = p_ >= 0
                cb[okb] |= cbull[p_[okb]]
                cs[okb] |= cbear[p_[okb]]
            chw[sel] = np.where(d > 0, cb, cs)
        out[tf] = (cw, ca, chw)
    return out


def show_split(tr: pd.DataFrame, title: str, source: str = "live", patterns: bool = False) -> None:
    r, t = tr["r_net"].to_numpy(), tr["decision"].to_numpy()
    mid = int(np.median(t))
    per = {} if patterns else None
    sp = split_by_htf(tr, source, per)
    print(f"\n   {title}: {len(tr)} trades, {r.mean():+.3f}R a trade  (trades R | first half / second half)")
    for tf, (cw, ca, chw) in sp.items():
        none = ~cw & ~ca
        print(f"      {tf} candle pattern  with    {pa.split_line(r, t, cw & ~ca, mid)}")
        print(f"      {tf} candle pattern  none    {pa.split_line(r, t, none, mid)}")
        print(f"      {tf} chart breakout  with    {pa.split_line(r, t, chw, mid)}")
    if patterns:
        print("      single patterns in the trade's direction on the last HTF candle (30+ trades):")
        for (tf, name), idx in sorted(per.items(), key=lambda kv: -len(kv[1])):
            if len(idx) < 30:
                continue
            m = np.zeros(len(tr), bool)
            m[idx] = True
            print(f"         {tf:3} {name:34} {pa.split_line(r, t, m, mid)}")


def part3() -> None:
    print("\n\n######## 3. HIGHER-TIMEFRAME PATTERNS WITH THE NEW DESIGN, PER COIN ########")
    news = pa.load_trades(pa.REPLAY / "journal-news.db", "v0-e78944")
    btc = pa.load_trades(pa.REPLAY / "journal-long-board.db", "dip15-e78944", symbols=["BTC"])
    show_split(pd.concat([news, btc]).sort_values("decision").reset_index(drop=True), "ALL 4 COINS POOLED", patterns=True)
    for coin in ["XRP", "SOL", "ETH"]:
        show_split(news[news["symbol"] == coin].reset_index(drop=True), f"{coin} (4 years)")
    show_split(btc, "BTC (dip15, 3 years)")
    print("\n\n######## 3b. 5m SIGNALS (v0's 5m trades, 3 years): does a higher-timeframe pattern rescue them? ########")
    v0 = pa.load_trades(pa.REPLAY / "journal-long-board.db", "v0-773ea9")
    v5 = v0[v0["timeframe"] == "5m"].reset_index(drop=True)
    for coin in COINS:
        show_split(v5[v5["symbol"] == coin].reset_index(drop=True), f"{coin} 5m signals")


def main() -> None:
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)  # the live agent comes first
    if "--skip-counts" not in sys.argv:  # the counts are already in data/research/pattern_counts.csv
        conn = sqlite3.connect(f"file:{pt.LONG}?mode=ro", uri=True)
        part2(conn)
        conn.close()
    part3()


if __name__ == "__main__":
    main()
