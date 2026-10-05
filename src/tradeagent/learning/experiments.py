"""Experiment Manager: proposals become challengers, challengers are judged, winners are promoted.

Lifecycle:  screening -> running -> reconfirming -> promoted
            (rejected after a failed history screen; lost when beaten; stopped by hand)

- config/setups.yaml stays the human-edited file: the baseline and the manual challengers. Manual challengers
  are tracked here too (source 'setups.yaml') so they are judged by the same rules.
- Experiments proposed by Claude or the user live in the journal (source 'claude' / 'user').
- A promotion (automatic, or by hand from the dashboard / CLI) is written into setups.yaml: the change goes into
  the baseline, the challenger's line is removed, the header gets a history line, and a backup is kept in
  data/backups. setups.yaml's baseline is therefore always what the demo trades.
- The judge compares the challenger with the baseline on their closed shadow trades in the same period, on the
  coins the demo account trades. Rules: settings `learning`.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import yaml

from tradeagent.config import Settings
from tradeagent.journal import log_event
from tradeagent.journal.db import now_ms
from tradeagent.learning.space import override_for, validate_change
from tradeagent.setups.config import BASELINE_NAME, SetupParams, Variant, deep_merge, load_variants
from tradeagent.setups.report import summarize

ACTIVE = ("running", "reconfirming")
OPEN = ("screening", *ACTIVE)
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
REFERENCE = {"video_original"}  # kept for comparison only, never promoted


def _canon(change: dict[str, Any]) -> str:
    return json.dumps(change, sort_keys=True, separators=(",", ":"))


def _row(conn: sqlite3.Connection, exp_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM experiments WHERE id = ?", (exp_id,)).fetchone()
    if row is None:
        raise ValueError(f"experiment {exp_id} not found")
    return row


def setups_raw(settings: Settings) -> dict[str, Any]:
    with settings.resolve(settings.shadow.setups).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def effective_baseline(settings: Settings, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """The rules the demo trades: setups.yaml's baseline (promotions are written into it)."""
    return setups_raw(settings)["baseline"]


def challenger(name: str, baseline: dict[str, Any], change: dict[str, Any]) -> Variant:
    return Variant(name, SetupParams.model_validate(deep_merge(baseline, change)), "challenger")


def active_variants(settings: Settings, conn: sqlite3.Connection, catalog: Any | None = None) -> list[Variant]:
    """The baseline (with promotions), the manual challengers of setups.yaml and the running experiments."""
    raw = setups_raw(settings)
    base = effective_baseline(settings, conn)
    file_variants = load_variants(settings.resolve(settings.shadow.setups), catalog)  # validates the file
    variants = [Variant(BASELINE_NAME, SetupParams.model_validate(base), "baseline")]
    promoted = {r[0] for r in conn.execute("SELECT name FROM experiments WHERE status = 'promoted'")}
    for v in file_variants[1:]:
        if v.name not in promoted:
            variants.append(challenger(v.name, base, (raw.get("variants") or {}).get(v.name) or {}))
    for row in conn.execute("SELECT name, change_json FROM experiments WHERE source != 'setups.yaml' AND status IN (?, ?)"
                            " ORDER BY id", ACTIVE):
        variants.append(challenger(row["name"], base, json.loads(row["change_json"])))
    return variants


