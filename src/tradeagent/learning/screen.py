"""History screen: replay the stored signals with the baseline and the proposed rules, on a copy of the journal.

A proposal goes on to the forward test only if it beats the baseline over the whole history (the same rules as
the forward judge, see settings `learning`) and is not worse in either half. The halves hold the same number of
baseline trades (5m snapshots start later than 15m ones, so equal time halves would leave 5m out of the first). The real journal is only read; the copy is
data/replay/journal-screen.db.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from tradeagent.config import Settings
from tradeagent.learning import experiments as ex
from tradeagent.setups.config import BASELINE_NAME, SetupParams, Variant, register_variants
from tradeagent.setups.engine import SetupEngine
from tradeagent.sim.tracker import Tracker

MIN_HALF_TRADES = 15  # fewer challenger trades in a half of the history: too few to judge


def _entry_times(conn: sqlite3.Connection, variant_id: str, coins: list[str]) -> list[int]:
    return [r[0] for r in conn.execute(
        f"SELECT entry_time FROM trades WHERE book = 'exploration' AND variant_id = ? AND taken = 1 AND status = 'closed'"
        f" AND symbol IN ({','.join('?' * len(coins))}) ORDER BY entry_time", (variant_id, *coins))]


def judge(stats: dict[str, Any], settings: Settings) -> tuple[bool, str]:
    """stats = {"all": {...}, "halves": [{...}, {...}]}, each with "challenger" and "baseline" summaries."""
    why = []
    won, reasons = ex.beats(stats["all"]["challenger"], stats["all"]["baseline"], settings)
    why += reasons
    for i, half in enumerate(stats["halves"], 1):
        ch, base = half["challenger"], half["baseline"]
        if ch["trades"] < MIN_HALF_TRADES:
            why.append(f"only {ch['trades']} trades in half {i} (needs {MIN_HALF_TRADES})")
        elif (ch["expectancy_r"] or 0) < (base["expectancy_r"] or 0) - 1e-9:
            why.append(f"half {i}: {ch['expectancy_r'] or 0:+.3f}R, below the baseline's {base['expectancy_r'] or 0:+.3f}R")
    return not why, "; ".join(why)


def history_compare(settings: Settings, conn: sqlite3.Connection, changes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Replay the baseline and every challenger {name: override} over the stored history. Returns a result per name."""
    from tradeagent.venue_replay import copy_journal, reset_shadow

    base = ex.effective_baseline(settings, conn)
    baseline = Variant(BASELINE_NAME, SetupParams.model_validate(base), "baseline")
    variants = [baseline] + [ex.challenger(name, base, change) for name, change in changes.items()]
    coins = ex.coins(settings)
    started = time.monotonic()
    copy = copy_journal(settings, "screen")
    try:
        reset_shadow(copy)
        register_variants(copy, variants)
        SetupEngine(settings, variants, copy).process()
        Tracker(settings, copy).update()
        times = _entry_times(copy, baseline.id, coins)
        if len(times) < 2 * MIN_HALF_TRADES:
            raise RuntimeError(f"the history has only {len(times)} baseline trades on {coins}: too little to screen")
        start, end, mid = times[0], times[-1] + 1, times[len(times) // 2]
        out = {}
        for v in variants[1:]:
            stats = {
                "all": {"challenger": ex.window_stats(copy, v.id, start, coins, end),
                        "baseline": ex.window_stats(copy, baseline.id, start, coins, end)},
                "halves": [{"challenger": ex.window_stats(copy, v.id, a, coins, b),
                            "baseline": ex.window_stats(copy, baseline.id, a, coins, b)} for a, b in ((start, mid), (mid, end))],
            }
            passed, why = judge(stats, settings)
            out[v.name] = {"passed": passed, "why": why or "beat the baseline overall and held up in both halves",
                           "period": [start, end], "split": mid, "coins": coins, "variant_id": v.id, **stats,
                           "seconds": round(time.monotonic() - started)}
        return out
    finally:
        copy.close()


def long_screen_on(settings: Settings) -> bool:
    from tradeagent.learning.long_screen import source

    return settings.learning.screen_on_long_history and source(settings) is not None


def screen_pending(settings: Settings, conn: sqlite3.Connection, ids: list[int] | None = None,
                   long_stage: bool = True) -> list[str]:
    """Screen the experiments waiting in 'screening' (or these ids) and record each verdict.

    Stage 1 replays the stored history (minutes). With the long screen on, a pass there keeps the experiment in
    'screening' with its history result, and stage 2 (`long_stage`, about an hour, run by the agent's background
    job) replays the long research history; only a pass in both starts the forward test."""
    query = "SELECT id, name, change_json, screen_json FROM experiments WHERE status = 'screening'"
    rows = conn.execute(query + (f" AND id IN ({','.join('?' * len(ids))})" if ids else "") + " ORDER BY id",
                        tuple(ids or ())).fetchall()
    if not rows:
        return []
    lines = []
    two_stage = long_screen_on(settings)
    first = [r for r in rows if not (json.loads(r["screen_json"] or "{}")).get("history_passed")]
    if first:
        results = history_compare(settings, conn, {r["name"]: json.loads(r["change_json"]) for r in first})
        for r in first:
            result = results[r["name"]]
            if result["passed"] and two_stage:
                ex.record_history_pass(conn, r["id"], result)
                lines.append(f"{r['name']}: passed the history screen; the 4-year screen follows in the background")
            else:
                lines.append(f"{r['name']}: {ex.finish_screen(conn, settings, r['id'], result)}")
    if long_stage and two_stage:
        from tradeagent.learning.long_screen import compare

        waiting = conn.execute(query + " ORDER BY id").fetchall()
        second = [r for r in waiting if (json.loads(r["screen_json"] or "{}")).get("history_passed")
                  and (not ids or r["id"] in ids)]
        if second:
            longs = compare(settings, conn, {r["name"]: json.loads(r["change_json"]) for r in second})
            for r in second:
                history, long = json.loads(r["screen_json"]), longs[r["name"]]
                combined = {**history, "long": long, "passed": long["passed"],
                            "why": f"4 years: {long['why']}" if not long["passed"] else
                                   f"{history['why']}; 4 years: {long['why']}"}
                lines.append(f"{r['name']}: {ex.finish_screen(conn, settings, r['id'], combined)}")
    return lines
