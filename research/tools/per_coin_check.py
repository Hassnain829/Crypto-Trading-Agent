r"""Every 2026-10-29 test split by coin (the user asked: were these tests checked on each coin?). Research only.

The tests pooled XRP, SOL and ETH. This tool shows each coin on its own, from the same data:
1. smart targets, runners, early exits and the ML policies (data/research/exit_tp/trades.csv, ml_policies.csv): R a
   trade minus the fixed plan's, per coin, 4 years and since Aug;
2. the regime and volatility factors (regime_test.py): high minus low per coin;
3. tier A against B per coin, and the scoreboard's 3% picks (scoreboard_validate.py) against tier A per coin.

    .venv\Scripts\python -u research\tools\per_coin_check.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COINS = ["XRP", "SOL", "ETH"]
SPLIT = 1727740800000


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rep = _load("exit_tp_report")
rt = _load("regime_test")
sv = _load("scoreboard_validate")


def main() -> None:
    out = []
    say = lambda s="": (print(s, flush=True), out.append(s))
    tr = pd.read_csv(ROOT / "data" / "research" / "exit_tp" / "trades.csv")
    tr["key"] = tr["sample"] + ":" + tr["id"].astype(str)
    for run in ("atr2_lock1", "atr3_lock125", "low4_lock1"):
        tr[f"r_half_{run}"] = 0.5 * (tr["r_plan"] + tr[f"r_run_{run}"])
    ml = pd.read_csv(ROOT / "data" / "research" / "exit_tp" / "ml_policies.csv")
    for pol, g in ml.groupby("policy"):
        tr[f"r_{pol}"] = tr["key"].map(g.set_index("key")["r"])
    four = (tr["sample"] == "4y") & tr["v4"]
    aug = tr["sample"] == "aug"

    say("1. Smart targets, runners, early exits, ML: R a trade minus the fixed plan's, per coin")
    say(f"   {'':40} {'4 years: XRP / SOL / ETH':>27} | {'since Aug: XRP / SOL / ETH':>27} | coins better 4y / Aug")
    line = []
    for c in COINS:
        line.append(f"{tr.loc[four & (tr['symbol'] == c), 'r_plan'].mean():+.3f} ({int((four & (tr['symbol'] == c)).sum())})")
    line_a = [f"{tr.loc[aug & (tr['symbol'] == c), 'r_plan'].mean():+.3f} ({int((aug & (tr['symbol'] == c)).sum())})" for c in COINS]
    say(f"   {'the plan itself (R a trade, trades)':40} {' / '.join(line)} | {' / '.join(line_a)}")
    for label, col in rep.RULES[1:] + rep.ML:
        if f"r_{col}" not in tr:
            continue
        d4, da = [], []
        for c in COINS:
            m4, ma = four & (tr["symbol"] == c), aug & (tr["symbol"] == c)
            d4.append((tr.loc[m4, f"r_{col}"] - tr.loc[m4, "r_plan"]).mean())
            da.append((tr.loc[ma, f"r_{col}"] - tr.loc[ma, "r_plan"]).mean())
        say(f"   {label:40} {' / '.join(f'{x:+.3f}' for x in d4):>27} | {' / '.join(f'{x:+.3f}' for x in da):>27} |"
            f" {sum(x > 0.005 for x in d4)} / {sum(x > 0.005 for x in da)}")

    say("\n2. Regime and volatility factors: high minus low (R a trade) per coin, 4 years (2022-24 / 2024-26) | since Aug")
    t4 = tr[four | aug].reset_index(drop=True)
    t = t4["entry_time"].to_numpy()
    conn = sqlite3.connect(f"file:{(ROOT / 'data/research/outside.db').as_posix()}?mode=ro", uri=True)
    btc1d, btc4h = rt.candles(conn, "BTC", "1d"), rt.candles(conn, "BTC", "4h")
    fac = {}
    for name, df, step, k in (("F1 HMM 2 states daily", btc1d, rt.DAY, 2), ("F2 HMM 3 states daily", btc1d, rt.DAY, 3),
                              ("F3 HMM 2 states 4h", btc4h, rt.H4, 2)):
        close, p, _ = rt.hmm_probs(df, step, k, rt.FIT_END)
        probs = np.column_stack([rt.at(close, p[:, j], t) for j in range(k)])
        fac[name] = probs.argmax(1) if k == 3 else (probs[:, -1] > 0.5).astype(int) * 2
    close, pct = rt.vol_percentile(btc4h, rt.FIT_END)
    fac["F4 BTC volatility percentile"] = np.digitize(rt.at(close, pct, t), [1 / 3, 2 / 3])
    f5, f6 = np.full(len(t4), np.nan), np.full(len(t4), np.nan)
    for c in COINS:
        d4 = rt.candles(conn, c, "4h")
        sel = (t4["symbol"] == c).to_numpy()
        close, pct = rt.vol_percentile(d4, rt.FIT_END)
        f5[sel] = rt.at(close, pct, t[sel])
        close, ratio = rt.vol_ratio(d4)
        f6[sel] = rt.at(close, ratio, t[sel])
    fac["F5 coin volatility percentile"] = np.where(np.isnan(f5), -1, np.digitize(f5, [1 / 3, 2 / 3]))
    fac["F6 coin 24h / 30d"] = np.where(np.isnan(f6), -1, np.digitize(f6, [0.87, 1.44]))
    r = t4["r_plan"].to_numpy()
    w4 = (t4["sample"] == "4y").to_numpy()
    wa = (t4["sample"] == "aug").to_numpy()
    h1, h2 = w4 & (t < SPLIT), w4 & (t >= SPLIT)

    def diff(m: np.ndarray, b: np.ndarray) -> str:
        hi, lo = m & (b == 2), m & (b == 0)
        return f"{r[hi].mean() - r[lo].mean():+.3f}" if hi.sum() >= 3 and lo.sum() >= 3 else "  n/a "

    for name, b in fac.items():
        cells = [f"{c} {diff(w4 & (t4['symbol'] == c).to_numpy(), b)} ({diff(h1 & (t4['symbol'] == c).to_numpy(), b)} /"
                 f" {diff(h2 & (t4['symbol'] == c).to_numpy(), b)}) | {diff(wa & (t4['symbol'] == c).to_numpy(), b)}"
                 for c in COINS]
        say(f"   {name:30} " + "   ".join(cells))

    say("\n3. Tier A against tier B per coin (R a trade, trades), and the scoreboard's 3% picks")
    for c in COINS:
        cells = []
        for w, lab in ((w4, "4 years"), (wa, "since Aug")):
            m = w & (t4["symbol"] == c).to_numpy()
            a, b_ = m & (t4["quality"] == "A").to_numpy(), m & (t4["quality"] == "B").to_numpy()
            cells.append(f"{lab}: A {r[a].mean():+.3f} ({a.sum()}) vs B {r[b_].mean():+.3f} ({b_.sum()})")
        say(f"   {c}: " + " | ".join(cells))
    data = sv.load()
    fourmask = (data["sample"] == "4y").to_numpy()
    board = sv.Board(data[fourmask].reset_index(drop=True), 0.15)
    picks = sv.walk(board, np.ones(fourmask.sum(), bool)).sort_index()
    d = data[fourmask].reset_index(drop=True)
    for c in COINS:
        m = (d["symbol"] == c).to_numpy()
        s2 = m & (picks["s2"].to_numpy() == "A")
        ta = m & (d["quality"] == "A").to_numpy()
        say(f"   {c} 4 years: tier A's trades {d['r_plan'][ta].mean():+.3f} ({ta.sum()}) vs the scoreboard's 3% picks"
            f" {d['r_plan'][s2].mean():+.3f} ({s2.sum()})")
    (ROOT / "data" / "research" / "per_coin_check.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
