r"""The new design on 13 coins (1.5 years) with the higher-timeframe patterns and BTC's move, per coin (2026-10-24).
Research only. Needs data/replay/journal-other.db from research/tools/replay_other.py.

    .venv\Scripts\python -u research\tools\other_coins.py > data\research\other_coins.txt

Plan: research/notes/2026-10-24-patterns-per-coin-plan.md (part 4).
"""
from __future__ import annotations

import importlib.util
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


pc = _load("pattern_coins", "pattern_coins.py")
bt = _load("btc_tier", "btc_tier.py")
pa = pc.pa
OTHER_DB = pa.REPLAY / "journal-other.db"
TRADED = ["XRP", "SOL", "ETH"]


def main() -> None:
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    tr = pa.load_trades(OTHER_DB, "design-e78944")
    m = bt.btc_move_12h(tr["decision"].to_numpy())
    d = tr["d"].to_numpy()
    tr["with_btc"] = (np.abs(m) >= 0.02) & (np.sign(m) == d)
    tr["against_btc"] = (np.abs(m) >= 0.02) & (np.sign(m) == -d)
    days = (tr["decision"].max() - tr["decision"].min()) / 86_400_000
    mid = int(np.median(tr["decision"]))
    print("######## 4. THE NEW DESIGN ON 13 COINS (2025-04 to 2026-10, the agent's engine, Python-copy indicators) ########")
    print("   coin: trades (a day), won, R a trade | first half / second half | with BTC 12h move | against it")
    for coin in sorted(tr["symbol"].unique(), key=lambda c_: (c_ not in TRADED, c_)):
        x = tr[tr["symbol"] == coin]
        r, t = x["r_net"].to_numpy(), x["decision"].to_numpy()
        h1, h2 = r[t < mid], r[t >= mid]
        w, a = x["with_btc"].to_numpy(), x["against_btc"].to_numpy()
        f = lambda v: f"{v.mean():+.3f}" if len(v) else "  -  "
        tag = " (traded now)" if coin in TRADED else (" (reference)" if coin == "BTC" else "")
        print(f"   {coin:5}{tag:13} {len(x):4d} ({len(x) / days:.2f}/day) won {(r > 0).mean():.0%} {r.mean():+.3f}R | {f(h1)} / {f(h2)}"
              f" | BTC with {f(r[w])} ({w.sum()}) | against {f(r[a])} ({a.sum()})")
    others = tr[~tr["symbol"].isin(TRADED + ["BTC"])].reset_index(drop=True)
    pc.show_split(others, "THE 9 OTHER COINS POOLED", source="other", patterns=True)
    pc.show_split(tr[tr["symbol"].isin(TRADED)].reset_index(drop=True), "XRP/SOL/ETH on the same 1.5 years", source="other")
    for coin in sorted(others["symbol"].unique()):
        pc.show_split(others[others["symbol"] == coin].reset_index(drop=True), coin, source="other")


if __name__ == "__main__":
    main()
