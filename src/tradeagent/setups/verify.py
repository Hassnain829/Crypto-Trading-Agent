"""Independent re-computation of shadow trades from raw data (Phase 2 exit check).

Deliberately does NOT use the simulator or the engine: it re-derives trigger, confirmation, entry,
stop, target, exit and net R straight from the journal's snapshots, candles and funding rates, so a
bug in the engine or simulator shows up as a mismatch.
"""

from __future__ import annotations

import json
import math
import sqlite3
from typing import Any

from tradeagent.config import Settings
from tradeagent.market.candles import tf_ms


def _snapshot_values(conn: sqlite3.Connection, symbol: str, tf: str, bar_time: int) -> tuple[dict[str, Any], sqlite3.Row] | None:
    row = conn.execute(
        "SELECT open, close, values_json FROM snapshots WHERE symbol = ? AND timeframe = ? AND bar_time = ?"
        " AND problems_json IS NULL ORDER BY signal_version DESC LIMIT 1",
        (symbol, tf, bar_time),
    ).fetchone()
    return (json.loads(row["values_json"]), row) if row else None


def verify_trade(conn: sqlite3.Connection, settings: Settings, trade: sqlite3.Row) -> list[str]:
    """Return the list of mismatches (empty = the trade is exactly what the rules and the data say)."""
    issues: list[str] = []
    p = json.loads(conn.execute("SELECT params_json FROM variants WHERE id = ?", (trade["variant_id"],)).fetchone()[0])
    symbol, tf, side = trade["symbol"], trade["timeframe"], trade["side"]
    sign = 1 if side == "long" else -1
    step = tf_ms(tf)
    close_enough = lambda a, b: math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)  # noqa: E731

    trig = _snapshot_values(conn, symbol, tf, trade["trigger_time"])
    field = p["trigger"]["long" if side == "long" else "short"]
    if trig is None or (trig[0].get(p["trigger"]["indicator"]) or {}).get(field) != 1:
        issues.append(f"no {p['trigger']['indicator']}.{field} flag on the trigger candle")

    conf = _snapshot_values(conn, symbol, tf, trade["confirm_time"])
    if conf is None:
        issues.append("no snapshot for the confirming candle")
    else:
        values, row = conf
        hist = (values.get("klinger") or {}).get("hist")
        if p["confirmation"]["klinger"] and (hist is None or (hist >= 0) != (side == "long")):
            issues.append(f"Klinger histogram {hist} does not confirm a {side}")
        if p["confirmation"]["candle_direction"] and not sign * (row["close"] - row["open"]) > 0:
            issues.append("confirming candle points the wrong way")
    if not 0 <= trade["confirm_time"] - trade["trigger_time"] <= p["confirmation"]["window"] * step:
        issues.append("confirmation outside the window")

    if trade["entry_time"] != trade["confirm_time"] + step:
        issues.append("entry is not right after the confirming candle")
    entry = conn.execute(
        "SELECT open FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time = ?", (symbol, trade["entry_time"])
    ).fetchone()
    if entry is None or not close_enough(entry["open"], trade["entry_ref"]):
        issues.append(f"entry {trade['entry_ref']} != Binance 1m open {entry['open'] if entry else None}")

    recent = conn.execute(
        "SELECT high, low FROM candles WHERE symbol = ? AND timeframe = ? AND open_time <= ? ORDER BY open_time DESC LIMIT ?",
        (symbol, tf, trade["confirm_time"], p["stop"]["lookback"]),
    ).fetchall()
    stop = min(r["low"] for r in recent) if sign > 0 else max(r["high"] for r in recent)
    if not close_enough(stop, trade["stop_initial"]):
        issues.append(f"stop {trade['stop_initial']} != {stop} from the last {p['stop']['lookback']} candles")
    risk = abs(trade["entry_ref"] - stop)
    target = trade["entry_ref"] + sign * p["exit"]["take_profit_r"] * risk
    if trade["exit_mode"] != "fixed":
        return issues + ["only fixed-exit trades are re-simulated"]
    if not close_enough(target, trade["target"]):
        issues.append(f"target {trade['target']} != {target}")

    # Walk the 1m candles: stop first, then target (conservative), until the time limit.
    max_hold = int(settings.shadow.max_hold_hours * 3_600_000)
    exit_time = exit_ref = reason = None
    for c in conn.execute(
        "SELECT open_time, open, high, low, close FROM candles WHERE symbol = ? AND timeframe = '1m'"
        " AND open_time >= ? ORDER BY open_time",
        (symbol, trade["entry_time"]),
    ):
        if c["open_time"] - trade["entry_time"] >= max_hold:
            exit_time, exit_ref, reason = c["open_time"], c["open"], "timeout"
            break
        if (c["low"] <= stop) if sign > 0 else (c["high"] >= stop):
            gapped = (c["open"] <= stop) if sign > 0 else (c["open"] >= stop)
            exit_time, exit_ref, reason = c["open_time"], c["open"] if gapped else stop, "stop"
            break
        if (c["high"] >= target) if sign > 0 else (c["low"] <= target):
            exit_time, exit_ref, reason = c["open_time"], target, "target"
            break
    if reason != trade["exit_reason"] or exit_time != trade["exit_time"]:
        issues.append(f"exit {trade['exit_reason']} at {trade['exit_time']} != {reason} at {exit_time}")
        return issues

    costs = settings.costs
    entry_fill = trade["entry_ref"] * (1 + sign * costs.slippage)
    market_exit = reason != "target"
    exit_fill = exit_ref * (1 - sign * costs.slippage) if market_exit else exit_ref
    fees = entry_fill * costs.taker_fee + exit_fill * (costs.taker_fee if market_exit else costs.maker_fee)
    funding = 0.0
    for f in conn.execute(
        "SELECT funding_time, rate FROM funding WHERE symbol = ? AND funding_time > ? AND funding_time <= ?",
        (symbol, trade["entry_time"], exit_time),
    ):
        price = conn.execute(
            "SELECT open FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time >= ? ORDER BY open_time LIMIT 1",
            (symbol, f["funding_time"]),
        ).fetchone()["open"]
        funding += sign * f["rate"] * price
    r_net = (sign * (exit_fill - entry_fill) - fees - funding) / risk
    if not math.isclose(r_net, trade["r_net"], rel_tol=1e-6, abs_tol=1e-9):
        issues.append(f"net R {trade['r_net']:.6f} != {r_net:.6f}")
    return issues
