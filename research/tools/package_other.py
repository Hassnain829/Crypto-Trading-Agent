r"""The tier-A package on the 13-coin replay (2025-04 to 2026-10): does it hold on coins and a window it was not found on?
(2026-10-24) Research only. Needs data/replay/journal-other.db.

    .venv\Scripts\python -u research\tools\package_other.py > data\research\package_other.txt
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


pc = _load("pattern_coins", "pattern_coins.py")
bt = _load("btc_tier", "btc_tier.py")
e2, pa = bt.e2, bt.pa
DB = pa.REPLAY / "journal-other.db"
TRADED = ["XRP", "SOL", "ETH"]


def main() -> None:
    tr = pa.load_trades(DB, "design-e78944")
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as c:
        exits = dict(c.execute("SELECT id, exit_time FROM trades WHERE variant_id = 'design-e78944'"))
    tr["exit_time"] = tr["id"].map(exits)
    tr["r"] = tr["r_net"]
    sp = pc.split_by_htf(tr, "other")
    b = sp["1h"][0] | sp["1d"][0]   # factor b: a candle pattern in the trade's direction on the last 1h or 1d candle
    c4 = sp["4h"][2]                 # factor c: a 4h chart breakout in the trade's direction (last 2 candles)
    m = bt.btc_move_12h(tr["decision"].to_numpy())
    d = tr["d"].to_numpy()
    dbtc = (np.abs(m) >= 0.02) & (np.sign(m) == d)
    against = (np.abs(m) >= 0.02) & (np.sign(m) == -d)
    a = (tr["quality"] == "A").to_numpy()
    r, t = tr["r"].to_numpy(), tr["decision"].to_numpy()
    mid = int(np.median(t))
    for label, sel in (("XRP/SOL/ETH (1.5 years)", tr["symbol"].isin(TRADED).to_numpy()),
                       ("9 other coins (not traded, not used to find the factors)", ~tr["symbol"].isin(TRADED + ["BTC"]).to_numpy())):
        print(f"\n######## {label}: {sel.sum()} trades, {r[sel].mean():+.3f}R ########")
        print("   factor: with | without   (trades R | first half / second half)")
        for name, f in (("a OI", a), ("b 1h/1d candle pattern", b), ("c 4h chart breakout", c4), ("d BTC 12h with", dbtc)):
            print(f"   {name:24} with    {pa.split_line(r, t, sel & f, mid)}\n   {'':24} without {pa.split_line(r, t, sel & ~f, mid)}")
        print(f"   {'against BTC 12h move':24}         {pa.split_line(r, t, sel & against, mid)}")
        k = (a.astype(int) + b + c4 + dbtc)
        for n, mk in (("0 factors", k == 0), ("1 factor", k == 1), ("2+ factors", k >= 2)):
            print(f"   {n:24}         {pa.split_line(r, t, sel & mk, mid)}")
        x = tr[sel]
        print("   simple account (user's rules, $150, A 3% / B 2%; a 13-coin book would differ, this is one group at a time):")
        for name, aa, skip in (("everyone 2%", np.zeros(len(tr), bool), None), ("a only (today)", a, None),
                               ("b", b, None), ("c", c4, None), ("d", dbtc, None), ("a+b+c+d", a | b | c4 | dbtc, None),
                               ("a+b+c+d + skip against BTC", a | b | c4 | dbtc, against), ("skip against BTC only", np.zeros(len(tr), bool), against)):
            y = x.assign(quality=np.where(aa[sel], "A", "B"))
            if skip is not None:
                y = y[~skip[sel]]
            res = [e2.account(y), e2.account(y[y["entry_time"] < mid]), e2.account(y[y["entry_time"] >= mid])]
            print(f"      {name:28} " + " | ".join(f"${bb:,.0f} ({bb / 150 - 1:+.0%}) DD {dd:.1%}" for n, bb, dd in res))


if __name__ == "__main__":
    main()
