r"""Wider stops on 4 years (2026-10-29, the user's question: the price often hit the stop and then the target).

The design's trades (15m + 5m dip 60, XRP/SOL/ETH, 2022-10 to 2026-10, data/replay/journal-news.db v0-e78944) are
re-run on the 1m candles of data/research/long4/journal.db with the stop k times as far from the signal price (as
stop.multiplier does), with the same target price or with the target at 1.5R of the wider stop. Same entries, the
simulator's rules: stop first when both are touched in a minute, no target in the fill minute, maker entry and target,
taker + slippage for stops and the 72 h timeout. Funding is left out. Checked at k = 1 against the stored results.
Trades a wider stop would add (missed at k = 1 because the stop came before the dip entry) are not included.

    .venv\Scripts\python -u research\tools\wide_stop_4y.py
"""
from __future__ import annotations

import sqlite3
import statistics as st
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HOLD = 72 * 3_600_000
MAKER, TAKER, SLIP = 0.0002, 0.0005, 0.0002
VERSIONS = [("now (1x)", 1.0, False), ("1.25x, same target", 1.25, False), ("1.5x, same target", 1.5, False),
            ("2x, same target", 2.0, False), ("1.5x, target 1.5R of it", 1.5, True), ("2x, target 1.5R of it", 2.0, True)]


def run(side: int, fill: float, stop: float, target: float, t: np.ndarray, o: np.ndarray, h: np.ndarray,
        l: np.ndarray, entry_time: int) -> tuple[float, str]:
    inside = t < entry_time + HOLD
    hit_stop = (l <= stop) if side > 0 else (h >= stop)
    hit_target = (h >= target) if side > 0 else (l <= target)
    hit_stop &= inside
    hit_target &= inside
    hit_target[:1] = False  # the limit order filled in the first minute: no provable profit exit inside it
    i_s = int(np.argmax(hit_stop)) if hit_stop.any() else None
    i_t = int(np.argmax(hit_target)) if hit_target.any() else None
    risk = abs(fill - stop)
    if i_s is not None and (i_t is None or i_s <= i_t):
        ref = o[i_s] if (o[i_s] <= stop if side > 0 else o[i_s] >= stop) else stop
        exit_fill, fee, reason = ref * (1 - side * SLIP), TAKER, "stop"
    elif i_t is not None:
        ref, exit_fill, fee, reason = target, target, MAKER, "target"
    else:
        after = np.nonzero(~inside)[0]
        ref = o[after[0]] if len(after) else o[-1]
        exit_fill, fee, reason = ref * (1 - side * SLIP), TAKER, "timeout"
    gross = side * (exit_fill - fill) / risk
    return gross - (fill * MAKER + exit_fill * fee) / risk, reason


def main() -> None:
    import psutil

    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)  # the live agent comes first
    news = sqlite3.connect(f"file:{(ROOT / 'data/replay/journal-news.db').as_posix()}?mode=ro", uri=True)
    long4 = sqlite3.connect(f"file:{(ROOT / 'data/research/long4/journal.db').as_posix()}?mode=ro", uri=True)
    trades = news.execute("SELECT symbol, side, entry_time, entry_ref, stop_initial, target, r_net, funding_r, exit_reason"
                          " FROM trades WHERE variant_id = 'v0-e78944' AND taken = 1 AND status = 'closed'"
                          " ORDER BY entry_time").fetchall()
    t0 = time.monotonic()
    results: dict[str, list[tuple[int, float]]] = {name: [] for name, _, _ in VERSIONS}
    check = []
    for n, (symbol, side_name, entry_time, fill, stop0, target0, r_net, funding_r, reason0) in enumerate(trades):
        side = 1 if side_name == "long" else -1
        c = np.array(long4.execute(
            "SELECT open_time, open, high, low FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time >= ?"
            " AND open_time <= ? ORDER BY open_time", (symbol, entry_time, entry_time + HOLD)).fetchall(), dtype=float)
        if len(c) == 0:
            continue
        t, o, h, l = c[:, 0].astype(np.int64), c[:, 1], c[:, 2], c[:, 3]
        reference = abs(target0 - stop0) / 2.5  # the planned swing risk from the signal price
        order = stop0 + side * reference
        for name, k, scaled in VERSIONS:
            stop = order - side * k * reference
            target = order + side * 1.5 * k * reference if scaled else target0
            if side * (fill - stop) <= 0 or side * (target - fill) <= 0:
                continue
            r, reason = run(side, fill, stop, target, t, o, h, l, entry_time)
            results[name].append((entry_time, r))
            if k == 1.0 and not scaled:
                check.append((r, r_net + (funding_r or 0), reason == reason0))
        if n % 500 == 0:
            print(f"  {n}/{len(trades)} trades, {time.monotonic() - t0:.0f} s", flush=True)
    diffs = [abs(a - b) for a, b, _ in check]
    out = [f"{len(trades)} design trades 2022-10 to 2026-10 (XRP/SOL/ETH, 15m + 5m dip 60); {time.monotonic() - t0:.0f} s",
           f"check at 1x vs the agent's tracker (funding added back): same exit {sum(x for *_, x in check)}/{len(check)},"
           f" mean |dR| {st.mean(diffs):.4f}", ""]
    mid = sorted(e for e, _ in results["now (1x)"])[len(results["now (1x)"]) // 2]
    for name, _, _ in VERSIONS:
        rows = results[name]
        rs = [r for _, r in rows]
        wins, losses = [r for r in rs if r > 0], [-r for r in rs if r < 0]
        years = {}
        for e, r in rows:
            years.setdefault(time.gmtime(e / 1000).tm_year, []).append(r)
        bal = 150.0
        for r in rs:  # 2% of the balance a trade, one after another (overlaps ignored): only to compare the versions
            bal *= 1 + 0.02 * r
        out.append(f"{name:26} {len(rs)} trades, won {len(wins) / len(rs):.0%}, {st.mean(rs):+.3f}R, PF"
                   f" {sum(wins) / sum(losses):.2f}, total {sum(rs):+.0f}R; halves {st.mean([r for e, r in rows if e < mid]):+.3f}"
                   f" / {st.mean([r for e, r in rows if e >= mid]):+.3f}; $150 at 2% in a row: ${bal:,.0f}")
        out.append("    by year: " + ", ".join(f"{y} {st.mean(v):+.3f}R" for y, v in sorted(years.items())))
    text = "\n".join(out)
    print(text)
    (ROOT / "data" / "research" / "wide_stop_4y.txt").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