def sync_manual(conn: sqlite3.Connection, settings: Settings, variants: list[Variant]) -> list[str]:
    """Track setups.yaml's challengers as experiments; stop those removed from the file."""
    actions = []
    raw = setups_raw(settings)
    baseline_id = variants[0].id
    start = conn.execute("SELECT started_at FROM account_state WHERE account = 'paper'").fetchone()
    account_start = (start[0] if start else None) or 0
    names = set()
    with conn:
        for v in variants[1:]:
            change = (raw.get("variants") or {}).get(v.name)
            if change is None:
                continue  # an experiment from the journal
            names.add(v.name)
            row = conn.execute("SELECT * FROM experiments WHERE name = ?", (v.name,)).fetchone()
            if row is None:
                # Compared from the demo's forward start, or from when the variant first ran if it is newer.
                first = conn.execute("SELECT created_at FROM variants WHERE id = ?", (v.id,)).fetchone()
                since = max(account_start, first[0] if first else now_ms())
                conn.execute(
                    "INSERT INTO experiments (name, source, baseline_id, change_json, hypothesis, status, variant_id,"
                    " started_at, created_at) VALUES (?, 'setups.yaml', ?, ?, ?, 'running', ?, ?, ?)",
                    (v.name, baseline_id, _canon(change), "manual challenger from config/setups.yaml", v.id, since, now_ms()),
                )
                actions.append(f"tracking {v.name}")
            elif row["status"] in ACTIVE and row["change_json"] != _canon(change):
                conn.execute("UPDATE experiments SET change_json = ?, variant_id = ?, started_at = ?, reconfirm_from = NULL,"
                             " status = 'running' WHERE id = ?", (_canon(change), v.id, now_ms(), row["id"]))
                actions.append(f"{v.name} changed in setups.yaml: its comparison restarts")
        for row in conn.execute("SELECT id, name FROM experiments WHERE source = 'setups.yaml' AND status IN (?, ?)", ACTIVE):
            if row["name"] not in names:
                conn.execute("UPDATE experiments SET status = 'stopped', decided_at = ?, lesson = coalesce(lesson, ?)"
                             " WHERE id = ?", (now_ms(), "removed from config/setups.yaml", row["id"]))
                actions.append(f"stopped {row['name']} (removed from setups.yaml)")
    return actions


def propose(conn: sqlite3.Connection, settings: Settings, proposal: dict[str, Any], source: str = "claude") -> tuple[int | None, list[str]]:
    """Validate a proposal and record it. Returns (experiment id, problems)."""
    problems: list[str] = []
    name = str(proposal.get("name") or "")
    change = proposal.get("change") or {}
    hypothesis = str(proposal.get("hypothesis") or "").strip()
    if not NAME_RE.match(name) or name == BASELINE_NAME:
        problems.append("name must be 3-41 lowercase letters, digits or _ (starting with a letter), not 'v0'")
    elif conn.execute("SELECT 1 FROM experiments WHERE name = ?", (name,)).fetchone() or \
            name in (setups_raw(settings).get("variants") or {}):
        problems.append(f"the name {name!r} is taken")
    if not hypothesis:
        problems.append("a hypothesis is required: what should improve, and why")
    confidence = proposal.get("confidence")
    if confidence is not None and not (isinstance(confidence, (int, float)) and 0 <= confidence <= 1):
        problems.append("confidence must be between 0 and 1")
    if not isinstance(change, dict) or set(change) != {"path", "value"}:
        problems.append('change must be {"path": "...", "value": ...}: exactly one rule')
        return None, problems
    base = effective_baseline(settings, conn)
    rules, change_problems = validate_change(base, change["path"], change["value"])
    problems += change_problems
    if problems:
        return None, problems
    override = override_for(change["path"], change["value"])
    baseline_id = Variant(BASELINE_NAME, SetupParams.model_validate(base), "baseline").id
    tested = conn.execute("SELECT name, status FROM experiments WHERE baseline_id = ? AND change_json = ?",
                          (baseline_id, _canon(override))).fetchone()
    if tested:
        return None, [f"already tested against this baseline as {tested['name']} ({tested['status']})"]
    open_count = conn.execute(f"SELECT count(*) FROM experiments WHERE status IN ({','.join('?' * len(OPEN))})", OPEN).fetchone()[0]
    if open_count >= settings.learning.max_challengers:
        return None, [f"{open_count} challengers are running (max {settings.learning.max_challengers}); stop one first"]
    screening = settings.learning.screen_on_history
    variant = challenger(name, base, override)
    with conn:
        cur = conn.execute(
            "INSERT INTO experiments (name, source, baseline_id, change_json, hypothesis, expected, confidence, status,"
            " variant_id, started_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, source, baseline_id, _canon(override), hypothesis, proposal.get("expected"), confidence,
             "screening" if screening else "running", variant.id, None if screening else now_ms(), now_ms()),
        )
    log_event(conn, "INFO", "learning", f"proposal {name}: {change['path']} = {change['value']!r} ({source})")
    return cur.lastrowid, []


