"""Learning-loop commands (called from cli.py): research pack and experiments."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tradeagent.config import Settings, load_settings
from tradeagent.journal import connect, migrate
from tradeagent.learning import experiments as ex
from tradeagent.logging_setup import setup_logging
from tradeagent.settings_store import apply_overrides
from tradeagent.tv.catalog import load_catalog


def _low_priority() -> None:
    """History replays take minutes of CPU: let the agent's TradingView reads go first."""
    try:
        import psutil

        proc = psutil.Process()
        proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if hasattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS") else 10)
    except Exception:
        pass


@contextmanager
def _open() -> Iterator[tuple[Settings, sqlite3.Connection, list]]:
    settings = load_settings()
    setup_logging(settings, console=False)
    conn = connect(settings.resolve(settings.journal.path))
    try:
        migrate(conn)
        apply_overrides(settings, conn)
        catalog = load_catalog(settings.resolve(settings.tradingview.catalog))
        variants = ex.active_variants(settings, conn, catalog)
        ex.sync_manual(conn, settings, variants)
        yield settings, conn, variants
    finally:
        conn.close()


def _fmt(s: dict[str, Any] | None) -> str:
    if not s or not s.get("trades"):
        return "0 trades"
    pf = f"{s['profit_factor']:.2f}" if s.get("profit_factor") else "-"
    return f"{s['trades']:3} trades {s['expectancy_r']:+.3f}R PF {pf} DD {s['max_drawdown_r']:.1f}R"


def _day(ms: int | None) -> str:
    return time.strftime("%m-%d %H:%M", time.gmtime(ms / 1000)) if ms else "-"


def research_pack() -> int:
    from tradeagent.learning.pack import write_pack

    with _open() as (settings, conn, variants):
        path = write_pack(settings, conn, variants)
    print(f"research pack written: {path}")
    print("also as research/packs/latest.md and latest.json")
    return 0


def experiment_list(show_all: bool = False) -> int:
    with _open() as (settings, conn, variants):
        rows = ex.summary(conn, settings, variants)
        rules = settings.learning
    print(f"Judge: {rules.min_trades} trades each, edge >= {rules.min_edge_r:g}R, PF not lower, drawdown at most "
          f"{rules.max_drawdown_worse:.0%} worse; re-confirm on {rules.reconfirm_trades} fresh trades. "
          f"Auto-promote: {'on' if rules.auto_promote else 'off'}.")
    shown = [r for r in rows if show_all or r["status"] in ex.OPEN]
    for r in shown:
        print(f"\n#{r['id']} {r['name']} [{r['status']}] ({r['source']}) {json.dumps(r['change'])}")
        if r["status"] in ex.ACTIVE:
            since = r["reconfirm_from"] or r["started_at"]
            print(f"   since {_day(since)} UTC  challenger: {_fmt(r['challenger'])}")
            print(f"   {'':<20}baseline:   {_fmt(r['baseline'])}")
        elif r.get("challenger"):
            print(f"   decided {_day(r['decided_at'])}: challenger {_fmt(r['challenger'])} | baseline {_fmt(r['baseline'])}")
        if r["lesson"]:
            print(f"   lesson: {r['lesson'].splitlines()[-1]}")
    hidden = len(rows) - len(shown)
    print(f"\n{len(rows)} experiments in all" + (f" ({hidden} decided ones hidden; --all shows them)" if hidden else ""))
    return 0


