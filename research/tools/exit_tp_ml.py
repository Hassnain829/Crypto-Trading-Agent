r"""Smart targets and exits for v4, stage 2: the ML models (2026-10-29). Research only.

Needs scikit-learn, which the agent's venv does not have and must not get: run it with a separate venv
(python -m venv <dir>; <dir>\Scripts\pip install numpy pandas scikit-learn). Input: data/research/exit_tp/*.csv from
exit_tp_data.py. Output: data/research/exit_tp/ml_policies.csv (each policy's result for every test trade, read by
exit_tp_report.py) and the diagnostics printed here.

Three gradient-boosting models, settings fixed before the results (research/notes/2026-10-29-exits-plan.md):
- exit: at every 15m close while a trade is open, predict (hold to the plan) - (exit now); exit at the first close where
  the prediction is below 0 (or below -0.1R).
- runner: at the target touch, predict (runner) - (take the target) for each runner; run when it is above 0.
- target: at the fill, predict (target k) - (the plan) for the fixed targets 1R to 3R; take the best one when above 0.
Out of sample only: the 2024-26 trades are judged by a model trained on 2022-24 and the other way round (so the 4 years
are covered by cross-fitting), and the trades since 2026-08-01 (the agent's own data) by a model trained on the 4-year
trades that started before 2026-07-29.

    <ml venv>\Scripts\python -u research\tools\exit_tp_ml.py
"""
from __future__ import annotations

import calendar
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "research" / "exit_tp"
SPLIT = 1727740800000  # 2024-10-01
AUG = calendar.timegm((2026, 8, 1, 0, 0, 0)) * 1000
DAY = 86_400_000
STATIC = ["t_r", "stop_pct", "long", "q_a"]
CP = ["el", "r_now", "mfe", "mae", "atr_r", "volr", "qt", "kl", "ret1h", "ret4h", "btc_since", "btc1h", "btc4h", "coin_since"]
TOUCH = ["el", "speed1h", "mae", "atr_r", "volr", "qt", "kl", "ret1h", "ret4h", "btc_since", "btc1h", "btc4h", "next_15m",
         "next_1h"]
ENTRY = ["e_atr_r", "e_volr", "e_qt", "e_kl", "e_ret1h", "e_ret4h", "e_btc1h", "e_btc4h", "e_btc12h", "e_lvl_15m", "e_lvl_1h",
         "e_n3_15m", "e_n3_1h"]
FIXED = ["1", "1.25", "1.5", "2", "2.5", "3"]
RUNNERS = ["atr2_lock1", "atr3_lock125", "low4_lock1"]


def gbm(min_leaf: int, iters: int) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(learning_rate=0.05, max_iter=iters, max_leaf_nodes=15, min_samples_leaf=min_leaf,
                                         l2_regularization=1.0, random_state=0)


def splits(tr: pd.DataFrame) -> dict[str, tuple[pd.Series, pd.Series]]:
    four, t = tr["sample"] == "4y", tr["entry_time"]
    return {"H1->H2": (four & (t < SPLIT), four & (t >= SPLIT) & tr["v4"]),
            "H2->H1": (four & (t >= SPLIT), four & (t < SPLIT) & tr["v4"]),
            "preAug->Aug": (four & (t < AUG - 3 * DAY), tr["sample"] == "aug")}


def deciles(pred: np.ndarray, y: np.ndarray) -> str:
    q = np.quantile(pred, np.linspace(0, 1, 6))
    parts = []
    for a, b in zip(q[:-1], q[1:]):
        m = (pred >= a) & (pred <= b)
        parts.append(f"pred {a:+.2f}..{b:+.2f}: real {y[m].mean():+.3f}")
    return "; ".join(parts)