def finish_screen(conn: sqlite3.Connection, settings: Settings, exp_id: int, result: dict[str, Any]) -> str:
    """Record a history screen: a pass starts the forward test, a fail rejects the proposal."""
    row = _row(conn, exp_id)
    passed = bool(result.get("passed"))
    with conn:
        if passed:
            conn.execute("UPDATE experiments SET status = 'running', screen_json = ?, started_at = ? WHERE id = ?",
                         (json.dumps(result), now_ms(), exp_id))
        else:
            conn.execute("UPDATE experiments SET status = 'rejected', screen_json = ?, decided_at = ? WHERE id = ?",
                         (json.dumps(result), now_ms(), exp_id))
    verdict = "passed the history screen: forward test started" if passed else f"rejected on history: {result.get('why')}"
    log_event(conn, "INFO", "learning", f"{row['name']} {verdict}")
    if not passed:
        add_lesson(conn, settings, exp_id, f"Rejected on history before any forward trade: {result.get('why')}", auto=True)
    return verdict


def window_stats(conn: sqlite3.Connection, variant_id: str, since: int, coins: list[str],
                 until: int | None = None) -> dict[str, Any]:
    """Closed taken trades of one variant entered in [since, until) on these coins."""
    r = [x[0] for x in conn.execute(
        f"SELECT r_net FROM trades WHERE book = 'exploration' AND variant_id = ? AND taken = 1 AND status = 'closed'"
        f" AND entry_time >= ? AND entry_time < ? AND symbol IN ({','.join('?' * len(coins))}) ORDER BY exit_time",
        (variant_id, since, until or 2**62, *coins))]
    return summarize(r)


def beats(ch: dict[str, Any], base: dict[str, Any], settings: Settings) -> tuple[bool, list[str]]:
    rules = settings.learning
    why = []
    if (ch["expectancy_r"] or 0) < (base["expectancy_r"] or 0) + rules.min_edge_r:
        why.append(f"expectancy {ch['expectancy_r'] or 0:+.3f}R is not {rules.min_edge_r:g}R above the baseline's "
                   f"{base['expectancy_r'] or 0:+.3f}R")
    if (ch["profit_factor"] or 0) < (base["profit_factor"] or 0):
        why.append(f"profit factor {ch['profit_factor'] or 0:.2f} below the baseline's {base['profit_factor'] or 0:.2f}")
    if ch["max_drawdown_r"] > base["max_drawdown_r"] * (1 + rules.max_drawdown_worse) + 1e-9:
        why.append(f"max drawdown {ch['max_drawdown_r']:.1f}R vs {base['max_drawdown_r']:.1f}R")
    return not why, why


def coins(settings: Settings) -> list[str]:
    """The coins the demo account trades: experiments are judged on these."""
    return settings.paper_account.symbols or list(settings.exchange.symbols)


