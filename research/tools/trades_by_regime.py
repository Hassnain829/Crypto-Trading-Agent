r"""How many trades a day the new package takes in quiet, normal and volatile markets (2026-10-24). Research only.

    .venv\Scripts\python -u research\tools\trades_by_regime.py > data\research\trades_by_regime.txt

The design's 4-year trades on XRP/SOL/ETH through the simple account at the user's rules with the revised package
(tier A = OI/Trendline or 4h chart breakout or BTC 12h move with the trade; trades against a 2%+ BTC 12h move skipped).
Days are grouped by BTC's daily range (high-low over open) and by the coins' volume against their own 30-day median.
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


bt = _load("btc_tier", "btc_tier.py")
e2, pa = bt.e2, bt.pa


def executed(trades: pd.DataFrame, a_risk=0.03, b_risk=0.02, start=150.0) -> pd.DataFrame:
    """engine2_check.account, returning the trades the account took."""
    bal = start
    open_: list[tuple] = []
    taken = []
    for row in trades.sort_values("entry_time").itertuples(index=False):
        for pos in sorted([p for p in open_ if p[0] <= row.entry_time]):
            bal += pos[3] * pos[4]
        open_ = [p for p in open_ if p[0] > row.entry_time]
        on_coin = [p for p in open_ if p[1] == row.symbol]
        if any(p[2] != row.side for p in on_coin) or len(on_coin) >= 2 or (len(open_) >= 5 and on_coin):
            continue
        want = bal * (a_risk if row.quality == "A" else b_risk)
        risk = min(want, 0.12 * bal - sum(p[3] for p in open_))
        if risk < 0.25 * want:
            continue
        open_.append((row.exit_time, row.symbol, row.side, risk, row.r))
        taken.append(row)
    return pd.DataFrame(taken)


def daily(coin: str) -> pd.DataFrame:
    with sqlite3.connect(f"file:{pa.LONG}?mode=ro", uri=True) as c:
        df = pd.read_sql_query("SELECT open_time, open, high, low, close, volume FROM candles WHERE symbol = ? AND timeframe = '15m'"
                               " ORDER BY open_time", c, params=(coin,))
    df.index = pd.to_datetime(df.pop("open_time"), unit="ms", utc=True)
    return df.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()


def main() -> None:
    path = pa.REPLAY / "journal-news.db"
    tr = pa.load_trades(path, "v0-e78944")
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as c:
        exits = dict(c.execute("SELECT id, exit_time FROM trades WHERE variant_id = 'v0-e78944'"))
    tr["exit_time"] = tr["id"].map(exits)
    tr["r"] = tr["r_net"]
    m = bt.btc_move_12h(tr["decision"].to_numpy())
    d = tr["d"].to_numpy()
    with_btc = (np.abs(m) >= 0.02) & (np.sign(m) == d)
    against = (np.abs(m) >= 0.02) & (np.sign(m) == -d)
    a = (tr["quality"] == "A").to_numpy() | e2.flag_chart4h(tr) | with_btc
    book = tr.assign(quality=np.where(a, "A", "B"))[~against]
    took = executed(book)
    took["day"] = pd.to_datetime(took["entry_time"], unit="ms", utc=True).dt.floor("D")

    btc = daily("BTC")
    btc["range"] = (btc["high"] - btc["low"]) / btc["open"]
    vol = pd.DataFrame({c_: daily(c_)["volume"] for c_ in ("XRP", "SOL", "ETH")}).dropna()
    rel = (vol / vol.rolling(30).median()).mean(axis=1)  # the 3 coins' volume against their own 30-day median
    days = pd.DataFrame({"range": btc["range"], "rel_vol": rel}).dropna()
    days = days[(days.index >= took["day"].min()) & (days.index <= took["day"].max())]
    per_day = took.groupby("day").size().reindex(days.index, fill_value=0)
    r_day = took.groupby("day")["r"].mean().reindex(days.index)
    total_days = len(days)
    print(f"the revised package: {len(took)} trades in {total_days} days = {len(took) / total_days:.2f} a day, "
          f"{len(took) / total_days * 7:.1f} a week, {len(took) / total_days * 30.4:.0f} a month; {took['r'].mean():+.3f}R a trade;"
          f" 3% (tier A) on {(took['quality'] == 'A').mean():.0%}")
    print(f"days with no trade: {(per_day == 0).mean():.0%}; 1 trade {(per_day == 1).mean():.0%}; 2-3 {per_day.between(2, 3).mean():.0%};"
          f" 4+ {(per_day >= 4).mean():.0%}; the most in one day {per_day.max()}")

    def show(title: str, key: pd.Series, labels: list[str], edges: list[float]) -> None:
        print(f"\n{title}")
        groups = pd.cut(key, edges, labels=labels, include_lowest=True)
        for g in labels:
            sel = groups == g
            n_days = int(sel.sum())
            n = int(per_day[sel].sum())
            rr = took[took["day"].isin(days.index[sel])]["r"]
            print(f"   {g:34} {n_days:5d} days ({n_days / total_days:4.0%}) | {n / max(n_days, 1):.2f} trades a day"
                  f" | no trade on {(per_day[sel] == 0).mean():.0%} of them | {rr.mean() if len(rr) else float('nan'):+.3f}R a trade")

    q = days["range"].quantile([0.25, 0.75, 0.9]).to_list()
    show(f"BY BTC's DAILY RANGE (quiet < {q[0]:.1%}, volatile > {q[1]:.1%}, very volatile > {q[2]:.1%})", days["range"],
         ["quiet (bottom 25%)", "normal (middle 50%)", "volatile (top 25%, not top 10%)", "very volatile (top 10%)"],
         [0, q[0], q[1], q[2], 10])
    show("BY THE COINS' VOLUME (against their own 30-day median)", days["rel_vol"],
         ["low (< 0.8x)", "normal (0.8-1.25x)", "high (1.25-2x)", "very high (> 2x)"], [0, 0.8, 1.25, 2.0, 100])
    recent = days.index >= pd.Timestamp("2026-06-25", tz="UTC")
    print(f"\nlast 4 months (since 2026-06-25): {per_day[recent].mean():.2f} trades a day; BTC daily range median "
          f"{days['range'][recent].median():.1%} vs {days['range'].median():.1%} over 4 years")


if __name__ == "__main__":
    main()
