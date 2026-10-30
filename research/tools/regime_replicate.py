r"""Replication of two volatility factors on coins they were not found on (2026-10-29). Research only.

regime_test.py found, on XRP/SOL/ETH: F5 (the coin's Kalman-filtered daily volatility percentile) worse when high, the
same way in 2022-24, 2024-26 and since Aug but with t -1.6, and the opposite of the planned direction; F6 (the last 24 h
volatility against the 30 days before) better when high over 4 years but not since Aug. Same definitions here (F6's cut
points from XRP/SOL/ETH 2022-24), on data not used so far (research/notes/2026-10-29-regime-plan.md, last section):
- AVAX: the design's trades 2022-10 to 2026-10 (journal-avax.db); 4h candles built from the research journal's 15m;
  the Kalman filter fitted on the first year;
- BTC: the old baseline v0's trades 2022-10 to 2026-10 (research journal), BTC 4h from outside.db, fitted before 2022-10;
- ten other coins: the design's trades 2025-04 to 2026-10 (journal-other.db), 4h from the 13-coin journal's 15m; a
  180-day percentile with the filter fitted on the first 6 months (only 1.5 years of data).

    .venv\Scripts\python -u research\tools\regime_replicate.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DAY, H4 = 86_400_000, 14_400_000
CUT6 = [0.87, 1.44]  # F6's cut points from XRP/SOL/ETH 2022-24 (regime_test.py)
OTHERS = ["BTC", "ADA", "AVAX", "BNB", "DOGE", "LINK", "LTC", "NEAR", "SUI", "ZEC"]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rt = _load("regime_test")


def ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def four_hour(conn: sqlite3.Connection, coin: str) -> pd.DataFrame:
    """4h candles from complete groups of sixteen 15m candles."""
    df = pd.read_sql_query("SELECT open_time, open, high, low, close FROM candles WHERE symbol = ? AND timeframe = '15m'"
                           " ORDER BY open_time", conn, params=(coin,))
    df["k"] = df["open_time"] // H4 * H4
    g = df.groupby("k").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
                            n=("open", "size"))
    g = g[g["n"] == 16].reset_index().rename(columns={"k": "time"})
    return g[["time", "open", "high", "low", "close"]]


def trades(conn: sqlite3.Connection, variant: str, coins: list[str]) -> pd.DataFrame:
    q = ("SELECT symbol, entry_time, r_net + coalesce(funding_r, 0) AS r FROM trades WHERE variant_id = ? AND taken = 1"
         f" AND status = 'closed' AND symbol IN ({','.join('?' * len(coins))}) ORDER BY entry_time")
    return pd.read_sql_query(q, conn, params=(variant, *coins))


def line(name: str, tr: pd.DataFrame, col: str, cuts: list[float]) -> str:
    v = tr[col].to_numpy(dtype=float)
    b = np.digitize(v, cuts)
    b[np.isnan(v)] = -1
    r = tr["r"].to_numpy()
    cells = [f"{lab} {int((b == j).sum())} {r[b == j].mean():+.3f}" for j, lab in enumerate(("low", "mid", "high"))]
    hi, lo = b == 2, b == 0
    t = rt.clustered_t(r, hi, lo, tr["entry_time"].to_numpy() // DAY)
    return f"   {name:26} {' | '.join(cells)} | high - low {r[hi].mean() - r[lo].mean():+.3f} (t {t:+.1f})"


def factors(tr: pd.DataFrame, d4: dict[str, pd.DataFrame], fit_end: dict[str, int], window: int) -> pd.DataFrame:
    tr = tr.copy()
    for coin, df in d4.items():
        sel = (tr["symbol"] == coin).to_numpy()
        if not sel.any():
            continue
        t = tr.loc[sel, "entry_time"].to_numpy()
        close, pct = rt.vol_percentile(df, fit_end[coin], window)
        tr.loc[sel, "F5"] = rt.at(close, pct, t)
        close, ratio = rt.vol_ratio(df)
        tr.loc[sel, "F6"] = rt.at(close, ratio, t)
    return tr


def main() -> None:
    out = []
    say = lambda s="": (print(s, flush=True), out.append(s))
    say("Replication on coins the factors were not found on. R a trade by third (funding left out); day-clustered t.")
    say("On XRP/SOL/ETH (4 years, regime_test.py): F5 high - low -0.092 (t -1.6); F6 high - low +0.075 (t +1.2).")

    # AVAX, the design, 4 years
    avax = trades(ro(ROOT / "data/replay/journal-avax.db"), "v0-e78944", ["AVAX"])
    d4 = {"AVAX": four_hour(ro(ROOT / "data/research/long4/journal.db"), "AVAX")}
    tr = factors(avax, d4, {"AVAX": int(d4["AVAX"]["time"].iloc[0]) + 365 * DAY}, 365)
    say(f"\nAVAX, the design, {len(tr)} trades 2022-10 to 2026-10 (F5 from 2023-09, after a year of history):")
    say(line("F5 coin vol percentile", tr, "F5", [1 / 3, 2 / 3]))
    say(line("F6 coin 24h / 30d", tr, "F6", CUT6))

    # BTC, the old baseline v0, 4 years
    btc = trades(ro(ROOT / "data/research/long4/journal.db"), "v0-773ea9", ["BTC"])
    btc = btc[btc["entry_time"] >= rt.FIT_END]
    d4 = {"BTC": rt.candles(ro(ROOT / "data/research/outside.db"), "BTC", "4h")}
    tr = factors(btc, d4, {"BTC": rt.FIT_END}, 365)
    say(f"\nBTC, the old baseline v0, {len(tr)} trades 2022-10 to 2026-10:")
    say(line("F5 coin vol percentile", tr, "F5", [1 / 3, 2 / 3]))
    say(line("F6 coin 24h / 30d", tr, "F6", CUT6))

    # ten other coins, the design, 1.5 years
    other = trades(ro(ROOT / "data/replay/journal-other.db"), "design-e78944", OTHERS)
    long13 = ro(ROOT / "data/research/long/journal.db")
    d4 = {c: four_hour(long13, c) for c in OTHERS}
    fit = {c: int(df["time"].iloc[0]) + 182 * DAY for c, df in d4.items()}
    tr = factors(other, d4, fit, 180)
    say(f"\nTen other coins, the design, {len(tr)} trades 2025-04 to 2026-10 (F5: a 180-day percentile, from 2025-10):")
    say(line("F5 coin vol percentile", tr, "F5", [1 / 3, 2 / 3]))
    say(line("F6 coin 24h / 30d", tr, "F6", CUT6))
    for coin in OTHERS:
        g = tr[tr["symbol"] == coin]
        v5, v6 = g["F5"].to_numpy(dtype=float), g["F6"].to_numpy(dtype=float)
        lo5, hi5 = g["r"][v5 < 1 / 3].mean(), g["r"][v5 >= 2 / 3].mean()
        lo6, hi6 = g["r"][v6 < CUT6[0]].mean(), g["r"][v6 >= CUT6[1]].mean()
        say(f"      {coin:5} {len(g):4d} trades: F5 high - low {hi5 - lo5:+.3f} | F6 high - low {hi6 - lo6:+.3f}")
    (ROOT / "data" / "research" / "regime_replicate.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