def evaluate(conn: sqlite3.Connection, settings: Settings, variants: list[Variant] | None = None) -> list[str]:
    """Judge the running experiments; promote a confirmed winner if allowed. Returns what happened."""
    variants = variants or active_variants(settings, conn)
    baseline = variants[0]
    by_name = {v.name: v for v in variants}
    rules, traded, now, actions = settings.learning, coins(settings), now_ms(), []
    for row in conn.execute(f"SELECT * FROM experiments WHERE status IN ({','.join('?' * len(ACTIVE))}) ORDER BY id", ACTIVE).fetchall():
        variant = by_name.get(row["name"])
        if variant is None:
            continue
        if row["baseline_id"] != baseline.id or row["variant_id"] != variant.id:
            with conn:  # the baseline changed (a promotion): compare again from now on
                conn.execute("UPDATE experiments SET baseline_id = ?, variant_id = ?, started_at = ?, reconfirm_from = NULL,"
                             " status = 'running' WHERE id = ?", (baseline.id, variant.id, now, row["id"]))
            actions.append(f"{row['name']}: new baseline, comparison restarted")
            continue
        reconfirm = row["status"] == "reconfirming"
        since = row["reconfirm_from"] if reconfirm else row["started_at"]
        need = rules.reconfirm_trades if reconfirm else rules.min_trades
        ch, base = window_stats(conn, variant.id, since, traded), window_stats(conn, baseline.id, since, traded)
        if ch["trades"] < need or base["trades"] < need:
            continue
        won, why = beats(ch, base, settings)
        result = {"phase": "reconfirm" if reconfirm else "first", "since": since, "challenger": ch, "baseline": base,
                  "why": why}
        if not won:
            with conn:
                conn.execute("UPDATE experiments SET status = 'lost', decided_at = ?, result_json = ? WHERE id = ?",
                             (now, json.dumps(result), row["id"]))
            text = (f"{'Lost its lead on fresh trades' if reconfirm else 'Did not beat the baseline'}: " + "; ".join(why) +
                    f" ({ch['trades']} vs {base['trades']} trades).")
            add_lesson(conn, settings, row["id"], text, auto=True)
            actions.append(f"{row['name']} lost: {'; '.join(why)}")
        elif not reconfirm:
            with conn:
                conn.execute("UPDATE experiments SET status = 'reconfirming', reconfirm_from = ?, result_json = ? WHERE id = ?",
                             (now, json.dumps(result), row["id"]))
            log_event(conn, "INFO", "learning", f"{row['name']} beat the baseline; re-confirming on {rules.reconfirm_trades} fresh trades")
            actions.append(f"{row['name']} won the first round; re-confirming")
        elif rules.auto_promote and row["name"] not in REFERENCE:
            try:
                actions.append(promote(conn, settings, row["id"], result))
            except (ValueError, OSError) as exc:  # setups.yaml could not be written: wait for a promotion by hand
                with conn:
                    conn.execute("UPDATE experiments SET result_json = ? WHERE id = ?", (json.dumps(result), row["id"]))
                log_event(conn, "ERROR", "learning", f"{row['name']} won twice but was not promoted: {exc}")
                actions.append(f"{row['name']} confirmed but not promoted: {exc}")
        else:
            with conn:
                conn.execute("UPDATE experiments SET result_json = ? WHERE id = ?", (json.dumps(result), row["id"]))
            actions.append(f"{row['name']} confirmed; waiting for promotion by hand")
    return actions


def _next_version(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT version FROM baseline_history ORDER BY adopted_at DESC LIMIT 1").fetchone()
    last = row[0] if row else "v0"
    m = re.match(r"^v(\d+)(?:\.(\d+))?$", last)
    return f"v{m.group(1)}.{int(m.group(2) or 0) + 1}" if m else f"{last}+1"


def confirmed(row: sqlite3.Row) -> bool:
    """A winner that also stayed ahead on fresh trades (waiting for promotion by hand when auto-promote is off)."""
    return row["status"] == "reconfirming" and json.loads(row["result_json"] or "{}").get("phase") == "reconfirm"


def promote(conn: sqlite3.Connection, settings: Settings, exp_id: int, result: dict[str, Any] | None = None, *,
            by: str = "auto", early: bool = False) -> str:
    """Make the challenger the new baseline of the demo account (live trading still needs the user's approval).

    The change is written into config/setups.yaml first; if that fails nothing changes. `early`: promoted by hand
    before the judge's rules were met (allowed, and recorded as such).
    """
    from tradeagent.learning.setups_file import promote_in_file

    row = _row(conn, exp_id)
    if row["name"] in REFERENCE:
        raise ValueError(f"{row['name']} is a reference variant and is never promoted")
    if row["status"] not in ACTIVE:
        raise ValueError(f"{row['name']} is {row['status']}: only a running experiment can be promoted")
    if not early and not confirmed(row) and result is None:
        raise ValueError(f"{row['name']} has not won twice yet; promote it early only on purpose")
    now = now_ms()
    version = _next_version(conn)
    day = time.strftime("%Y-%m-%d", time.gmtime(now / 1000))
    how = "promoted by hand before the rules were met" if early else "promoted after winning twice"
    backup = promote_in_file(settings.resolve(settings.shadow.setups), json.loads(row["change_json"]), row["name"],
                             f"{version} ({day}): experiment {row['name']} {how} ({by}): {row['change_json']}",
                             settings.root / "data" / "backups")
    new_id = Variant(BASELINE_NAME, SetupParams.model_validate(effective_baseline(settings)), "baseline").id
    if result is None and early:
        since = row["reconfirm_from"] or row["started_at"] or now
        result = {"phase": "early", "by": by, "since": since,
                  "challenger": window_stats(conn, row["variant_id"], since, coins(settings)) if row["variant_id"] else None}
    ch = (result or {}).get("challenger") or json.loads(row["result_json"] or "{}").get("challenger") or {}
    started = time.strftime("%Y-%m-%d", time.gmtime((row["started_at"] or now) / 1000))
    with conn:
        conn.execute("UPDATE experiments SET status = 'promoted', decided_at = ?, result_json = coalesce(?, result_json)"
                     " WHERE id = ?", (now, json.dumps(result) if result else None, exp_id))
        conn.execute(
            "INSERT OR REPLACE INTO baseline_history (version, variant_id, adopted_at, summary, expectancy_r, trades,"
            " paper_return_pct, evidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (version, new_id, now, f"promoted experiment {row['name']}: {row['change_json']}", ch.get("expectancy_r"),
             ch.get("trades"), None, f"{how} ({by}); forward shadow trades since {started}; hypothesis: {row['hypothesis']}"),
        )
    log_event(conn, "WARNING", "learning", f"{row['name']} {how} ({by}): the demo now trades baseline {version} ({new_id});"
              f" setups.yaml updated, backup {backup.name}")
    add_lesson(conn, settings, exp_id,
               f"Promoted by hand ({by}) to baseline {version} before the judge's rules were met." if early else
               f"Promoted to baseline {version}: it beat the baseline and stayed ahead on fresh trades.", auto=True)
    return f"{row['name']} promoted to baseline {version}"


