"""Everything the dashboard shows, read from the journal (the UI itself calculates nothing).

The dashboard is a separate process: it opens its own connection, reads while the agent writes (WAL), and
writes only settings, the kill switch and the audit log.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import psutil

from tradeagent.account.engine import ACCOUNT, AccountEngine
from tradeagent.account.kill_switch import get_kill_switch, set_kill_switch
from tradeagent.account.preview import live_preview
from tradeagent.account.report import account_report
from tradeagent.config import PaperAccountConfig, Settings
from tradeagent.journal import migrate
from tradeagent.market.candles import find_gaps, tf_ms
from tradeagent.settings_store import apply_overrides
from tradeagent.setups.report import baseline_median_entry, summarize, variant_report
from tradeagent.supervisor import Supervisor, wanted_state
from tradeagent.tv.coverage import coverage

DAY = 86_400_000


def now_ms() -> int:
    return int(time.time() * 1000)


def day_start(ms: int) -> int:
    return ms - ms % DAY


def stats(values: list[float]) -> dict[str, Any]:
    """Trades, win rate, expectancy, total R and profit factor of a list of net R values."""
    s = summarize(values)
    return {"trades": s["trades"], "win_rate": s["win_rate"], "expectancy_r": s["expectancy_r"],
            "total_r": s["total_r"], "profit_factor": s["profit_factor"]}


class Store:
    """One per dashboard process. Settings = settings.yaml plus the overrides saved from the dashboard."""

    def __init__(self, defaults: Settings) -> None:
        self.defaults = defaults
        path = defaults.resolve(defaults.journal.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        migrate(self.conn)
        self._cache: dict[str, tuple[float, Any]] = {}
        self.supervisor: Supervisor | None = None  # set by the app: starts and stops the agent process

    # ---- helpers -----------------------------------------------------------------------------
    def cached(self, key: str, seconds: float, fn) -> Any:
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < seconds:
            return hit[1]
        value = fn()
        self._cache[key] = (time.monotonic(), value)
        return value

    def invalidate(self) -> None:
        self._cache.clear()

    @property
    def settings(self) -> Settings:
        def build() -> Settings:
            effective = self.defaults.model_copy(deep=True)
            apply_overrides(effective, self.conn)
            return effective
        return self.cached("settings", 2, build)

    def q(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple = ()) -> Any:
        row = self.conn.execute(sql, params).fetchone()
        return row[0] if row else None

    @property
    def baseline_id(self) -> str | None:
        return self.one("SELECT id FROM variants WHERE role = 'baseline'")

    def baseline_version(self) -> str:
        """The baseline's version name (v2, ...) from baseline_history, or its variant id."""
        bid = self.baseline_id
        version = self.one("SELECT version FROM baseline_history WHERE variant_id = ?", (bid,)) if bid else None
        return version or (bid or "–")

    @property
    def forward_start(self) -> int | None:
        return self.one("SELECT started_at FROM account_state WHERE account = ?", (ACCOUNT,))

    # ---- agent and system state --------------------------------------------------------------
    def agent_status(self) -> dict[str, Any]:
        rows = {r["key"]: (json.loads(r["value_json"]), r["updated_at"]) for r in self.q("SELECT * FROM agent_status")}
        agent = rows.get("agent", ({}, None))[0]
        beat, beat_at = rows.get("heartbeat", ({}, None))
        pid = agent.get("pid")
        alive = False
        if pid:
            try:
                alive = psutil.pid_exists(pid) and "python" in psutil.Process(pid).name().lower()
            except psutil.Error:
                alive = False
        age = (now_ms() - beat_at) / 1000 if beat_at else None
        if not alive:
            state = "stopped"
        elif age is None or (agent.get("started_at") or 0) > (beat_at or 0):
            state = "starting"
        elif age > 11 * 60:
            state = "stalled"
        else:
            state = "running"
        return {"state": state, "pid": pid, "started_at": agent.get("started_at"), "version": agent.get("version"),
                "last_cycle_age_s": age, "heartbeat": beat, "baseline": agent.get("baseline"),
                "wanted": wanted_state(self.conn)}

    def kill_switch(self) -> str:
        return get_kill_switch(self.conn)

    def set_kill_switch(self, mode: str) -> None:
        set_kill_switch(self.conn, mode, "dashboard")
        self.invalidate()

    def health(self) -> dict[str, Any]:
        now = now_ms()
        charts = []
        for symbol in self.settings.exchange.symbols:
            for tf in self.settings.all_timeframes:
                row = self.conn.execute(
                    "SELECT max(read_at), max(bar_time) FROM snapshots WHERE symbol = ? AND timeframe = ? AND source = 'live'"
                    " AND problems_json IS NULL", (symbol, tf)).fetchone()
                read_at = row[0]
                age = (now - read_at) / 1000 if read_at else None
                limit = tf_ms(tf) / 1000 + 120
                charts.append({"symbol": symbol, "timeframe": tf, "age_s": age,
                               "status": "idle" if age is None else "good" if age <= limit else "warning"})
        candle = self.one("SELECT max(open_time) FROM candles WHERE timeframe = '1m'")
        candle_age = (now - candle - 60_000) / 1000 if candle else None
        resources = self.q("SELECT data_json, ts FROM events WHERE source = 'resources' ORDER BY ts DESC LIMIT 1")
        research_docs = sorted((self.defaults.root / "docs" / "research").glob("*.md"))
        return {
            "charts": charts,
            "binance": {"age_s": candle_age, "status": "idle" if candle_age is None else "good" if candle_age < 300 else "warning"},
            "resources": json.loads(resources[0]["data_json"]) if resources else None,
            "resources_at": resources[0]["ts"] if resources else None,
            "last_research": research_docs[-1].stat().st_mtime * 1000 if research_docs else None,
            "machine": {"ram_used_pct": psutil.virtual_memory().percent, "cpu_pct": psutil.cpu_percent(interval=None)},
        }

    # ---- paper account -----------------------------------------------------------------------
    def paper(self) -> dict[str, Any]:
        settings = self.settings
        rules = settings.paper_account
        state = self.conn.execute("SELECT * FROM account_state WHERE account = ?", (ACCOUNT,)).fetchone()
        balance = state["balance"] if state else rules.starting_balance
        positions = AccountEngine(settings, self.conn).mark_to_market()
        unrealized = sum(p["unrealized_usd"] for p in positions)
        today = day_start(now_ms())
        realized_today = self.one("SELECT coalesce(sum(pnl_usd), 0) FROM account_trades WHERE account = ? AND status = 'closed'"
                                  " AND exit_time >= ?", (ACCOUNT, today)) or 0.0
        day_start_balance = state["day_start_balance"] if state and state["day"] == time.strftime(
            "%Y-%m-%d", time.gmtime(today / 1000)) else balance - realized_today
        closed = self.q("SELECT pnl_usd, r_net FROM account_trades WHERE account = ? AND status = 'closed'", (ACCOUNT,))
        s = stats([r["r_net"] for r in closed])
        loss_today = max(0.0, day_start_balance - balance) / day_start_balance if day_start_balance else 0.0
        return {
            "balance": balance, "equity": balance + unrealized, "unrealized": unrealized,
            "start": rules.starting_balance, "return_pct": (balance - rules.starting_balance) / rules.starting_balance * 100,
            "today_pnl": realized_today + unrealized, "today_pct": (realized_today + unrealized) / day_start_balance * 100
            if day_start_balance else 0.0,
            "positions": positions, "closed": s["trades"], "win_rate": s["win_rate"], "expectancy_r": s["expectancy_r"],
            "fees": self.one("SELECT coalesce(sum(fees_usd), 0) FROM account_trades WHERE account = ? AND status = 'closed'",
                             (ACCOUNT,)) or 0.0,
            "daily_stop": rules.daily_loss_stop, "loss_today": loss_today,
            "started_at": state["started_at"] if state else None,
            "rules": rules.model_dump(),
        }

    def equity_curve(self) -> list[tuple[int, float]]:
        start = self.settings.paper_account.starting_balance
        begin = self.forward_start or self.one("SELECT min(entry_time) FROM account_trades WHERE account = ?", (ACCOUNT,))
        points = [(begin or now_ms(), start)]
        points += [(r["exit_time"], r["balance_after"]) for r in self.q(
            "SELECT exit_time, balance_after FROM account_trades WHERE account = ? AND status = 'closed' ORDER BY exit_time, id",
            (ACCOUNT,))]
        return points

    def daily_pnl(self) -> list[tuple[str, float]]:
        return [(r[0], r[1]) for r in self.q(
            "SELECT date(exit_time / 1000, 'unixepoch') d, sum(pnl_usd) FROM account_trades WHERE account = ? AND status = 'closed'"
            " GROUP BY d ORDER BY d", (ACCOUNT,))]

    # ---- strategy (baseline shadow trades) -----------------------------------------------------
    def baseline_trades(self, since: int | None) -> list[sqlite3.Row]:
        if not self.baseline_id:
            return []
        return self.q("SELECT * FROM trades WHERE book = 'exploration' AND variant_id = ? AND taken = 1 AND status = 'closed'"
                      " AND entry_time >= ? ORDER BY entry_time", (self.baseline_id, since or 0))

    def strategy(self, period: str) -> dict[str, Any]:
        since = self.period_start(period)
        rows = self.baseline_trades(since)
        r = [t["r_net"] for t in rows]
        out = stats(r)
        out["r_values"] = r
        mean = out["expectancy_r"]
        if len(r) > 1 and mean is not None:
            half = 1.96 * statistics.stdev(r) / math.sqrt(len(r))
            out["ci"] = (mean - half, mean + half)
        else:
            out["ci"] = None
        windows = [sum(r[i:i + 50]) / 50 for i in range(0, len(r) - 49)] if len(r) >= 50 else []
        out["positive_windows"] = sum(1 for w in windows if w > 0) / len(windows) if windows else None
        cumulative, total = [], 0.0
        for t in sorted(rows, key=lambda row: (row["exit_time"], row["id"])):
            total += t["r_net"]
            cumulative.append((t["exit_time"], total))
        out["cumulative_r"] = cumulative
        return out

    def period_start(self, period: str) -> int | None:
        if period == "forward":
            return self.forward_start or now_ms()
        if period == "30d":
            return now_ms() - 30 * DAY
        if period == "7d":
            return now_ms() - 7 * DAY
        return None

    def breakdowns(self, period: str) -> dict[str, list[dict[str, Any]]]:
        rows = self.baseline_trades(self.period_start(period))
        groups: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for t in rows:
            ctx = json.loads(t["context_json"] or "{}")
            trend = "bull" if t["side"] == "long" else "bear"
            hour = time.gmtime(t["entry_time"] / 1000).tm_hour
            groups["Coin"][t["symbol"]].append(t["r_net"])
            groups["Timeframe"][t["timeframe"]].append(t["r_net"])
            groups["Side"][t["side"]].append(t["r_net"])
            groups["Hour (UTC)"][f"{hour // 3 * 3:02d}-{hour // 3 * 3 + 3:02d}"].append(t["r_net"])
            for name in ("1h", "4h"):
                state = (ctx.get("htf") or {}).get(name)
                label = "missing" if state is None else "with trend" if state == trend else "against trend"
                groups[f"{name} trend"][label].append(t["r_net"])
            groups["Exit"][t["exit_reason"] or "-"].append(t["r_net"])
        return {name: [{"group": key, **stats(vals)} for key, vals in sorted(g.items())] for name, g in groups.items()}

    def variants(self) -> list[dict[str, Any]]:
        def build():
            split = baseline_median_entry(self.conn)
            rows = variant_report(self.conn, split_time=split)
            fwd = self.forward_start or now_ms()
            forward = {r[0]: (r[1], r[2]) for r in self.q(
                "SELECT variant_id, count(*), avg(r_net) FROM trades WHERE book = 'exploration' AND taken = 1"
                " AND status = 'closed' AND entry_time >= ? GROUP BY variant_id", (fwd,))}
            base = next((r for r in rows if r["role"] == "baseline"), None)
            for r in rows:
                r["name"] = r["variant"].rsplit("-", 1)[0]
                r["forward_trades"], r["forward_expectancy_r"] = forward.get(r["variant"], (0, None))
                r["delta_r"] = (r["expectancy_r"] - base["expectancy_r"]) if base and r["expectancy_r"] is not None \
                    and base["expectancy_r"] is not None else None
            return rows
        return self.cached("variants", 30, build)

    def gate(self) -> dict[str, Any]:
        return self.cached("gate", 20, lambda: account_report(self.conn, self.settings))

    def preview(self, rules: PaperAccountConfig, period: str) -> dict[str, Any]:
        return live_preview(self.conn, self.settings, rules, since=self.period_start(period))

    # ---- activity ----------------------------------------------------------------------------
    def today(self) -> dict[str, Any]:
        start = day_start(now_ms())
        base = self.baseline_id
        return {
            "snapshots": self.one("SELECT count(*) FROM snapshots WHERE source = 'live' AND read_at >= ?", (start,)) or 0,
            "signals": self.one("SELECT count(*) FROM trades WHERE book = 'exploration' AND variant_id = ? AND entry_time >= ?",
                                (base, start)) or 0,
            "paper_opened": self.one("SELECT count(*) FROM account_trades WHERE account = ? AND status != 'rejected'"
                                     " AND entry_time >= ?", (ACCOUNT, start)) or 0,
            "paper_closed": self.one("SELECT count(*) FROM account_trades WHERE account = ? AND status = 'closed'"
                                     " AND exit_time >= ?", (ACCOUNT, start)) or 0,
            "shadow_opened": self.one("SELECT count(*) FROM trades WHERE book = 'exploration' AND entry_time >= ?", (start,)) or 0,
            "shadow_closed": self.one("SELECT count(*) FROM trades WHERE book = 'exploration' AND status = 'closed'"
                                      " AND exit_time >= ?", (start,)) or 0,
        }

    def feed(self, limit: int = 25) -> list[dict[str, Any]]:
        items = []
        for r in self.q("SELECT a.*, t.target FROM account_trades a JOIN trades t ON t.id = a.trade_id"
                        " WHERE a.account = ? AND a.status != 'rejected' ORDER BY a.id DESC LIMIT ?", (ACCOUNT, limit)):
            items.append({"ts": r["entry_time"], "kind": "open", "icon": "login",
                          "text": f"Demo {r['side']} {r['symbol']} {r['timeframe']} opened at {r['entry_fill']:g}"})
            if r["status"] == "closed":
                items.append({"ts": r["exit_time"], "kind": "win" if r["pnl_usd"] > 0 else "loss", "icon": "logout",
                              "text": f"Demo {r['symbol']} {r['timeframe']} closed ({r['exit_reason']}): "
                                      f"{r['r_net']:+.2f}R, {r['pnl_usd']:+.2f} USDT"})
        for r in self.q("SELECT ts, level, source, message FROM events WHERE level IN ('WARNING', 'ERROR')"
                        " ORDER BY ts DESC LIMIT ?", (limit,)):
            items.append({"ts": r["ts"], "kind": r["level"].lower(), "icon": "warning" if r["level"] == "WARNING" else "error",
                          "text": f"{r['source']}: {r['message']}"})
        for r in self.q("SELECT ts, key, old_json, new_json FROM settings_audit ORDER BY id DESC LIMIT 10"):
            items.append({"ts": r["ts"], "kind": "setting", "icon": "tune",
                          "text": f"Setting {r['key']}: {r['old_json']} → {r['new_json']}"})
        return sorted(items, key=lambda i: i["ts"] or 0, reverse=True)[:limit]

    # ---- trades ------------------------------------------------------------------------------
    def paper_trades(self, coin: str | None, tf: str | None, result: str | None, since: int | None,
                     include_rejected: bool) -> list[dict[str, Any]]:
        clauses, params = ["a.account = ?"], [ACCOUNT]
        if not include_rejected:
            clauses.append("a.status != 'rejected'")
        for col, val in (("a.symbol", coin), ("a.timeframe", tf)):
            if val:
                clauses.append(f"{col} = ?")
                params.append(val)
        if since:
            clauses.append("a.entry_time >= ?")
            params.append(since)
        if result == "win":
            clauses.append("a.pnl_usd > 0")
        elif result == "loss":
            clauses.append("a.pnl_usd <= 0")
        elif result == "open":
            clauses.append("a.status = 'open'")
        rows = self.q("SELECT a.*, t.target FROM account_trades a JOIN trades t ON t.id = a.trade_id WHERE "
                      + " AND ".join(clauses) + " ORDER BY a.entry_time DESC LIMIT 500", tuple(params))
        return [{"id": r["id"], "trade_id": r["trade_id"], "time": r["entry_time"], "coin": r["symbol"], "tf": r["timeframe"],
                 "side": r["side"], "status": r["status"], "entry": r["entry_fill"], "stop": r["stop"], "target": r["target"],
                 "exit_time": r["exit_time"], "exit": r["exit_reason"] or (r["reject_reason"] or ""),
                 "r": r["r_net"], "pnl": r["pnl_usd"], "fees": r["fees_usd"], "size": r["notional"]} for r in rows]

    def shadow_trades(self, coin: str | None, tf: str | None, variant: str | None, result: str | None,
                      since: int | None, taken: str | None) -> list[dict[str, Any]]:
        clauses, params = ["book = 'exploration'"], []
        for col, val in (("symbol", coin), ("timeframe", tf), ("variant_id", variant)):
            if val:
                clauses.append(f"{col} = ?")
                params.append(val)
        if since:
            clauses.append("entry_time >= ?")
            params.append(since)
        if taken == "taken":
            clauses.append("taken = 1")
        elif taken == "filtered":
            clauses.append("taken = 0")
        if result == "win":
            clauses.append("r_net > 0")
        elif result == "loss":
            clauses.append("r_net <= 0")
        elif result == "open":
            clauses.append("status = 'open'")
        rows = self.q("SELECT id, variant_id, symbol, timeframe, side, entry_time, entry_ref, stop_initial, target, status,"
                      " exit_time, exit_reason, r_net, taken, reason FROM trades WHERE " + " AND ".join(clauses)
                      + " ORDER BY entry_time DESC LIMIT 500", tuple(params))
        return [{"id": r["id"], "trade_id": r["id"], "time": r["entry_time"], "variant": r["variant_id"].rsplit("-", 1)[0],
                 "coin": r["symbol"], "tf": r["timeframe"], "side": r["side"], "status": r["status"], "entry": r["entry_ref"],
                 "stop": r["stop_initial"], "target": r["target"], "exit_time": r["exit_time"], "exit": r["exit_reason"] or "",
                 "r": r["r_net"], "taken": "taken" if r["taken"] else f"filtered: {r['reason']}"} for r in rows]

    def trade_detail(self, trade_id: int) -> dict[str, Any] | None:
        t = self.conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if t is None:
            return None
        ctx = json.loads(t["context_json"] or "{}")
        state = json.loads(t["state_json"] or "{}")
        paper = self.conn.execute("SELECT * FROM account_trades WHERE trade_id = ? AND account = ?", (trade_id, ACCOUNT)).fetchone()
        end = t["exit_time"] or now_ms()
        span = end - t["entry_time"]
        tf = "1m" if span <= 4 * 3_600_000 else "5m" if span <= 20 * 3_600_000 else "15m"
        step = tf_ms(tf)
        candles = [tuple(r) for r in self.q(
            "SELECT open_time, open, close, low, high FROM candles WHERE symbol = ? AND timeframe = ? AND open_time BETWEEN ? AND ?"
            " ORDER BY open_time", (t["symbol"], tf, t["entry_time"] - 40 * step, end + 20 * step))]
        return {"trade": dict(t), "context": ctx, "legs": state.get("legs", []), "paper": dict(paper) if paper else None,
                "candles": candles, "candle_tf": tf, "variant": t["variant_id"],
                "params": json.loads(self.one("SELECT params_json FROM variants WHERE id = ?", (t["variant_id"],)) or "{}")}

    def choices(self) -> dict[str, list[str]]:
        return {"coins": list(self.settings.exchange.symbols), "timeframes": list(self.settings.timeframes.trade),
                "variants": [r[0] for r in self.q("SELECT id FROM variants WHERE role != 'retired'"
                                                  " ORDER BY CASE role WHEN 'baseline' THEN 0 ELSE 1 END, id")]}

    # ---- learning ----------------------------------------------------------------------------
    def learning(self) -> dict[str, Any]:
        def build():
            root = self.defaults.root
            docs = []
            for path in sorted((root / "docs" / "research").glob("*.md"), reverse=True):
                text = path.read_text(encoding="utf-8")
                title = next((line[2:] for line in text.splitlines() if line.startswith("# ")), path.stem)
                docs.append({"title": title, "file": path.name, "text": text})
            lessons_path = root / "research" / "lessons.md"
            return {
                "baseline": self.baseline_params(),
                "history": [dict(r) for r in self.q("SELECT * FROM baseline_history ORDER BY adopted_at")],
                "docs": docs,
                "decisions": self.decision_log(root / "docs" / "REQUIREMENTS.md"),
                "lessons": lessons_path.read_text(encoding="utf-8") if lessons_path.exists() else None,
                "tested": {"variants": self.one("SELECT count(*) FROM variants") or 0,
                           "active": self.one("SELECT count(*) FROM variants WHERE role != 'retired'") or 0,
                           "shadow_trades": self.one("SELECT count(*) FROM trades WHERE book = 'exploration'") or 0,
                           "snapshots": self.one("SELECT count(*) FROM snapshots") or 0},
            }
        return self.cached("learning", 60, build)

    def baseline_params(self) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT id, params_json FROM variants WHERE role = 'baseline'").fetchone()
        return {"id": row["id"], "params": json.loads(row["params_json"])} if row else None

    @staticmethod
    def decision_log(path: Path) -> list[dict[str, str]]:
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        section = text.split("## 5. Decision log", 1)[-1]
        rows = []
        for line in section.splitlines():
            m = re.match(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(.+?)\s*\|$", line)
            if m:
                rows.append({"date": m.group(1), "text": m.group(2)})
        return rows[::-1]

    # ---- system ------------------------------------------------------------------------------
    def log_lines(self, level: str, search: str, limit: int = 400) -> list[str]:
        path = self.defaults.resolve(self.defaults.logging.file)
        if not path.exists():
            return []
        with path.open(encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()[-5000:]
        order = ["DEBUG", "INFO", "WARNING", "ERROR"]
        wanted = order[order.index(level):] if level in order else order
        out = [ln.rstrip() for ln in lines if any(f" {lv} " in ln[:40] or f" {lv}  " in ln[:40] for lv in wanted)
               and (not search or search.lower() in ln.lower())]
        return out[-limit:]

    def events(self, level: str | None, source: str | None, limit: int = 300) -> list[dict[str, Any]]:
        clauses, params = ["1 = 1"], []
        if level:
            clauses.append("level = ?")
            params.append(level)
        if source:
            clauses.append("source = ?")
            params.append(source)
        return [dict(r) for r in self.q("SELECT ts, level, source, message FROM events WHERE " + " AND ".join(clauses)
                                        + " ORDER BY ts DESC LIMIT ?", (*params, limit))]

    def coverage(self, hours: float) -> list[dict[str, Any]]:
        end = now_ms()
        return coverage(self.conn, self.settings.exchange.symbols, self.settings.all_timeframes, end - int(hours * 3_600_000), end)

    def gaps(self) -> list[dict[str, Any]]:
        end = now_ms()
        out = []
        for symbol in self.settings.exchange.symbols:
            for first, last in find_gaps(self.conn, symbol, "1m", end - 2 * DAY, end):
                out.append({"symbol": symbol, "from": first, "to": last, "minutes": (last - first) // 60_000 + 1})
        return out

    def indicator_versions(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.q("SELECT signal_version, settings_hash, created_at FROM indicator_settings"
                                        " ORDER BY signal_version DESC")]

    def resources_history(self) -> list[tuple[int, dict[str, Any]]]:
        return [(r["ts"], json.loads(r["data_json"])) for r in self.q(
            "SELECT ts, data_json FROM events WHERE source = 'resources' AND ts >= ? ORDER BY ts", (now_ms() - 7 * DAY,))]
