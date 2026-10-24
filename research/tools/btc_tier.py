r"""BTC's last-12-hour move as a tier-A reason, and skipping trades against it (2026-10-23). Research only.

    .venv\Scripts\python -u research\tools\btc_tier.py > data\research\btc_tier.txt

Fixed before looking: BTC moved 2%+ over the 12 h before the decision. In the trade's direction = tier A (3%);
against it = (variant) skip. Simple account at the user's rules (engine2_check.account), the design's 4-year trades.
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


e2 = _load("engine2_check", "engine2_check.py")
pa = e2.pa


def btc_move_12h(t: np.ndarray) -> np.ndarray:
    btc = pa.candles15("BTC")
    t_open = ((btc.index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy(dtype="int64")
    close = btc["close"].to_numpy(dtype=float)
    at = lambda ms: close[np.clip(np.searchsorted(t_open + 900_000, ms, side="right") - 1, 0, len(close) - 1)]
    return at(t) / at(t - 12 * 3_600_000) - 1


def main() -> None:
    path = pa.REPLAY / "journal-news.db"
    tr = pa.load_trades(path, "v0-e78944")
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as c:
        exits = dict(c.execute("SELECT id, exit_time FROM trades WHERE variant_id = 'v0-e78944'"))
    tr["exit_time"] = tr["id"].map(exits)
    tr["r"] = tr["r_net"]
    m = btc_move_12h(tr["decision"].to_numpy())
    d = tr["d"].to_numpy()
    with_btc = (np.abs(m) >= 0.02) & (np.sign(m) == d)
    against = (np.abs(m) >= 0.02) & (np.sign(m) == -d)
    rec_a = (tr["quality"] == "A").to_numpy()
    pat, c4 = pa.candidate(tr), e2.flag_chart4h(tr)
    split = pa.SPLIT_MS
    print(f"design trades {len(tr)}; with a 2%+ BTC 12h move {with_btc.sum()} ({with_btc.mean():.0%}), against {against.sum()} ({against.mean():.0%})")
    print("scheme: all | 2022-24 | 2024-26   (simple account, user's rules, $150, A 3% / B 2%)")
    schemes = [("S1 A or 1h/1d pattern", rec_a | pat, None),
               ("+ 4h chart breakout", rec_a | pat | c4, None),
               ("+ BTC 12h move with the trade", rec_a | pat | c4 | with_btc, None),
               ("  and skip trades against BTC", rec_a | pat | c4 | with_btc, against),
               ("everyone 2%", np.zeros(len(tr), bool), None)]
    for label, a, skip in schemes:
        x = tr.assign(quality=np.where(a, "A", "B"))
        if skip is not None:
            x = x[~skip]
        res = [e2.account(x), e2.account(x[x["entry_time"] < split]), e2.account(x[x["entry_time"] >= split])]
        print(f"   {label:32} " + " | ".join(f"{n} tr ${b:,.0f} ({b / 150 - 1:+.0%}) DD {dd:.1%}" for n, b, dd in res)
              + f"   [A on {a.mean():.0%}]")


if __name__ == "__main__":
    main()
