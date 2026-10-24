r"""BTC and the alts, the 4h chart breakout as a tier-A reason, and the 4h-chart-breakout -> 15m engine (2026-10-23).
Research only.

    .venv\Scripts\python -u research\tools\engine2_check.py > data\research\engine2.txt

A. How closely XRP/SOL/ETH follow BTC, and how the design's trades did on BTC's big down days.
B. A 4h chart breakout in the trade's direction as one more tier-A reason: replication and the demo account.
C. The second engine (4h chart breakout as the bias, entry on the first 15m pullback, the agent's stop rules, 1.5R):
   (1) on 9 coins the agent does not trade (1.5 years), (2) its overlap with the design's trades,
   (3) one account with both: design alone vs design + engine 2 (a simple account at the user's rules, checked against
   the real account replay first).
"""
from __future__ import annotations

import importlib.util
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
pa = pm.pa
OTHER = ROOT / "data" / "research" / "long" / "journal.db"
OTHER_COINS = ["ADA", "AVAX", "BNB", "DOGE", "LINK", "LTC", "NEAR", "SUI", "ZEC"]
TRADED = ["XRP", "SOL", "ETH"]
H4 = 14_400_000
COST, TARGET, SWING, MIN_STOP = 0.0014, 1.5, 10, 0.015
HOLD_MS = 2 * 86_400_000


