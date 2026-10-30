r"""Smart targets and exits for v4, stage 3: the comparison (2026-10-29). Research only.

Reads data/research/exit_tp/trades.csv, checkpoints.csv and touches.csv (exit_tp_data.py) and ml_policies.csv
(exit_tp_ml.py), and compares every version with the fixed plan:
- per trade on v4's 4-year trades (all, 2022-24, 2024-26) with the paired difference and its day-clustered t,
- since 2026-08-01 (the agent's own data),
- in the simple account at the user's rules (engine2_check.account: max 5 open, 2 a coin, opposite skipped, the first
  position of a coin always allowed, 12% open-risk budget, A 3% / B 2%, $150).
The ML versions are out of sample: each 4-year half is judged by the model trained on the other half, and the trades
since Aug by the model trained before it.

    .venv\Scripts\python -u research\tools\exit_tp_report.py
"""
from __future__ import annotations

import calendar
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "data" / "research" / "exit_tp"
SPLIT = 1727740800000  # 2024-10-01
AUG = calendar.timegm((2026, 8, 1, 0, 0, 0)) * 1000
DAY = 86_400_000


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


e2 = _load("engine2_check")

RULES = [("plan (now)", "plan"),
         ("target 1R", "fix1"), ("target 1.25R", "fix1.25"), ("target 1.5R from the fill", "fix1.5"), ("target 2R", "fix2"),
         ("target 2.5R", "fix2.5"), ("target 3R", "fix3"),
         ("S/R 15m: front", "sr_front_15m"), ("S/R 15m: extend", "sr_extend_15m"), ("S/R 15m: both", "sr_both_15m"),
         ("S/R 1h: front", "sr_front_1h"), ("S/R 1h: extend", "sr_extend_1h"), ("S/R 1h: both", "sr_both_1h"),
         ("runner +1R, 2 ATR", "run_atr2_lock1"), ("runner +1.25R, 3 ATR", "run_atr3_lock125"),
         ("runner +1R, last 4 candles", "run_low4_lock1"),
         ("half runner +1R, 2 ATR", "half_atr2_lock1"), ("half runner +1.25R, 3 ATR", "half_atr3_lock125"),
         ("half runner +1R, last 4 candles", "half_low4_lock1"),
         ("exit: Q-Trend against", "ex_qt_against"), ("exit: Q-Trend against, in a loss", "ex_qt_against_loss"),
         ("exit: no progress at 2 h", "ex_noprog_2h"), ("exit: no progress at 4 h", "ex_noprog_4h"),
         ("exit: no progress at 8 h", "ex_noprog_8h"), ("exit: BTC 1% against, in a loss", "ex_btc_against"),
         ("exit: Q-Trend + Klinger against, -0.3R", "ex_qt_kl_against"), ("exit: -0.5R and falling", "ex_fast_to_stop")]
ML = [("ML exit (pred < 0)", "ml_exit_0"), ("ML exit (pred < -0.1R)", "ml_exit_0.1"),
      ("ML runner +1R, 2 ATR", "ml_run_atr2_lock1"), ("ML runner +1.25R, 3 ATR", "ml_run_atr3_lock125"),
      ("ML runner +1R, last 4 candles", "ml_run_low4_lock1"), ("ML target 1R..3R", "ml_target")]


def clustered_t(diff: np.ndarray, day: np.ndarray) -> float:
    """t of the mean difference with the trades of one day as one cluster."""
    mean = diff.mean()
    sums = pd.Series(diff - mean).groupby(day).sum().to_numpy()
    se = np.sqrt((sums ** 2).sum()) / len(diff)
    return mean / se if se > 0 else 0.0


def account(df: pd.DataFrame, r: pd.Series, x: pd.Series) -> str:
    a = pd.DataFrame({"symbol": df["symbol"], "side": df["side"], "entry_time": df["entry_time"], "exit_time": x, "r": r,
                      "quality": df["quality"]})
    _, bal, dd = e2.account(a)
    return f"${bal:,.0f} DD {dd:.0%}"


