r"""Tier-A factors compared, alone and together (2026-10-24). Research only.

    .venv\Scripts\python -u research\tools\factor_compare.py > data\research\factor_compare.txt

Plan: research/notes/2026-10-24-patterns-per-coin-plan.md (part 1).
"""
from __future__ import annotations

import importlib.util
import itertools
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


def trades(path: Path, vid: str) -> pd.DataFrame:
    tr = pa.load_trades(path, vid)
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as c:
        exits = dict(c.execute("SELECT id, exit_time FROM trades WHERE variant_id = ?", (vid,)))
    tr["exit_time"] = tr["id"].map(exits)
    tr["r"] = tr["r_net"]
    m = bt.btc_move_12h(tr["decision"].to_numpy())
    d = tr["d"].to_numpy()
    tr["a"] = (tr["quality"] == "A").to_numpy()
    tr["b"] = pa.candidate(tr)
    tr["c"] = e2.flag_chart4h(tr)
    tr["d_btc"] = (np.abs(m) >= 0.02) & (np.sign(m) == d)
    tr["against"] = (np.abs(m) >= 0.02) & (np.sign(m) == -d)
    return tr


NAMES = {"a": "a OI/Trendline", "b": "b 1h/1d candle pattern", "c": "c 4h chart breakout", "d_btc": "d BTC 12h move with"}


def report(tr: pd.DataFrame, label: str, halves: bool) -> None:
    r, t = tr["r"].to_numpy(), tr["decision"].to_numpy()
    mid = pa.SPLIT_MS if halves else int(np.median(t))
    print(f"\n######## {label}: {len(tr)} trades ########")
    print("   each factor: with | without   (trades R | first half / second half)")
    for k, name in NAMES.items():
        f = tr[k].to_numpy()
        print(f"   {name:24} on {f.mean():4.0%}:  with {pa.split_line(r, t, f, mid)}\n{'':37}without {pa.split_line(r, t, ~f, mid)}")
    ag = tr["against"].to_numpy()
    print(f"   {'against BTC 12h move':24} on {ag.mean():4.0%}:  {pa.split_line(r, t, ag, mid)}")
    k = tr[["a", "b", "c", "d_btc"]].sum(axis=1).to_numpy()
    print("   how many factors agree (a, b, c, d):")
    for n, m in (("0", k == 0), ("1", k == 1), ("2", k == 2), ("3+", k >= 3)):
        print(f"      {n:3} {pa.split_line(r, t, m, mid)}")
    print("   the simple account (user's rules, $150, A 3% / B 2%): all" + (" | 2022-24 | 2024-26" if halves else ""))
    combos = [()] + [(x,) for x in NAMES] + list(itertools.combinations(["b", "c", "d_btc"], 2)) + [("b", "c", "d_btc"),
                                                                                                ("a", "b", "c", "d_btc")]
    for combo in combos:
        for skip in (False, True):
            if skip and len(combo) not in (0, 4):
                continue
            a = np.zeros(len(tr), bool)
            for x in combo:
                a |= tr[x].to_numpy()
            x_ = tr.assign(quality=np.where(a, "A", "B"))
            if skip:
                x_ = x_[~tr["against"].to_numpy()]
            runs = [e2.account(x_)]
            if halves:
                runs += [e2.account(x_[x_["entry_time"] < pa.SPLIT_MS]), e2.account(x_[x_["entry_time"] >= pa.SPLIT_MS])]
            name = ("+".join(c.replace("_btc", "") for c in combo) or "none (all 2%)") + (" + skip against BTC" if skip else "")
            print(f"      {name:32} A on {a.mean():4.0%}: " + " | ".join(f"${b:,.0f} ({b / 150 - 1:+.0%}) DD {dd:.1%}" for n, b, dd in runs))


def main() -> None:
    report(trades(pa.REPLAY / "journal-news.db", "v0-e78944"), "4 YEARS, the design, XRP/SOL/ETH", halves=True)
    gate = pa.REPLAY / "journal-gate-2026-06-25.db"
    with sqlite3.connect(f"file:{gate}?mode=ro", uri=True) as c:
        vid = c.execute("SELECT id FROM variants WHERE id LIKE 'design-%'").fetchone()[0]
    report(trades(gate, vid), "TRADINGVIEW DATA since 2026-06-25, the design", halves=False)


if __name__ == "__main__":
    main()
