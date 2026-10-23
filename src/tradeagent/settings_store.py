"""Settings edited in the dashboard: stored as overrides in the journal on top of config/settings.yaml.

Every change is validated with the same pydantic models as settings.yaml and written to settings_audit
(time, field, old -> new, source). The agent re-applies the overrides at the start of every cycle, so the
fields marked `live` take effect without a restart; the others apply when the agent starts.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from tradeagent.config import Settings
from tradeagent.journal.db import now_ms
from tradeagent.venues import VENUES

PREFIX = "cfg:"


@dataclass(frozen=True)
class EditableField:
    path: str  # section.key in settings.yaml
    label: str
    kind: str  # money | percent | optpercent | int | optint | float | bool | select | time | coins
    help: str = ""
    live: bool = True  # takes effect in the next agent cycle (False: on the next agent start)
    choices: tuple[str, ...] = field(default_factory=tuple)
    step: float | None = None
    labels: tuple[tuple[str, str], ...] = ()  # select: (value, label) shown instead of the value


TIMEZONES = (
    ("system", "Same as this computer"), ("Etc/UTC", "UTC"), ("Asia/Karachi", "Pakistan (UTC+5)"),
    ("Asia/Dubai", "Dubai (UTC+4)"), ("Asia/Kolkata", "India (UTC+5:30)"), ("Asia/Singapore", "Singapore (UTC+8)"),
    ("Europe/London", "London"), ("Europe/Berlin", "Central Europe"), ("America/New_York", "New York"),
)

_ACCOUNT = "Demo account (takes every signal unless you set limits)"
_LIVE = "Live limits (used for live trading and the live preview)"

FIELDS: tuple[EditableField, ...] = (
    EditableField("paper_account.starting_balance", "Starting balance", "money",
          "Used when the demo account is reset (paper-reset).", live=False),
    EditableField("paper_account.risk_per_trade", "Risk per trade", "percent", "Share of the balance risked on each trade."),
    EditableField("paper_account.risk_tier_a", "Risk on quality-A trades", "optpercent",
                  "Trades confirmed by a 15m Trendline breakout. Empty = the normal risk for every trade."),
    EditableField("paper_account.max_open_risk", "Max open risk", "optpercent",
                  "All open positions together may lose at most this share of the balance at their stops. A trade that "
                  "would go over it is made smaller, not skipped. Empty = no budget."),
    EditableField("paper_account.leverage_cap", "Leverage cap", "float", "Positions are sized down to fit the margin at this leverage."),
    EditableField("paper_account.max_positions", "Max open positions", "optint", "Empty = no limit."),
    EditableField("paper_account.max_positions_per_coin", "Max positions per coin", "optint", "Empty = no limit."),
    EditableField("paper_account.symbols", "Coins traded", "coins",
          "The demo account trades only these coins. The shadow book keeps testing every coin."),
    EditableField("paper_account.daily_loss_stop", "Daily loss stop", "optpercent",
          "Stops new entries for the rest of the UTC day after this loss. Empty = off."),
    EditableField("paper_account.allow_opposite", "Allow long and short on one coin", "bool",
                  "Off: a signal against a coin's open position is skipped (no hedged pairs)."),
    EditableField("paper_account.first_position_always", "First position per coin always allowed", "bool",
                  "On: 'Max open positions' never blocks a coin that has no position yet."),
    EditableField("paper_account.drawdown_brake", "Drawdown brake", "optpercent",
                  "While the balance is this far below its highest balance, every trade risks less (see the next "
                  "field), until a new high. Empty = off."),
    EditableField("paper_account.brake_factor", "Risk under the brake", "percent",
                  "Share of the normal risk while the drawdown brake is on (50% = half)."),
    EditableField("live_account.starting_balance", "Live balance", "money", "Balance the live preview starts with."),
    EditableField("live_account.symbols", "Coins traded live", "coins", "Live trading (and the live preview) uses only these coins."),
    EditableField("live_account.risk_per_trade", "Risk per trade", "percent"),
    EditableField("live_account.max_open_risk", "Max open risk", "optpercent",
                  "Open positions together lose at most this share at their stops; bigger trades are made smaller."),
    EditableField("live_account.leverage_cap", "Leverage cap", "float"),
    EditableField("live_account.max_positions", "Max open positions", "optint", "Empty = no limit."),
    EditableField("live_account.max_positions_per_coin", "Max positions per coin", "optint", "Empty = no limit."),
    EditableField("live_account.daily_loss_stop", "Daily loss stop", "optpercent", "Empty = off."),
    EditableField("live_account.allow_opposite", "Allow long and short on one coin", "bool"),
    EditableField("live_account.first_position_always", "First position per coin always allowed", "bool"),
    EditableField("live_account.drawdown_brake", "Drawdown brake", "optpercent", "Empty = off."),
    EditableField("live_account.brake_factor", "Risk under the brake", "percent"),
    EditableField("costs.maker_fee", "Maker fee", "percent", "Limit orders.", live=False, step=0.001),
    EditableField("costs.taker_fee", "Taker fee", "percent", "Market orders and stops.", live=False, step=0.001),
    EditableField("costs.slippage", "Slippage", "percent", "Added to every market fill.", live=False, step=0.001),
    EditableField("goal.min_trades", "Strategy trades", "int", "Forward shadow trades of the baseline needed."),
    EditableField("goal.min_days", "Days running", "int"),
    EditableField("goal.min_expectancy_r", "Expectancy (R per trade)", "float", step=0.01),
    EditableField("goal.min_edge_lower_r", "Edge lower bound (R, 90%)", "float",
                  "The expectancy must beat this with 90% confidence. Trades of one market move are resampled together.",
                  step=0.01),
    EditableField("goal.min_profit_factor", "Profit factor", "float", step=0.05),
    EditableField("goal.max_drawdown", "Max drawdown", "percent", "Checked on the live preview."),
    EditableField("goal.min_snapshot_coverage", "Snapshot coverage", "percent", "Live TradingView reads in the last 7 days."),
    EditableField("tradingview.draw_trades", "Draw demo trades on the charts", "bool",
          "Entry, stop, target and result on the AGENT charts, synced to every layout."),
    EditableField("tradingview.timezone", "Time zone", "select",
          "Time axis of the AGENT charts and the times on this dashboard. 'Same as this computer' follows the "
          "PC or VPS. Display only: candles, signals and stored times (UTC) do not change.",
          choices=tuple(v for v, _ in TIMEZONES), labels=TIMEZONES),
    EditableField("exchange.venue", "Trading exchange", "select",
          "Its prices fill the demo trades, and from Phase 6 it takes the live orders. Signals stay on the TradingView "
          "charts. After a change the agent downloads this exchange's market data again (a few minutes); start a new "
          "forward test afterwards (paper-reset --from-now).",
          live=False, choices=tuple(VENUES), labels=tuple((v.id, v.label) for v in VENUES.values())),
    EditableField("learning.min_trades", "Trades to decide", "int",
          "Closed trades the challenger and the baseline both need in the same period before a verdict."),
    EditableField("learning.min_edge_r", "Edge to win (R per trade)", "float",
          "The challenger's expectancy must beat the baseline's by at least this much.", step=0.01),
    EditableField("learning.max_drawdown_worse", "Drawdown may be worse by", "percent"),
    EditableField("learning.reconfirm_trades", "Fresh trades to confirm", "int",
          "After a first win the challenger must stay ahead on this many new trades."),
    EditableField("learning.max_challengers", "Max challengers", "int"),
    EditableField("learning.auto_promote", "Promote winners to the demo", "bool",
          "A confirmed winner becomes the demo baseline by itself. Live trading always needs your approval."),
    EditableField("learning.screen_on_history", "Screen proposals on history", "bool",
          "A proposal must first beat the baseline in both halves of the stored history."),
    EditableField("learning.long_history_years", "Research history used (years)", "optint",
          "The newest N years of the research history for the long screen and the leaderboard. Empty = all of it."),
    EditableField("learning.screen_on_long_history", "Screen proposals on 4 years", "bool",
          "After the stored history, a proposal must also beat the baseline in both halves of the 4-year research "
          "history (about an hour, in the background). Short histories cannot tell a good rule from a lucky period."),
    EditableField("research.enabled", "Daily research run", "bool", "Claude studies the journal once a day (Phase 5)."),
    EditableField("research.daily_time_utc", "Research time (UTC)", "time"),
    EditableField("alerts.enabled", "Phone alerts", "bool",
                  "Problems (failing reads, the clock, a stopped agent) and notices go to the ntfy app on your phone. "
                  "Needs NTFY_TOPIC in .env."),
    EditableField("alerts.trades", "Demo trade messages", "bool", "A message for every demo trade opened, skipped and closed."),
    EditableField("alerts.status_hours", "Status every (hours)", "optint",
                  "The open positions (entry, SL, TP, price, profit or loss) every N hours, at 00:00 UTC and its multiples, "
                  "when there are any. Write 'status' in the ntfy app for it at any time. Empty = off."),
    EditableField("alerts.failed_cycles", "Alert after failed cycles", "int", "Cycles in a row with failed TradingView reads."),
    EditableField("alerts.stale_minutes", "Agent silent for (minutes)", "float",
                  "The dashboard alerts when the agent has not finished a cycle this long."),
)
BY_PATH = {f.path: f for f in FIELDS}
GROUPS = {
    _ACCOUNT: [f for f in FIELDS if f.path.startswith("paper_account.")],
    _LIVE: [f for f in FIELDS if f.path.startswith("live_account.")],
    "Costs (apply when the agent restarts)": [f for f in FIELDS if f.path.startswith("costs.")],
    "Go-live gate": [f for f in FIELDS if f.path.startswith("goal.")],
    "TradingView": [f for f in FIELDS if f.path.startswith("tradingview.")],
    "Research": [f for f in FIELDS if f.path.startswith("research.") or f.path.startswith("learning.")],
    "Trading exchange (applies when the agent restarts)": [f for f in FIELDS if f.path.startswith("exchange.")],
    "Alerts": [f for f in FIELDS if f.path.startswith("alerts.")],
}


def overrides(conn: sqlite3.Connection) -> dict[str, Any]:
    return {row[0][len(PREFIX):]: json.loads(row[1])
            for row in conn.execute("SELECT key, value_json FROM settings WHERE key LIKE ?", (PREFIX + "%",))}


def current(settings: Settings, path: str) -> Any:
    section, key = path.split(".", 1)
    return getattr(getattr(settings, section), key)


def _with(settings: Settings, values: dict[str, Any]) -> Settings:
    """A copy of `settings` with `values` applied and validated section by section."""
    result = settings.model_copy(deep=True)
    by_section: dict[str, dict[str, Any]] = {}
    for path, value in values.items():
        section, key = path.split(".", 1)
        by_section.setdefault(section, {})[key] = value
    for section, changes in by_section.items():
        model = getattr(result, section)
        setattr(result, section, type(model).model_validate({**model.model_dump(), **changes}))
    return result


def apply_overrides(settings: Settings, conn: sqlite3.Connection) -> list[str]:
    """Apply the stored overrides to `settings` in place. Returns problems (invalid overrides are skipped)."""
    problems = []
    valid: dict[str, Any] = {}
    for path, value in overrides(conn).items():
        if path not in BY_PATH:
            problems.append(f"{path}: not an editable setting")
            continue
        try:
            _with(settings, {**valid, path: value})
            valid[path] = value
        except ValidationError as exc:
            problems.append(f"{path}: {exc.errors()[0]['msg']}")
    if valid:
        updated = _with(settings, valid)
        for section in {p.split(".", 1)[0] for p in valid}:
            setattr(settings, section, getattr(updated, section))
    return problems


def set_value(conn: sqlite3.Connection, settings: Settings, path: str, value: Any, source: str = "dashboard") -> str | None:
    """Validate and store one change (with an audit row). Returns an error message, or None when saved."""
    if path not in BY_PATH:
        return f"{path} cannot be edited"
    try:
        _with(settings, {path: value})
    except ValidationError as exc:
        return exc.errors()[0]["msg"]
    old = current(settings, path)
    if old == value:
        return None
    now = now_ms()
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
            (PREFIX + path, json.dumps(value), now),
        )
        conn.execute("INSERT INTO settings_audit (ts, key, old_json, new_json, source) VALUES (?, ?, ?, ?, ?)",
                     (now, path, json.dumps(old), json.dumps(value), source))
    return None


def reset_value(conn: sqlite3.Connection, settings: Settings, defaults: Settings, path: str, source: str = "dashboard") -> None:
    """Drop the override, so settings.yaml applies again."""
    old, new = current(settings, path), current(defaults, path)
    with conn:
        deleted = conn.execute("DELETE FROM settings WHERE key = ?", (PREFIX + path,)).rowcount
        if deleted:
            conn.execute("INSERT INTO settings_audit (ts, key, old_json, new_json, source) VALUES (?, ?, ?, ?, ?)",
                         (now_ms(), path, json.dumps(old), json.dumps(new), f"{source} (reset to settings.yaml)"))


def audit_log(conn: sqlite3.Connection, limit: int = 200) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT ts, key, old_json, new_json, source FROM settings_audit ORDER BY id DESC LIMIT ?", (limit,))]