def main() -> None:
    tr = pd.read_csv(OUT / "trades.csv")
    tr["key"] = tr["sample"] + ":" + tr["id"].astype(str)
    tr = tr.set_index("key")
    for run in ("atr2_lock1", "atr3_lock125", "low4_lock1"):
        tr[f"r_half_{run}"] = 0.5 * (tr["r_plan"] + tr[f"r_run_{run}"])
        tr[f"x_half_{run}"] = tr[f"x_run_{run}"]
    ml_path = OUT / "ml_policies.csv"
    if ml_path.exists():
        ml = pd.read_csv(ml_path)
        for pol, g in ml.groupby("policy"):
            g = g.set_index("key")
            tr[f"r_{pol}"], tr[f"x_{pol}"] = g["r"], g["x"]
    four = tr[(tr["sample"] == "4y") & tr["v4"]]
    aug = tr[tr["sample"] == "aug"]
    h1, h2 = four[four["entry_time"] < SPLIT], four[four["entry_time"] >= SPLIT]
    out = [f"v4 trades: 4 years {len(four)} (2022-24 {len(h1)}, 2024-26 {len(h2)}), since 2026-08-01 {len(aug)}",
           "R a trade after costs, funding left out | the paired difference to the plan on 4 years (day-clustered t) |"
           " the account at the user's rules from $150: 4 years | 2022-24 | 2024-26 | since Aug", ""]
    head = f"{'version':40} {'4y':>7} {'22-24':>7} {'24-26':>7} {'diff':>7} {'t':>5} {'Aug':>7} {'diff':>7}   account"
    out.append(head)
    for label, col in RULES + [m for m in ML if f"r_{m[1]}" in tr]:
        r4, ra = four[f"r_{col}"], aug[f"r_{col}"]
        if r4.isna().any() or ra.isna().any():
            label += " (some trades missing)"
        diff = (r4 - four["r_plan"]).to_numpy()
        t = clustered_t(diff, (four["entry_time"] // DAY).to_numpy())
        accts = " | ".join(account(df, df[f"r_{col}"], df[f"x_{col}"]) for df in (four, h1, h2, aug))
        out.append(f"{label:40} {r4.mean():+7.3f} {h1[f'r_{col}'].mean():+7.3f} {h2[f'r_{col}'].mean():+7.3f}"
                   f" {diff.mean():+7.3f} {t:+5.1f} {ra.mean():+7.3f} {(ra - aug['r_plan']).mean():+7.3f}   {accts}")
        if label.startswith("plan"):
            out.append("")
    out += ["", "How the stopped and the winning trades looked early on (v4, 4 years; the first 15m close at or after the hour):"]
    cp = pd.read_csv(OUT / "checkpoints.csv")
    cp["key"] = cp["sample"] + ":" + cp["id"].astype(str)
    cp = cp[cp["key"].isin(four.index)].join(four[["why_plan", "r_plan"]], on="key")
    for hours in (1, 2, 4, 8):
        at = cp[cp["el"] >= hours].groupby("key").head(1)
        line = [f"   after {hours} h ({len(at)} trades still open):"]
        for lo, hi, name in ((-9, -0.5, "at -0.5R or worse"), (-0.5, 0, "-0.5R..0"), (0, 0.5, "0..+0.5R"), (0.5, 9, "+0.5R or better")):
            g = at[(at["r_now"] > lo) & (at["r_now"] <= hi)]
            if len(g):
                line.append(f"{name}: {len(g)}, ended at the target {(g['why_plan'] == 'target').mean():.0%}, stop"
                            f" {(g['why_plan'] == 'stop').mean():.0%}, final {g['r_plan'].mean():+.2f}R vs exit now {g['r_exit'].mean():+.2f}R")
        out.append("\n      ".join(line))
    to = pd.read_csv(OUT / "touches.csv")
    to["key"] = to["sample"] + ":" + to["id"].astype(str)
    if "after24" in to:
        out += ["", "After the target touch (v4, 4 years | since Aug): how far the price went on in the trade's direction"]
        for name, g in (("4 years", to[to["key"].isin(four.index)]), ("since Aug", to[to["key"].isin(aug.index)])):
            out.append(f"   {name}: {len(g)} touches; within 24 h it reached 2R {(g['after24'] >= 2).mean():.0%}, 2.5R"
                       f" {(g['after24'] >= 2.5).mean():.0%}, 3R {(g['after24'] >= 3).mean():.0%}; before falling back to +1R it"
                       f" reached 2R {(g['before1'] >= 2).mean():.0%}, 3R {(g['before1'] >= 3).mean():.0%}; back to +1R within 24 h"
                       f" {(g['back1_24'] > 0).mean():.0%}")
    text = "\n".join(out)
    print(text)
    (ROOT / "data" / "research" / "exit_tp_report.txt").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