def _load_proposals(source: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Proposals and lessons from a research run's output (research/proposal.schema.json), a list or one proposal."""
    text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    data = json.loads(text)
    if isinstance(data, dict) and "proposals" in data:
        return data["proposals"] or [], data.get("lessons") or []
    return (data if isinstance(data, list) else [data]), []


def experiment_propose(source: str, origin: str, screen: bool) -> int:
    from tradeagent.learning.screen import screen_pending

    _low_priority()
    try:
        proposals, lessons = _load_proposals(source)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read the proposals: {exc}")
        return 2
    with _open() as (settings, conn, _):
        for lesson in lessons:
            try:
                ex.add_lesson(conn, settings, int(lesson["experiment_id"]), str(lesson["text"]))
                print(f"lesson added to experiment {lesson['experiment_id']}")
            except (KeyError, ValueError) as exc:
                print(f"lesson skipped: {exc}")
        added = []
        for p in proposals:
            exp_id, problems = ex.propose(conn, settings, p, origin)
            if problems:
                print(f"REJECTED {p.get('name')}: " + "; ".join(problems))
            else:
                added.append(exp_id)
                print(f"recorded #{exp_id} {p['name']}: {p['change']['path']} = {json.dumps(p['change']['value'])}")
        if added and screen and settings.learning.screen_on_history:
            print(f"Screening {len(added)} proposal(s) on the stored history in one replay (a few minutes)...",
                  flush=True)
            for line in screen_pending(settings, conn, added):
                print(f"  {line}")
        elif added and settings.learning.screen_on_history:
            print("Not screened yet: the agent screens waiting proposals within the hour (or: experiment screen).")
    return 0 if added or not proposals else 1


def experiment_try(path: str, value: str) -> int:
    """Screen one change on the history without recording anything."""
    from tradeagent.learning.screen import history_compare
    from tradeagent.learning.space import override_for, validate_change

    _low_priority()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = value
    with _open() as (settings, conn, _):
        _, problems = validate_change(ex.effective_baseline(settings, conn), path, parsed)
        if problems:
            print("; ".join(problems))
            return 2
        print(f"Replaying the history with {path} = {json.dumps(parsed)} (1-2 minutes)...", flush=True)
        result = history_compare(settings, conn, {"try": override_for(path, parsed)})["try"]
    print(f"period {_day(result['period'][0])} .. {_day(result['period'][1])} UTC on {', '.join(result['coins'])}")
    print(f"  all      challenger {_fmt(result['all']['challenger'])} | baseline {_fmt(result['all']['baseline'])}")
    for i, half in enumerate(result["halves"], 1):
        print(f"  half {i}   challenger {_fmt(half['challenger'])} | baseline {_fmt(half['baseline'])}")
    print(f"verdict: {'PASS' if result['passed'] else 'FAIL'} - {result['why']}")
    return 0


def experiment_screen(ids: list[int] | None) -> int:
    from tradeagent.learning.screen import screen_pending

    _low_priority()
    with _open() as (settings, conn, _):
        lines = screen_pending(settings, conn, ids)
    print("\n".join(lines) or "no proposal is waiting for its history screen")
    return 0


def experiment_evaluate() -> int:
    with _open() as (settings, conn, variants):
        actions = ex.evaluate(conn, settings, variants)
    print("\n".join(actions) or "no experiment has enough trades for a verdict yet")
    return 0


def experiment_stop(exp_id: int, reason: str) -> int:
    with _open() as (_, conn, _v):
        ex.stop(conn, exp_id, reason)
    print(f"experiment {exp_id} stopped")
    return 0


def experiment_lesson(exp_id: int, text: str) -> int:
    with _open() as (settings, conn, _):
        ex.add_lesson(conn, settings, exp_id, text)
    print(f"lesson added to experiment {exp_id} and research/lessons.md")
    return 0


def experiment_promote(exp_id: int, confirm: bool, early: bool = False) -> int:
    with _open() as (settings, conn, _):
        row = conn.execute("SELECT * FROM experiments WHERE id = ?", (exp_id,)).fetchone()
        if row is None:
            print(f"experiment {exp_id} not found")
            return 2
        if row["status"] not in ex.ACTIVE:
            print(f"{row['name']} is {row['status']}: only a running experiment can be promoted")
            return 2
        if not ex.confirmed(row) and not early:
            print(f"{row['name']} has not won twice yet. Add --early to promote it anyway (recorded as early).")
            return 2
        if not confirm:
            print(f"This makes {row['name']} the demo account's baseline and writes it into config/setups.yaml."
                  " Run again with --yes to do it.")
            return 1
        try:
            print(ex.promote(conn, settings, exp_id, by="cli", early=not ex.confirmed(row)))
        except ValueError as exc:
            print(f"not promoted: {exc}")
            return 2
    return 0