def stop(conn: sqlite3.Connection, exp_id: int, reason: str) -> None:
    with conn:
        conn.execute("UPDATE experiments SET status = 'stopped', decided_at = ?, lesson = coalesce(lesson, ?) WHERE id = ?",
                     (now_ms(), f"stopped by hand: {reason}", exp_id))
    log_event(conn, "INFO", "learning", f"experiment {exp_id} stopped: {reason}")


def lessons_path(settings: Settings) -> Path:
    return settings.root / "research" / "lessons.md"


def add_lesson(conn: sqlite3.Connection, settings: Settings, exp_id: int, text: str, *, auto: bool = False) -> None:
    """Store the lesson with the experiment and append it to research/lessons.md."""
    row = _row(conn, exp_id)
    with conn:
        conn.execute("UPDATE experiments SET lesson = ? WHERE id = ?",
                     (f"{row['lesson']}\n{text.strip()}" if row["lesson"] else text.strip(), exp_id))
    path = lessons_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# Lessons\n\nOne entry per experiment decision, newest last. Written by the Experiment Manager"
                        " and by Claude's research.\n", encoding="utf-8")
    heading = f"## {time.strftime('%Y-%m-%d', time.gmtime())} · {row['name']} · {row['change_json']}"
    headings = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("## ")]
    with path.open("a", encoding="utf-8") as fh:  # a second lesson on the same day joins the entry above
        fh.write(("" if headings and headings[-1] == heading else f"\n{heading}\n") + f"{'(auto) ' if auto else ''}{text.strip()}\n")


def summary(conn: sqlite3.Connection, settings: Settings, variants: list[Variant] | None = None,
            baseline_id: str | None = None) -> list[dict[str, Any]]:
    """Every experiment with its current numbers in its window (for the pack, the CLI and the dashboard)."""
    baseline_id = baseline_id or (variants or active_variants(settings, conn))[0].id
    traded, out = coins(settings), []
    for row in conn.execute("SELECT * FROM experiments ORDER BY id"):
        item = dict(row)
        item["change"] = json.loads(row["change_json"])
        item["result"] = json.loads(row["result_json"] or "{}")
        if row["status"] in ACTIVE and row["variant_id"]:
            since = row["reconfirm_from"] or row["started_at"] or now_ms()
            item["challenger"] = window_stats(conn, row["variant_id"], since, traded)
            item["baseline"] = window_stats(conn, baseline_id, since, traded)
        else:
            res = json.loads(row["result_json"] or "{}")
            item["challenger"], item["baseline"] = res.get("challenger"), res.get("baseline")
        out.append(item)
    return out
