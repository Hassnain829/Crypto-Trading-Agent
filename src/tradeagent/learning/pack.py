"""Research pack: what Claude reads before proposing a change (research/packs/<day>.json and .md, plus latest.*).

Every number is computed from the journal by code Claude does not change. "history" = every closed exploration
trade (the replayed history and the forward weeks); "forward" = since the demo account's forward start.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from tradeagent.config import Settings
from tradeagent.learning import experiments as ex
from tradeagent.learning.space import SPACE, get_path
from tradeagent.setups.config import Variant
from tradeagent.setups.report import summarize

WORST = 8
HOURS = ((0, 4), (4, 8), (8, 12), (12, 16), (16, 20), (20, 24))


def _utc(ms: int | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    return time.strftime(fmt, time.gmtime(ms / 1000)) if ms else "-"


def _closed(conn: sqlite3.Connection, variant_id: str, coins: list[str], since: int = 0, taken: int = 1) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT id, symbol, timeframe, side, entry_time, exit_time, exit_reason, reason, r_net, mfe_r, context_json"
        f" FROM trades WHERE book = 'exploration' AND variant_id = ? AND taken = ? AND status = 'closed'"
        f" AND entry_time >= ? AND symbol IN ({','.join('?' * len(coins))}) ORDER BY exit_time",
        (variant_id, taken, since, *coins)).fetchall()


def _stats(rows: list[sqlite3.Row]) -> dict[str, Any]:
    out = summarize([r["r_net"] for r in rows])
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in out.items()}


def _group(rows: list[sqlite3.Row], key) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)
    return {k: _stats(v) for k, v in sorted(groups.items())}


def _hour(r: sqlite3.Row) -> str:
    h = time.gmtime(r["entry_time"] / 1000).tm_hour
    a, b = next(x for x in HOURS if x[0] <= h < x[1])
    return f"{a:02d}-{b:02d} UTC"


def _htf(r: sqlite3.Row) -> str:
    htf = json.loads(r["context_json"]).get("htf") or {}
    want = "bull" if r["side"] == "long" else "bear"
    agree = [tf for tf in ("1h", "4h") if htf.get(tf) == want]
    return {0: "1h and 4h against", 1: f"only {agree[0] if agree else ''} with".strip(), 2: "1h and 4h with"}[len(agree)]


def _streaks(rows: list[sqlite3.Row]) -> dict[str, int]:
    longest = current = 0
    for r in rows:
        current = current + 1 if r["r_net"] < 0 else 0
        longest = max(longest, current)
    return {"longest_losing": longest, "current_losing": current}


def _quality(conn: sqlite3.Connection, now: int) -> dict[str, Any]:
    day_ago = now - 86_400_000
    rows = conn.execute("SELECT symbol, timeframe, count(*), sum(problems_json IS NOT NULL), max(bar_time) FROM snapshots"
                        " WHERE bar_time >= ? AND timeframe IN ('5m', '15m') GROUP BY 1, 2", (day_ago,)).fetchall()
    events = conn.execute("SELECT level, count(*) FROM events WHERE ts >= ? AND level IN ('WARNING', 'ERROR') GROUP BY 1",
                          (day_ago,)).fetchall()
    return {
        "snapshots_24h": {f"{r[0]} {r[1]}": {"stored": r[2], "expected": 288 if r[1] == "5m" else 96, "with_problems": r[3] or 0,
                                             "newest": _utc(r[4])} for r in rows},
        "warnings_24h": dict(events),
        "open_trades": conn.execute("SELECT count(*) FROM trades WHERE book = 'exploration' AND status = 'open'").fetchone()[0],
    }


def build_pack(settings: Settings, conn: sqlite3.Connection, variants: list[Variant] | None = None) -> dict[str, Any]:
    variants = variants or ex.active_variants(settings, conn)
    baseline = variants[0]
    coins = ex.coins(settings)
    now = int(time.time() * 1000)
    state = conn.execute("SELECT started_at FROM account_state WHERE account = 'paper'").fetchone()
    forward = (state[0] if state else None) or now
    base_rows = _closed(conn, baseline.id, coins)
    filtered = conn.execute(
        f"SELECT reason, r_net FROM trades WHERE book = 'exploration' AND variant_id = ? AND taken = 0 AND status = 'closed'"
        f" AND symbol IN ({','.join('?' * len(coins))})", (baseline.id, *coins)).fetchall()
    by_filter: dict[str, list[float]] = defaultdict(list)
    for r in filtered:
        by_filter[r["reason"] or "?"].append(r["r_net"])
    worst = sorted(base_rows, key=lambda r: r["r_net"])[:WORST]
    rules = baseline.params.model_dump()
    return {
        "generated_at": _utc(now),
        "coins": coins,
        "forward_start": _utc(forward),
        "baseline": {"id": baseline.id, "rules": rules},
        "judge": settings.learning.model_dump(),
        "variants": [{"name": v.name, "id": v.id, "history": _stats(_closed(conn, v.id, coins)),
                      "forward": _stats(_closed(conn, v.id, coins, forward))} for v in variants],
        "baseline_breakdown": {
            "by_coin": _group(base_rows, lambda r: r["symbol"]),
            "by_timeframe": _group(base_rows, lambda r: r["timeframe"]),
            "by_side": _group(base_rows, lambda r: r["side"]),
            "by_hour": _group(base_rows, _hour),
            "by_htf": _group(base_rows, _htf),
            "by_exit": _group(base_rows, lambda r: r["exit_reason"] or "?"),
            "streaks": _streaks(base_rows),
            "reached_half_r_then_stopped": sum(1 for r in base_rows if r["exit_reason"] == "stop" and (r["mfe_r"] or 0) >= 0.5),
        },
        "filters": {reason: {"trades_filtered": len(rs), "their_expectancy_r": round(sum(rs) / len(rs), 3)}
                    for reason, rs in sorted(by_filter.items(), key=lambda x: -len(x[1]))},
        "worst_trades": [{"id": r["id"], "symbol": r["symbol"], "tf": r["timeframe"], "side": r["side"],
                          "entry": _utc(r["entry_time"]), "r_net": round(r["r_net"], 3), "exit": r["exit_reason"],
                          "snapshot_id": json.loads(r["context_json"]).get("snapshot_id")} for r in worst],
        "experiments": [{k: e.get(k) for k in ("id", "name", "source", "status", "change", "hypothesis", "challenger",
                                               "baseline", "lesson")} for e in ex.summary(conn, settings, variants)],
        "experiment_counts": dict(conn.execute("SELECT status, count(*) FROM experiments GROUP BY status").fetchall()),
        "allowed_changes": {path: {"now": _value(rules, path), "help": k.help,
                                   **({"choices": list(k.choices)} if k.choices else {}),
                                   **({"range": [k.lo, k.hi], "step": k.step} if k.lo is not None else {}),
                                   **({"null_allowed": True} if k.nullable else {})} for path, k in SPACE.items()},
        "data_quality": _quality(conn, now),
    }


def _value(rules: dict[str, Any], path: str) -> Any:
    try:
        return get_path(rules, path)
    except (KeyError, TypeError):
        return None


def _line(s: dict[str, Any] | None) -> str:
    if not s or not s.get("trades"):
        return "no closed trades"
    pf = f"{s['profit_factor']:.2f}" if s.get("profit_factor") else "-"
    return (f"{s['trades']} trades, win {s['win_rate']:.0%}, {s['expectancy_r']:+.3f}R/trade, total {s['total_r']:+.1f}R,"
            f" PF {pf}, max DD {s['max_drawdown_r']:.1f}R")


def to_markdown(pack: dict[str, Any]) -> str:
    out = [f"# Research pack {pack['generated_at']} UTC", "",
           f"Coins traded by the demo: {', '.join(pack['coins'])}. Forward test since {pack['forward_start']} UTC.",
           f"Baseline `{pack['baseline']['id']}`. Judge: {json.dumps(pack['judge'])}.", "", "## Variants", "",
           "| variant | history | forward |", "|---|---|---|"]
    out += [f"| {v['name']} | {_line(v['history'])} | {_line(v['forward'])} |" for v in pack["variants"]]
    out += ["", "## Baseline breakdown (history, demo coins)", ""]
    for title, groups in pack["baseline_breakdown"].items():
        if isinstance(groups, dict) and groups and isinstance(next(iter(groups.values())), dict):
            out.append(f"**{title.replace('_', ' ')}**")
            out += [f"- {k}: {_line(s)}" for k, s in groups.items()]
            out.append("")
    b = pack["baseline_breakdown"]
    out += [f"Losing streaks: longest {b['streaks']['longest_losing']}, current {b['streaks']['current_losing']}.",
            f"Stopped trades that first reached +0.5R: {b['reached_half_r_then_stopped']}.", "",
            "## Filters (what the skipped setups would have made)", ""]
    out += [f"- {k}: {v['trades_filtered']} skipped, {v['their_expectancy_r']:+.3f}R each" for k, v in pack["filters"].items()]
    out += ["", "## Worst trades", ""]
    out += [f"- #{t['id']} {t['symbol']} {t['tf']} {t['side']} {t['entry']} {t['r_net']:+.2f}R ({t['exit']}),"
            f" snapshot {t['snapshot_id']}" for t in pack["worst_trades"]]
    out += ["", "## Experiments", "", f"Counts: {json.dumps(pack['experiment_counts'])}", ""]
    for e in pack["experiments"]:
        out.append(f"- **{e['name']}** ({e['source']}, {e['status']}): `{json.dumps(e['change'])}`")
        if e.get("challenger"):
            out.append(f"  - challenger: {_line(e['challenger'])}; baseline same period: {_line(e['baseline'])}")
        if e.get("lesson"):
            out.append(f"  - lesson: {e['lesson'].splitlines()[-1]}")
    out += ["", "## Allowed changes (one per proposal)", ""]
    for path, k in pack["allowed_changes"].items():
        extra = k.get("choices") or (f"{k['range'][0]:g}..{k['range'][1]:g} step {k['step']:g}" if "range" in k else "")
        out.append(f"- `{path}` now `{json.dumps(k['now'])}`: {k['help']} ({extra}{', null allowed' if k.get('null_allowed') else ''})")
    q = pack["data_quality"]
    out += ["", "## Data quality (last 24 h)", ""]
    out += [f"- {k}: {v['stored']}/{v['expected']} snapshots, {v['with_problems']} with problems, newest {v['newest']}"
            for k, v in q["snapshots_24h"].items()]
    out += [f"- warnings/errors: {json.dumps(q['warnings_24h'])}; open shadow trades: {q['open_trades']}", ""]
    return "\n".join(out)


def packs_dir(settings: Settings) -> Path:
    return settings.root / "research" / "packs"


def write_pack(settings: Settings, conn: sqlite3.Connection, variants: list[Variant] | None = None) -> Path:
    pack = build_pack(settings, conn, variants)
    folder = packs_dir(settings)
    folder.mkdir(parents=True, exist_ok=True)
    day = time.strftime("%Y-%m-%d", time.gmtime())
    text, md = json.dumps(pack, indent=1, default=str), to_markdown(pack)
    for name in (day, "latest"):
        (folder / f"{name}.json").write_text(text, encoding="utf-8")
        (folder / f"{name}.md").write_text(md, encoding="utf-8")
    write_results(settings, conn)
    return folder / f"{day}.md"


def write_results(settings: Settings, conn: sqlite3.Connection) -> Path:
    """research/results.tsv: one line per experiment (the autoresearch-style log), rebuilt from the journal."""
    lines = ["id\tcreated\tname\tsource\tchange\tstatus\tdecided\tchallenger_trades\tchallenger_r\tbaseline_trades"
             "\tbaseline_r\tlesson"]
    for r in conn.execute("SELECT * FROM experiments ORDER BY id"):
        res = json.loads(r["result_json"] or "{}")
        ch, base = res.get("challenger") or {}, res.get("baseline") or {}
        cells = [r["id"], _utc(r["created_at"], "%Y-%m-%d"), r["name"], r["source"], r["change_json"], r["status"],
                 _utc(r["decided_at"], "%Y-%m-%d") if r["decided_at"] else "", ch.get("trades", ""),
                 "" if ch.get("expectancy_r") is None else f"{ch['expectancy_r']:+.3f}", base.get("trades", ""),
                 "" if base.get("expectancy_r") is None else f"{base['expectancy_r']:+.3f}",
                 (r["lesson"] or "").splitlines()[-1] if r["lesson"] else ""]
        lines.append("\t".join(str(c).replace("\t", " ") for c in cells))
    path = settings.root / "research" / "results.tsv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def written_today(settings: Settings) -> bool:
    return (packs_dir(settings) / f"{time.strftime('%Y-%m-%d', time.gmtime())}.md").exists()