def main() -> None:
    tr = pd.read_csv(OUT / "trades.csv")
    cp = pd.read_csv(OUT / "checkpoints.csv")
    to = pd.read_csv(OUT / "touches.csv")
    for df in (tr, cp, to):
        df["key"] = df["sample"] + ":" + df["id"].astype(str)
    st = tr.set_index("key")[STATIC + ["r_plan", "x_plan", "entry_time"]]
    cp = cp.join(st[STATIC + ["r_plan"]], on="key").sort_values(["key", "tau"]).reset_index(drop=True)
    to = to.join(st[STATIC], on="key")
    cp["y"] = cp["r_plan"] - cp["r_exit"]
    rows = []  # (key, policy, r, x)
    print(f"{len(tr)} trades, {len(cp)} checkpoints, {len(to)} target touches")

    for name, (train, test) in splits(tr).items():
        k_train, k_test = set(tr.loc[train, "key"]), set(tr.loc[test, "key"])
        test_tr = tr[test].set_index("key")
        print(f"\n==== {name}: train {len(k_train)} trades, test {len(k_test)} trades ====")

        # 1. the exit model
        a, b = cp[cp["key"].isin(k_train)], cp[cp["key"].isin(k_test)]
        model = gbm(200, 300).fit(a[CP + STATIC], a["y"])
        pred = model.predict(b[CP + STATIC])
        print(f"exit model: {len(a)} train / {len(b)} test checkpoints; test R2 {model.score(b[CP + STATIC], b['y']):+.4f};"
              f" mean hold-minus-exit {b['y'].mean():+.3f}R")
        print("   " + deciles(pred, b["y"].to_numpy()))
        if name == "H1->H2":
            sub = b.sample(min(len(b), 20000), random_state=0)
            imp = permutation_importance(model, sub[CP + STATIC], sub["y"], n_repeats=3, random_state=0)
            order = np.argsort(-imp.importances_mean)
            print("   importance (R2 lost): " + ", ".join(f"{(CP + STATIC)[i]} {imp.importances_mean[i]:+.4f}" for i in order[:8]))
        for theta in (0.0, 0.1):
            fire = b.assign(fire=pred < -theta)
            first = fire[fire["fire"]].groupby("key").head(1).set_index("key")
            r = test_tr["r_plan"].copy()
            x = test_tr["x_plan"].copy()
            hit = first.index.intersection(r.index)
            r[hit], x[hit] = first.loc[hit, "r_exit"], first.loc[hit, "x_exit"]
            rows += [(k, f"ml_exit_{theta:g}", r[k], x[k]) for k in r.index]
            print(f"   exit when pred < {-theta:+.1f}: {len(hit)} of {len(r)} trades exit early; {r.mean():+.3f}R vs plan"
                  f" {test_tr['r_plan'].mean():+.3f}R")

        # 2. the runner model
        a, b = to[to["key"].isin(k_train)], to[to["key"].isin(k_test)]
        for run in RUNNERS:
            ya, yb = a[f"r_{run}"] - a["r_take"], b[f"r_{run}"] - b["r_take"]
            model = gbm(40, 150).fit(a[TOUCH + STATIC], ya)
            pred = model.predict(b[TOUCH + STATIC])
            go = pred > 0
            r = test_tr["r_plan"].copy()
            x = test_tr["x_plan"].copy()
            keys = b["key"].to_numpy()[go]
            r[keys], x[keys] = b[f"r_{run}"].to_numpy()[go], b[f"x_{run}"].to_numpy()[go]
            rows += [(k, f"ml_run_{run}", r[k], x[k]) for k in r.index]
            print(f"runner {run}: {len(a)} train / {len(b)} test touches; always run {yb.mean():+.3f}R a touch, model runs"
                  f" {go.mean():.0%} for {yb[go].mean() if go.any() else 0:+.3f}R (skipped {yb[~go].mean() if (~go).any() else 0:+.3f}R);"
                  f" hindsight best {np.maximum(yb, 0).mean():+.3f}R; trades {r.mean():+.3f}R vs plan {test_tr['r_plan'].mean():+.3f}R")

        # 3. the target model
        a, b = tr[train], tr[test]
        preds = np.column_stack([gbm(60, 200).fit(a[ENTRY + STATIC], a[f"r_fix{k}"] - a["r_plan"]).predict(b[ENTRY + STATIC])
                                 for k in FIXED])
        best = preds.argmax(axis=1)
        use = preds.max(axis=1) > 0
        real = np.column_stack([b[f"r_fix{k}"] for k in FIXED])
        xs = np.column_stack([b[f"x_fix{k}"] for k in FIXED])
        r = np.where(use, real[np.arange(len(b)), best], b["r_plan"])
        x = np.where(use, xs[np.arange(len(b)), best], b["x_plan"])
        rows += list(zip(b["key"], ["ml_target"] * len(b), r, x))
        chosen = pd.Series(np.where(use, np.array(FIXED, dtype=object)[best], "plan")).value_counts(normalize=True)
        print(f"target model: picks " + ", ".join(f"{k} {v:.0%}" for k, v in chosen.items()) +
              f"; trades {r.mean():+.3f}R vs plan {b['r_plan'].mean():+.3f}R; hindsight best"
              f" {np.maximum(real.max(axis=1), b['r_plan']).mean():+.3f}R")

    pd.DataFrame(rows, columns=["key", "policy", "r", "x"]).to_csv(OUT / "ml_policies.csv", index=False)
    print(f"\nwrote {len(rows)} policy rows")


if __name__ == "__main__":
    main()
