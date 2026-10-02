"""Setup engine: turns snapshots into setups and exploration trades, for every variant.

For each closed trading-timeframe candle (in time order, once):
1. A trigger flag starts a pending setup (and cancels pending setups on the other side).
2. A pending setup confirms on the first candle within its window that passes the confirmation rules,
   or expires when the window is over.
3. A confirmed setup becomes a trade: entry at the Binance 1m open right after the confirming candle
   closes, stop from the last N candles, filters checked. A trade that fails a filter is still simulated
   as a counterfactual (taken = 0) so the value of every filter can be measured.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from typing import Any

from tradeagent.config import Settings
from tradeagent.journal.db import now_ms
from tradeagent.market.candles import tf_ms
from tradeagent.setups.config import SetupParams, Variant
from tradeagent.sim.simulator import Costs, open_trade

log = logging.getLogger("tradeagent.engine")

BOOK = "exploration"


def costs_from(settings: Settings) -> Costs:
    return Costs(settings.costs.maker_fee, settings.costs.taker_fee, settings.costs.slippage)


def zerolag_trend(values: dict[str, Any]) -> str | None:
    """Zero Lag draws only the lower band in a bullish trend and only the upper band in a bearish one."""
    zl = values.get("zerolag") or {}
    if zl.get("lower_band") is not None:
        return "bull"
    if zl.get("upper_band") is not None:
        return "bear"
    return None


class SetupEngine:
    def __init__(self, settings: Settings, variants: list[Variant], conn: sqlite3.Connection) -> None:
        self.settings = settings
        self.variants = variants
        self.conn = conn
        self.costs = costs_from(settings)
        self.timeframes = sorted({tf for v in variants for tf in v.params.timeframes}, key=tf_ms)

    def _get_state(self, key: str) -> int:
        row = self.conn.execute("SELECT value FROM engine_state WHERE key = ?", (key,)).fetchone()
        return int(row[0]) if row else 0

    def _set_state(self, key: str, value: int) -> None:
        self.conn.execute(
            "INSERT INTO engine_state (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )

    def process(self) -> Counter[str]:
        """Handle every new snapshot whose entry candle is available. Safe to call repeatedly."""
        counts: Counter[str] = Counter()
        for symbol in self.settings.exchange.symbols:
            newest_1m = self.conn.execute(
                "SELECT max(open_time) FROM candles WHERE symbol = ? AND timeframe = '1m'", (symbol,)
            ).fetchone()[0]
            if newest_1m is None:
                continue
            for tf in self.timeframes:
                step = tf_ms(tf)
                key = f"engine:{symbol}:{tf}"
                rows = self.conn.execute(
                    """
                    SELECT s.id, s.bar_time, s.open, s.high, s.low, s.close, s.values_json, s.signal_version
                    FROM snapshots s
                    WHERE s.symbol = ? AND s.timeframe = ? AND s.bar_time > ? AND s.problems_json IS NULL
                      AND s.signal_version = (SELECT max(x.signal_version) FROM snapshots x
                                              WHERE x.symbol = s.symbol AND x.timeframe = s.timeframe
                                                AND x.bar_time = s.bar_time AND x.problems_json IS NULL)
                    ORDER BY s.bar_time
                    """,
                    (symbol, tf, self._get_state(key)),
                ).fetchall()
                for row in rows:
                    entry_time = row["bar_time"] + step
                    if entry_time > newest_1m:
                        break  # wait until the entry candle is closed and synced
                    entry = self.conn.execute(
                        "SELECT open FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time = ?",
                        (symbol, entry_time),
                    ).fetchone()
                    with self.conn:  # one transaction per candle: restart-safe
                        if entry is None:
                            counts["no_entry_candle"] += 1
                        else:
                            for v in self.variants:
                                if tf in v.params.timeframes:
                                    self._on_candle(v, symbol, tf, row, entry["open"], counts)
                        self._set_state(key, row["bar_time"])
                    counts["candles"] += 1
        return counts

    def _on_candle(self, v: Variant, symbol: str, tf: str, row: sqlite3.Row, entry_ref: float, counts: Counter[str]) -> None:
        p = v.params
        values = json.loads(row["values_json"])
        trigger_values = values.get(p.trigger.indicator) or {}
        for side, field in (("long", p.trigger.long), ("short", p.trigger.short)):
            if trigger_values.get(field) == 1:
                opposite = "short" if side == "long" else "long"
                self.conn.execute(
                    "UPDATE setups SET status = 'cancelled'"
                    " WHERE variant_id = ? AND symbol = ? AND timeframe = ? AND side = ? AND status = 'pending'",
                    (v.id, symbol, tf, opposite),
                )
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO setups (variant_id, symbol, timeframe, side, trigger_time, status, signal_version)"
                    " VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                    (v.id, symbol, tf, side, row["bar_time"], row["signal_version"]),
                )
                counts["triggers"] += cur.rowcount

        step = tf_ms(tf)
        pending = self.conn.execute(
            "SELECT id, side, trigger_time FROM setups"
            " WHERE variant_id = ? AND symbol = ? AND timeframe = ? AND status = 'pending' ORDER BY trigger_time",
            (v.id, symbol, tf),
        ).fetchall()
        for setup in pending:
            if row["bar_time"] > setup["trigger_time"] + p.confirmation.window * step:
                self.conn.execute("UPDATE setups SET status = 'expired' WHERE id = ?", (setup["id"],))
                counts["expired"] += 1
            elif self._confirmed(p, setup["side"], values, row):
                self._open_trade(v, setup, symbol, tf, row, values, entry_ref, counts)
                self.conn.execute(
                    "UPDATE setups SET status = 'confirmed', confirm_time = ? WHERE id = ?", (row["bar_time"], setup["id"])
                )

    @staticmethod
    def _confirmed(p: SetupParams, side: str, values: dict[str, Any], row: sqlite3.Row) -> bool:
        if p.confirmation.klinger:
            hist = (values.get("klinger") or {}).get("hist")
            if hist is None or (side == "long" and hist < 0) or (side == "short" and hist >= 0):
                return False
        if p.confirmation.candle_direction:
            if side == "long" and not row["close"] > row["open"]:
                return False
            if side == "short" and not row["close"] < row["open"]:
                return False
        return True

    def _htf_trend(self, symbol: str, timeframe: str, at: int) -> str | None:
        """Zero Lag trend of the newest closed higher-timeframe candle at `at` (None if missing or stale)."""
        step = tf_ms(timeframe)
        row = self.conn.execute(
            "SELECT bar_time, values_json FROM snapshots WHERE symbol = ? AND timeframe = ? AND problems_json IS NULL"
            " AND bar_time + ? <= ? ORDER BY bar_time DESC LIMIT 1",
            (symbol, timeframe, step, at),
        ).fetchone()
        if row is None or at - (row["bar_time"] + step) > step:
            return None
        return zerolag_trend(json.loads(row["values_json"]))

    def _open_trade(
        self, v: Variant, setup: sqlite3.Row, symbol: str, tf: str, row: sqlite3.Row,
        values: dict[str, Any], entry_ref: float, counts: Counter[str],
    ) -> None:
        p = v.params
        side = setup["side"]
        sign = 1 if side == "long" else -1
        trend = "bull" if side == "long" else "bear"
        entry_time = row["bar_time"] + tf_ms(tf)

        problems: list[str] = []
        stop: float | None = None
        recent = self.conn.execute(
            "SELECT high, low FROM candles WHERE symbol = ? AND timeframe = ? AND open_time <= ?"
            " ORDER BY open_time DESC LIMIT ?",
            (symbol, tf, row["bar_time"], p.stop.lookback),
        ).fetchall()
        if len(recent) < p.stop.lookback:
            problems.append("not enough candles for the stop")
        else:
            stop = min(c["low"] for c in recent) if sign > 0 else max(c["high"] for c in recent)
            if sign * (entry_ref - stop) <= 0:
                problems.append("stop on the wrong side of the entry")

        htf = {name: self._htf_trend(symbol, name, entry_time) for name in ("1h", "4h")}
        failed: list[str] = []
        if p.filters.vwap:
            vwap = (values.get("vwap") or {}).get("vwap")
            if vwap is None or sign * (row["close"] - vwap) < 0:
                failed.append("vwap")
        if p.filters.macd_trend:
            macd = (values.get("atp_macd") or {}).get("macd")
            if macd is None or sign * macd <= 0:
                failed.append("macd_trend")
        if p.filters.htf != "none":
            needed = ["1h"] if p.filters.htf == "1h" else ["1h", "4h"]
            if any(htf[name] != trend for name in needed):
                failed.append(f"htf_{p.filters.htf}")
        if p.filters.min_stop_pct > 0 and stop is not None and abs(entry_ref - stop) / entry_ref * 100 < p.filters.min_stop_pct:
            failed.append("min_stop_pct")

        mode = p.exit.mode
        if mode == "htf_rule":
            mode = "hybrid" if htf["1h"] == trend and htf["4h"] == trend else "fixed"
        context = {
            "values": values,
            "candle": [row["open"], row["high"], row["low"], row["close"]],
            "htf": htf,
            "filters_failed": failed,
            "snapshot_id": row["id"],
            "params_hash": v.params_hash,
        }
        if problems:
            status, taken, reason, state, target = "invalid", 0, "; ".join(problems), {}, None
            stop_value = stop if stop is not None else entry_ref
        else:
            assert stop is not None
            sim = open_trade(
                side=side, mode=mode, entry_time=entry_time, entry_ref=entry_ref, stop=stop,
                take_profit_r=p.exit.take_profit_r, partial_r=p.exit.partial_r,
                partial_fraction=p.exit.partial_fraction, trail_lookback=p.exit.trail_lookback, costs=self.costs,
            )
            status, taken, reason, state, target = "open", int(not failed), ", ".join(failed) or None, sim.to_json(), sim.target
            stop_value = stop
        now = now_ms()
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO trades (book, variant_id, symbol, timeframe, side, setup_id, signal_version,
                trigger_time, confirm_time, entry_time, taken, reason, exit_mode, entry_ref, stop_initial, target,
                status, context_json, state_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                BOOK, v.id, symbol, tf, side, setup["id"], row["signal_version"], setup["trigger_time"],
                row["bar_time"], entry_time, taken, reason, mode, entry_ref, stop_value, target, status,
                json.dumps(context, sort_keys=True), json.dumps(state), now, now,
            ),
        )
        if cur.rowcount:
            kind = "invalid" if status == "invalid" else ("taken" if taken else "counterfactual")
            counts[f"trades_{kind}"] += 1