def ms(index) -> np.ndarray:
    return ((index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy(dtype="int64")


def load15(path: Path, coin: str) -> pd.DataFrame:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as c:
        df = pd.read_sql_query("SELECT open_time, open, high, low, close FROM candles WHERE symbol = ? AND timeframe = '15m'"
                               " ORDER BY open_time", c, params=(coin,))
    df.index = pd.to_datetime(df.pop("open_time"), unit="ms", utc=True)
    return df


def chart_events(df15: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """(close time ms, direction) of 4h chart-pattern breakouts."""
    d4 = df15.resample("4h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    o, h, l, c = (d4[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
    bull, bear = np.zeros(len(c), bool), np.zeros(len(c), bool)
    for name, (d, idx, _s) in list(pm.chart_more(o, h, l, c).items()) + list(pt.chart_patterns(o, h, l, c).items()):
        (bull if d > 0 else bear)[idx] = True
    one = bull ^ bear
    return ms(d4.index)[one] + H4, np.where(bull[one], 1, -1)


def engine2(df15: pd.DataFrame, coin: str, start_ms: int, window: int = 2) -> pd.DataFrame:
    """The engine's trades with entry and exit times."""
    at_list, dirs = chart_events(df15)
    o, h, l, c = (df15[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
    t_open = ms(df15.index)
    step = 900_000
    hold = HOLD_MS // step
    rows = []
    for at, d in zip(at_list, dirs):
        if at < start_ms:
            continue
        i = np.searchsorted(t_open, at)
        end = np.searchsorted(t_open, at + window * H4)
        while i < end and i + hold + 1 < len(c):
            against = c[i] < o[i] if d > 0 else c[i] > o[i]
            if against and i >= SWING:
                entry = o[i + 1]
                stop = l[i - SWING + 1:i + 1].min() if d > 0 else h[i - SWING + 1:i + 1].max()
                risk = d * (entry - stop)
                if risk > MIN_STOP * entry:
                    target = entry + d * TARGET * risk
                    hh, ll = h[i + 1:i + 1 + hold], l[i + 1:i + 1 + hold]
                    sh = (ll <= stop) if d > 0 else (hh >= stop)
                    th = (hh >= target) if d > 0 else (ll <= target)
                    fs = int(sh.argmax()) if sh.any() else hold
                    ft = int(th.argmax()) if th.any() else hold
                    if fs < hold and fs <= ft:
                        r, k = -1.0, fs
                    elif ft < hold:
                        r, k = TARGET, ft
                    else:
                        r, k = d * (c[i + hold] - entry) / risk, hold - 1
                    rows.append((coin, "long" if d > 0 else "short", t_open[i + 1], t_open[i + 1 + k] + step,
                                 r - COST * entry / risk, "B"))
                    break
            i += 1
    return pd.DataFrame(rows, columns=["symbol", "side", "entry_time", "exit_time", "r", "quality"])


def account(trades: pd.DataFrame, a_risk: float = 0.03, b_risk: float = 0.02, start: float = 150.0) -> tuple:
    """A simple account at the user's rules: 12% open-risk budget (a trade is made smaller to fit), max 5 open, max 2 a
    coin, opposite signals skipped, the first position of a coin always allowed. Returns (trades, end, max DD)."""
    bal = peak = start
    dd = 0.0
    open_: list[tuple] = []  # (exit_time, coin, side, risk_usd, r)
    n = 0
    for row in trades.sort_values("entry_time").itertuples(index=False):
        for pos in sorted([p for p in open_ if p[0] <= row.entry_time]):
            bal += pos[3] * pos[4]
            peak = max(peak, bal)
            dd = max(dd, 1 - bal / peak)
        open_ = [p for p in open_ if p[0] > row.entry_time]
        on_coin = [p for p in open_ if p[1] == row.symbol]
        if any(p[2] != row.side for p in on_coin) or len(on_coin) >= 2:
            continue
        if len(open_) >= 5 and on_coin:
            continue
        want = bal * (a_risk if row.quality == "A" else b_risk)
        room = 0.12 * bal - sum(p[3] for p in open_)
        risk = min(want, room)
        if risk < 0.25 * want:
            continue
        open_.append((row.exit_time, row.symbol, row.side, risk, row.r))
        n += 1
    for pos in sorted(open_):
        bal += pos[3] * pos[4]
        peak = max(peak, bal)
        dd = max(dd, 1 - bal / peak)
    return n, bal, dd


def part_a() -> None:
    print("######## A. DO XRP/SOL/ETH FOLLOW BTC? ########")
    d = {coin: pa.candles15(coin)["close"] for coin in ["BTC"] + TRADED}
    closes = pd.DataFrame(d).dropna()
    r1h = closes.resample("1h").last().pct_change().dropna()
    print("   correlation of 1h returns with BTC (4 years): "
          + ", ".join(f"{c} {r1h[c].corr(r1h['BTC']):.2f}" for c in TRADED))
    day = closes.resample("1D").last().pct_change().dropna()
    big = day[day["BTC"] <= -0.03]
    print(f"   days BTC fell 3%+: {len(big)}; the coin also fell that day: "
          + ", ".join(f"{c} {(big[c] < 0).mean():.0%} (average {big[c].mean():+.1%})" for c in TRADED)
          + f"; BTC average {big['BTC'].mean():+.1%}")
    tr = pa.load_trades(pa.REPLAY / "journal-news.db", "v0-e78944")
    tr["day"] = pd.to_datetime(tr["decision"], unit="ms", utc=True).dt.floor("D")
    btc_day = day["BTC"]
    tr["btc_day"] = tr["day"].map(btc_day)
    for label, m in (("BTC fell 3%+ that day", tr["btc_day"] <= -0.03), ("BTC rose 3%+ that day", tr["btc_day"] >= 0.03),
                     ("other days", tr["btc_day"].abs() < 0.03)):
        x = tr[m]
        sh, lo = x[x["side"] == "short"], x[x["side"] == "long"]
        print(f"   design trades on days {label:22}: {len(sh):4d} shorts {sh['r_net'].mean():+.3f}R | {len(lo):4d} longs {lo['r_net'].mean():+.3f}R")


def flag_chart4h(tr: pd.DataFrame) -> np.ndarray:
    """A 4h chart breakout in the trade's direction among the last 2 closed 4h candles at the decision."""
    w = np.zeros(len(tr), bool)
    for coin in tr["symbol"].unique():
        close, dirs = chart_events(pa.candles15(coin))
        sel = np.where(tr["symbol"].to_numpy() == coin)[0]
        t = tr["decision"].to_numpy()[sel]
        d = tr["d"].to_numpy()[sel]
        for k, (tt, dd) in enumerate(zip(t, d)):
            j = np.searchsorted(close, tt, side="right")
            recent = slice(max(0, j - 10), j)
            live = close[recent] > tt - 2 * H4
            if live.any() and dirs[recent][live][-1] == dd:
                w[sel[k]] = True
    return w


def part_b() -> None:
    print("\n######## B. A 4h CHART BREAKOUT IN THE TRADE'S DIRECTION AS ONE MORE TIER-A REASON ########")
    board, gate = pa.REPLAY / "journal-long-board.db", pa.REPLAY / "journal-gate-2026-06-25.db"
    with sqlite3.connect(f"file:{gate}?mode=ro", uri=True) as c:
        gate_id = c.execute("SELECT id FROM variants WHERE id LIKE 'design-%'").fetchone()[0]
    samples = [("4-year design (found here)", pa.REPLAY / "journal-news.db", "v0-e78944", None),
               ("dip15 on BTC (not seen)", board, "dip15-e78944", ["BTC"]),
               ("v0, 4 coins (not seen)", board, "v0-773ea9", None),
               ("trend15, 4 coins (not seen)", board, "trend15-dfc467", None),
               ("design, TradingView data since 06-25", gate, gate_id, None)]
    print("   sample: with the breakout | without (first half / second half)")
    for label, path, vid, syms in samples:
        t = pa.load_trades(path, vid, symbols=syms)
        f = flag_chart4h(t)
        r, tt = t["r_net"].to_numpy(), t["decision"].to_numpy()
        mid = int(np.median(tt))
        print(f"   {label}:\n      with    {pa.split_line(r, tt, f, mid)}\n      without {pa.split_line(r, tt, ~f, mid)}")

    print("\n   The demo account (simple account at the user's rules; the 4-year design trades)")
    tr = pa.load_trades(pa.REPLAY / "journal-news.db", "v0-e78944", taken_only_closed=True)
    with sqlite3.connect(f"file:{pa.REPLAY / 'journal-news.db'}?mode=ro", uri=True) as c:
        exits = dict(c.execute("SELECT id, exit_time FROM trades WHERE variant_id = 'v0-e78944'"))
    tr["exit_time"] = tr["id"].map(exits)
    tr["r"] = tr["r_net"]
    rec_a = (tr["quality"] == "A").to_numpy()
    pat = pa.candidate(tr)
    c4 = flag_chart4h(tr)
    split = pa.SPLIT_MS
    for label, a in (("S0 tier A as recorded", rec_a), ("S1 A or 1h/1d pattern", rec_a | pat),
                     ("S1 + 4h chart breakout", rec_a | pat | c4), ("everyone 2%", np.zeros(len(tr), bool))):
        x = tr.assign(quality=np.where(a, "A", "B"))
        res = [account(x), account(x[x["entry_time"] < split]), account(x[x["entry_time"] >= split])]
        print(f"      {label:26} " + " | ".join(f"{n} tr ${b:,.0f} ({b / 150 - 1:+.0%}) DD {d:.1%}" for n, b, d in res))


def part_c() -> None:
    print("\n######## C. THE SECOND ENGINE: 4h chart breakout -> first 15m pullback, agent stop (>= 1.5%), 1.5R ########")
    start4 = pt.START.value // 1_000_000
    print("   (1) on 9 coins the agent does not trade, 2025-04 to 2026-10:")
    pooled = []
    for coin in OTHER_COINS:
        e = engine2(load15(OTHER, coin), coin, 0)
        pooled.append(e)
        days = (e["entry_time"].max() - e["entry_time"].min()) / 86_400_000 if len(e) else 1
        print(f"      {coin:5} {len(e):4d} trades ({len(e) / max(days, 1):.2f}/day) won {(e['r'] > 0).mean():.0%} {e['r'].mean():+.3f}R")
    allo = pd.concat(pooled)
    mid = int(np.median(allo["entry_time"]))
    h1, h2 = allo[allo["entry_time"] < mid], allo[allo["entry_time"] >= mid]
    print(f"      all 9: {len(allo)} trades, won {(allo['r'] > 0).mean():.0%}, {allo['r'].mean():+.3f}R"
          f" | first half {h1['r'].mean():+.3f}R / second half {h2['r'].mean():+.3f}R")

    print("   (2) overlap with the design's trades (XRP/SOL/ETH, 4 years):")
    e2 = pd.concat([engine2(pa.candles15(c_), c_, start4) for c_ in TRADED]).reset_index(drop=True)
    tr = pa.load_trades(pa.REPLAY / "journal-news.db", "v0-e78944")
    with sqlite3.connect(f"file:{pa.REPLAY / 'journal-news.db'}?mode=ro", uri=True) as c:
        exits = dict(c.execute("SELECT id, exit_time FROM trades WHERE variant_id = 'v0-e78944'"))
    tr["exit_time"] = tr["id"].map(exits)
    near = 0
    for row in e2.itertuples(index=False):
        x = tr[(tr["symbol"] == row.symbol) & (tr["side"] == row.side)]
        if ((x["entry_time"] - row.entry_time).abs() <= H4).any():
            near += 1
    days = (e2["entry_time"].max() - e2["entry_time"].min()) / 86_400_000
    print(f"      engine 2: {len(e2)} trades ({len(e2) / days:.2f}/day), {e2['r'].mean():+.3f}R; within 4 h of a design trade"
          f" on the same coin and side: {near} ({near / len(e2):.0%})")

    print("   (3) one account, the user's rules, $150, 2% each (tier A 3% where the design has it):")
    d1 = tr.assign(r=tr["r_net"], quality=np.where(pa.candidate(tr) | (tr["quality"] == "A").to_numpy(), "A", "B"))
    d1 = d1[["symbol", "side", "entry_time", "exit_time", "r", "quality"]]
    both = pd.concat([d1, e2])
    check = d1.assign(quality=np.where((tr["quality"] == "A").to_numpy(), "A", "B"))
    n, b, dd = account(check)
    print(f"      check against the real replay (S0: +773%, DD 62.7%): simple account {n} tr ${b:,.0f} ({b / 150 - 1:+.0%}) DD {dd:.1%}")
    split = pa.SPLIT_MS
    for label, x in (("design alone (S1 tiers)", d1), ("design + engine 2", both), ("engine 2 alone", e2)):
        res = [account(x), account(x[x["entry_time"] < split]), account(x[x["entry_time"] >= split])]
        days_x = (x["entry_time"].max() - x["entry_time"].min()) / 86_400_000
        print(f"      {label:24} " + " | ".join(f"{n} tr ${b:,.0f} ({b / 150 - 1:+.0%}) DD {d:.1%}" for n, b, d in res)
              + f"   [{res[0][0] / days_x:.2f} trades/day]")


def main() -> None:
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)  # the live agent comes first
    part_a()
    part_b()
    part_c()


if __name__ == "__main__":
    main()
