r"""The user's question of 2026-10-29: what if both the stop and the position are made a little bigger?

A wider stop with the same % risk makes the position smaller, so every win shrinks (stop_dip_replay.py). Keeping the
position (or making it bigger) with a wider stop means risking more % a trade. The fair comparison is the same %
risk with today's stop. Two samples:

A. Since 2026-08-01 with the agent's engine and account: the replay journal of stop_dip_replay.py (v4 and the 1.25x /
   1.5x stop versions), live_preview with the demo's rules (max 5, 2 a coin, opposite skipped, 12% open-risk budget)
   at different risks (B / A).
B. 4 years (the design's 3,263 trades, 2022-10 to 2026-10) on 1m candles as in wide_stop_4y.py, then the simple
   account of engine2_check.py (the user's rules, checked against the real account replay), flat risk.

    .venv\Scripts\python -u research\tools\stop_size_test.py
"""
from __future__ import annotations

import calendar
import importlib.util
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
START = calendar.timegm((2026, 8, 1, 0, 0, 0)) * 1000
SPLIT = 1727740800000  # 2024-10-01
HOLD = 72 * 3_600_000


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ws = _load("wide_stop_4y")
e2 = _load("engine2_check")

# (label, stop multiplier, risk B, risk A): the position is risk / stop distance
CASES = [("now: stop 1x, risk 2% / A 3%", 1.0, 0.02, 0.03),
         ("stop 1.25x, position smaller (2% / 3%)", 1.25, 0.02, 0.03),
         ("stop 1.25x, position as now (2.5% / 3.75%)", 1.25, 0.025, 0.0375),
         ("stop 1x, risk 2.5% / 3.75% (same risk)", 1.0, 0.025, 0.0375),
         ("stop 1.25x, position +25% (3.1% / 4.7%)", 1.25, 0.03125, 0.046875),
         ("stop 1x, risk 3.1% / 4.7% (same risk)", 1.0, 0.03125, 0.046875),
         ("stop 1.5x, position as now (3% / 4.5%)", 1.5, 0.03, 0.045),
         ("stop 1x, risk 3% / 4.5% (same risk)", 1.0, 0.03, 0.045)]


def part_a() -> None:
    from tradeagent.account.preview import live_preview
    from tradeagent.config import load_settings

    settings = load_settings(ROOT)
    db = sqlite3.connect(ROOT / "data" / "replay" / "journal-stopdip-2026-08-01.db")
    db.row_factory = sqlite3.Row
    ids = {1.0: "v0-d1d9b2", 1.25: "sl_x125-64fe1c", 1.5: "sl_x150-e02020"}
    print("A. Since 2026-08-01, the agent's engine and account (demo rules, $150):")
    for label, k, b, a in CASES:
        rules = settings.paper_account.model_copy(update={"risk_per_trade": b, "risk_tier_a": a})
        p = live_preview(db, settings, rules=rules, since=START, variant_id=ids[k])
        print(f"   {label:44} {p['taken']:3d} trades, ${p['balance']:7.2f} ({p['return_pct']:+6.1f}%), DD {p['max_drawdown']:5.1%}")
    db.close()


def exit_time(side: int, stop: float, target: float, t: np.ndarray, h: np.ndarray, l: np.ndarray, entry_time: int) -> int:
    """When wide_stop_4y.run closes the trade: the first stop or target minute (no target in the fill minute), or 72 h."""
    inside = t < entry_time + HOLD
    hit_stop = ((l <= stop) if side > 0 else (h >= stop)) & inside
    hit_target = ((h >= target) if side > 0 else (l <= target)) & inside
    hit_target[:1] = False
    first = [int(np.argmax(x)) for x in (hit_stop, hit_target) if x.any()]
    return int(t[min(first)]) + 60_000 if first else entry_time + HOLD


def part_b() -> None:
    fc = _load("factor_compare")
    path = ROOT / "data" / "replay" / "journal-news.db"
    tr = fc.trades(path, "v0-e78944")  # the design's trades with the tier-A reasons and the BTC skip flag
    tr = tr[~tr["against"].to_numpy()].reset_index(drop=True)  # v4 skips trades against a 2%+ BTC 12 h move
    quality = dict(zip(tr["id"], np.where(tr["a"] | tr["c"] | tr["d_btc"], "A", "B")))
    news = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    long4 = sqlite3.connect(f"file:{(ROOT / 'data/research/long4/journal.db').as_posix()}?mode=ro", uri=True)
    trades = news.execute("SELECT id, symbol, side, entry_time, entry_ref, stop_initial, target FROM trades"
                          " WHERE variant_id = 'v0-e78944' AND taken = 1 AND status = 'closed' ORDER BY entry_time").fetchall()
    rows = {1.0: [], 1.25: [], 1.5: []}
    for tid, symbol, side_name, entry_time, fill, stop0, target0 in trades:
        if tid not in quality:
            continue
        side = 1 if side_name == "long" else -1
        c = np.array(long4.execute(
            "SELECT open_time, open, high, low FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time >= ?"
            " AND open_time <= ? ORDER BY open_time", (symbol, entry_time, entry_time + HOLD)).fetchall(), dtype=float)
        if len(c) == 0:
            continue
        t, o, h, l = c[:, 0].astype(np.int64), c[:, 1], c[:, 2], c[:, 3]
        reference = abs(target0 - stop0) / 2.5
        order = stop0 + side * reference
        for k in rows:
            stop = order - side * k * reference
            if side * (fill - stop) <= 0:
                continue
            r, _reason = ws.run(side, fill, stop, target0, t, o, h, l, entry_time)
            rows[k].append((symbol, side_name, entry_time, exit_time(side, stop, target0, t, h, l, entry_time), r,
                            quality[tid]))
    a_share = np.mean([q == "A" for q in quality.values()])
    print(f"\nB. 4 years, v4 on the design's trades ({len(rows[1.0])} after the BTC skip, quality A {a_share:.0%}) on 1m"
          " candles, the simple account (user's rules, $150):  all | 2022-24 | 2024-26")
    for label, k, b, a in CASES:
        df = pd.DataFrame(rows[k], columns=["symbol", "side", "entry_time", "exit_time", "r", "quality"])
        runs = [e2.account(df, a, b), e2.account(df[df["entry_time"] < SPLIT], a, b), e2.account(df[df["entry_time"] >= SPLIT], a, b)]
        print(f"   {label:44} " + " | ".join(f"${bal:,.0f} ({bal / 150 - 1:+.0%}) DD {dd:.0%}" for n, bal, dd in runs))


def main() -> None:
    import psutil

    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    t0 = time.monotonic()
    part_a()
    part_b()
    print(f"\n{time.monotonic() - t0:.0f} s")


if __name__ == "__main__":
    main()
