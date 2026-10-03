"""Moves open shadow trades forward on closed 1m candles until they close."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter

from tradeagent.config import Settings
from tradeagent.journal.db import now_ms
from tradeagent.market.candles import tf_ms
from tradeagent.sim.simulator import Costs, TradeState, apply_funding, close_now, results, step, trail

CHUNK = 500  # 1m candles loaded at a time; most trades close within a few hours


class Tracker:
    def __init__(self, settings: Settings, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.costs = Costs(settings.costs.maker_fee, settings.costs.taker_fee, settings.costs.slippage)
        self.max_hold_ms = int(settings.shadow.max_hold_hours * 3_600_000)

    def update(self, book: str = "exploration") -> Counter[str]:
        counts: Counter[str] = Counter()
        open_trades = self.conn.execute(
            "SELECT id, symbol, timeframe, entry_time, state_json FROM trades WHERE book = ? AND status = 'open'",
            (book,),
        ).fetchall()
        for trade in open_trades:
            state = TradeState.from_json(json.loads(trade["state_json"]))
            last_before = state.last_time
            self._advance(trade, state)
            if state.last_time != last_before or state.closed:
                self._save(trade["id"], state)
                counts["closed" if state.closed else "updated"] += 1
        return counts

    def _advance(self, trade: sqlite3.Row, state: TradeState) -> None:
        """Step the trade through every stored 1m candle after its last processed one, in chunks."""
        start = state.last_time + 60_000 if state.last_time is not None else trade["entry_time"]
        settled_until = state.last_time if state.last_time is not None else trade["entry_time"]
        funding = self.conn.execute(
            "SELECT funding_time, rate FROM funding WHERE symbol = ? AND funding_time > ? ORDER BY funding_time",
            (trade["symbol"], settled_until),
        ).fetchall()
        next_funding = 0
        tf_step = tf_ms(trade["timeframe"])
        while not state.closed:
            candles = self.conn.execute(
                "SELECT open_time, open, high, low, close FROM candles"
                " WHERE symbol = ? AND timeframe = '1m' AND open_time >= ? ORDER BY open_time LIMIT ?",
                (trade["symbol"], start, CHUNK),
            ).fetchall()
            for c in candles:
                t = c["open_time"]
                while next_funding < len(funding) and funding[next_funding]["funding_time"] <= t:
                    apply_funding(state, funding[next_funding]["rate"], c["open"])
                    next_funding += 1
                if state.exit_at is not None and t >= state.exit_at:
                    close_now(state, t, c["open"], self.costs, "opposite signal")
                    break
                if state.time_stop_at is not None and t >= state.time_stop_at:
                    close_now(state, t, c["open"], self.costs, "time stop")
                    break
                if t - trade["entry_time"] >= self.max_hold_ms:
                    close_now(state, t, c["open"], self.costs, "timeout")
                    break
                if state.mode == "hybrid" and state.partial_done and t % tf_step == 0:
                    closed = self.conn.execute(
                        "SELECT open_time, open, high, low, close FROM candles"
                        " WHERE symbol = ? AND timeframe = ? AND open_time <= ? ORDER BY open_time DESC LIMIT ?",
                        (trade["symbol"], trade["timeframe"], t - tf_step, state.trail_lookback),
                    ).fetchall()
                    trail(state, [tuple(r) for r in reversed(closed)])
                step(state, (t, c["open"], c["high"], c["low"], c["close"]), self.costs)
                if state.closed:
                    break
            if len(candles) < CHUNK:
                break
            start = candles[-1]["open_time"] + 60_000

    def _save(self, trade_id: int, state: TradeState) -> None:
        now = now_ms()
        state_json = json.dumps(state.to_json())
        with self.conn:
            if not state.closed:
                self.conn.execute("UPDATE trades SET state_json = ?, updated_at = ? WHERE id = ?", (state_json, now, trade_id))
                return
            r = results(state, self.costs)
            self.conn.execute(
                """
                UPDATE trades SET status = 'closed', exit_time = ?, exit_reason = ?, r_gross = ?, fees_r = ?,
                    slippage_r = ?, funding_r = ?, r_net = ?, mfe_r = ?, mae_r = ?, ambiguous = ?,
                    state_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    state.last_time, state.exit_reason, r["r_gross"], r["fees_r"], r["slippage_r"], r["funding_r"],
                    r["r_net"], r["mfe_r"], r["mae_r"], int(state.ambiguous), state_json, now, trade_id,
                ),
            )
