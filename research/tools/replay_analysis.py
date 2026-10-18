"""Compare the bar-replay recording with the full-history flags (research, read-only).

For every signal: when did it first appear in the replay (0 = on its own bar)? Did it vanish later? Is it in the
history but never seen live (drawn back afterwards), or seen live but not in the history (removed afterwards)?
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data" / "research" / "indicators_history.db"
H = 3_600_000
WINDOW = 15  # bars recorded at every step


def main() -> None:
    c = sqlite3.connect(DB)
    totals = defaultdict(lambda: defaultdict(int))
    for coin, tf in c.execute("SELECT DISTINCT symbol, tf FROM replay"):
        steps = [r[0] for r in c.execute("SELECT DISTINCT step_bar FROM replay WHERE symbol=? AND tf=? ORDER BY 1", (coin, tf))]
        if len(steps) < 20:
            continue
        step_set = set(steps)
        seen = defaultdict(list)  # (bar, study, plot) -> step bars where present
        for step, bar, study, plot in c.execute("SELECT step_bar, bar_time, study, plot FROM replay WHERE symbol=? AND tf=?",
                                                (coin, tf)):
            seen[(bar, study, plot)].append(step)
        lo, hi = steps[0], steps[-1]
        hist = {(t, study, plot.split(":", 2)[2]) for t, study, plot in c.execute(
            "SELECT time, study, plot FROM flags WHERE symbol=? AND tf=? AND plot LIKE '%alertcondition%' AND time BETWEEN ? AND ?",
            (coin, tf, lo, hi - WINDOW * H))}
        for (bar, study, plot), present in seen.items():
            if bar < lo or bar > hi - WINDOW * H:
                continue  # only bars that were inside the window from their own step to the end
            first = min(present)
            delay = round((first - bar) / H)
            expected = [s for s in steps if first <= s <= bar + (WINDOW - 1) * H]
            vanished = len(present) < len(expected)
            key = study
            totals[key]["signals"] += 1
            totals[key]["on time (0-1 bar)" if delay <= 1 else "drawn late (2+ bars)"] += 1
            if vanished:
                totals[key]["vanished later"] += 1
            if (bar, study, plot) not in hist:
                totals[key]["not in today's history"] += 1
        replay_keys = {(b, s, p) for (b, s, p) in seen}
        for t, study, plot in hist:
            if (t, study, plot) not in replay_keys and t in step_set:
                totals[study]["in history, never seen live"] += 1
        print(f"{coin} {tf}: {len(steps)} replay steps from {lo} to {hi}")
    print()
    cols = ["signals", "on time (0-1 bar)", "drawn late (2+ bars)", "vanished later", "not in today's history",
            "in history, never seen live"]
    print(f"{'indicator':<36}" + "".join(f"{c:>26}" for c in cols))
    for study, t in sorted(totals.items()):
        print(f"{study:<36}" + "".join(f"{t.get(col, 0):>26}" for col in cols))


def warmup_check() -> None:
    """Agreement between replay and history in the first, middle and last third of each replay. Agreement that
    grows over the replay means the differences come from the shorter history the replay starts with (warm-up)."""
    c = sqlite3.connect(DB)
    print("\nAgreement with the full history by replay third (both = signal in replay and in history):")
    for coin, tf in c.execute("SELECT DISTINCT symbol, tf FROM replay").fetchall():
        steps = [r[0] for r in c.execute("SELECT DISTINCT step_bar FROM replay WHERE symbol=? AND tf=? ORDER BY 1", (coin, tf))]
        gaps = sum(1 for a, b in zip(steps, steps[1:]) if b - a != H)
        lo, hi = steps[0], steps[-1] - WINDOW * H
        replay = {(b, s, p) for b, s, p in c.execute(
            "SELECT DISTINCT bar_time, study, plot FROM replay WHERE symbol=? AND tf=? AND bar_time BETWEEN ? AND ?",
            (coin, tf, lo, hi))}
        hist = {(t, s, p.split(":", 2)[2]) for t, s, p in c.execute(
            "SELECT time, study, plot FROM flags WHERE symbol=? AND tf=? AND plot LIKE '%alertcondition%' AND time BETWEEN ? AND ?",
            (coin, tf, lo, hi))}
        thirds = [lo + (hi - lo) * i // 3 for i in range(4)]
        parts = []
        for i in range(3):
            r = {k for k in replay if thirds[i] <= k[0] < thirds[i + 1]}
            h = {k for k in hist if thirds[i] <= k[0] < thirds[i + 1]}
            parts.append(f"{len(r & h)}/{len(r | h)} = {len(r & h) / max(1, len(r | h)):.0%}")
        print(f"  {coin} {tf} ({len(steps)} steps, {gaps} gaps): " + "   ".join(parts))


if __name__ == "__main__":
    main()
    warmup_check()
