"""Paper account: follows the baseline variant's signals under the live rules.

Signals are handled in time order. Before each new entry, positions whose exploration trade has
already closed are settled, so the balance, the open positions and the daily loss stop are exactly
what they would have been at that moment. Every decision (opened or rejected, and why) is stored.
The account never writes to the exploration book: its limits and pauses do not slow down learning.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections import Counter
from typing import Any

from tradeagent.account.broker import Broker, ExitReport, PaperBroker
from tradeagent.account.kill_switch import get_kill_switch, set_kill_switch
from tradeagent.account.rules import MarketLimits, OpenPosition, check_entry, size_position, used_margin
from tradeagent.config import PaperAccountConfig, Settings
from tradeagent.journal.db import now_ms
from tradeagent.sim.simulator import Costs

log = logging.getLogger("tradeagent.account")

ACCOUNT = "paper"
LATE = "signal arrived after a later signal was already handled"


def reset_account(conn: sqlite3.Connection, settings: Settings, *, from_now: bool = False) -> int:
    """Delete the paper account. With `from_now`, it restarts at the starting balance and takes only
    signals from this moment on (a forward test); otherwise the next run replays the whole history."""
    with conn:
        deleted = conn.execute("DELETE FROM account_trades WHERE account = ?", (ACCOUNT,)).rowcount
        conn.execute("DELETE FROM account_state WHERE account = ?", (ACCOUNT,))
        if from_now:
            baseline = conn.execute("SELECT id FROM variants WHERE role = 'baseline'").fetchone()
            start, now = settings.paper_account.starting_balance, now_ms()
            conn.execute(
                "INSERT INTO account_state (account, balance, day, day_start_balance, last_entry_time, baseline,"
                " started_at, updated_at) VALUES (?, ?, NULL, ?, ?, ?, ?, ?)",
                (ACCOUNT, start, start, now, baseline[0] if baseline else None, now, now),
            )
    return deleted


def utc_day(ms: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def position_pnl(position: Any, report: ExitReport) -> tuple[float, float, float]:
    """(net PnL, fees, funding) in USDT of a position that closed as `report` describes."""
    sign = 1 if position["side"] == "long" else -1
    qty, entry_fill = position["qty"], position["entry_fill"]
    gross = qty * sum(sign * (leg.fill - entry_fill) * leg.fraction for leg in report.legs)
    fees = qty * (entry_fill * report.entry_fee_rate + sum(leg.fill * leg.fee_rate * leg.fraction for leg in report.legs))
    funding = qty * report.funding_per_unit
    return gross - fees - funding, fees, funding


class AccountEngine:
    def __init__(self, settings: Settings, conn: sqlite3.Connection, broker: Broker | None = None) -> None:
        self.settings = settings
        self.conn = conn
        self.costs = Costs(settings.costs.maker_fee, settings.costs.taker_fee, settings.costs.slippage)
        self.broker = broker or PaperBroker(conn, self.costs)

    @property
    def rules(self) -> PaperAccountConfig:
        """Read on every use, so a change made in the dashboard applies in the next cycle."""
        return self.settings.paper_account

    # ---- state -------------------------------------------------------------------------------
    def _load(self) -> dict:
        row = self.conn.execute("SELECT * FROM account_state WHERE account = ?", (ACCOUNT,)).fetchone()
        if row:
            return dict(row)
        return {"account": ACCOUNT, "balance": self.rules.starting_balance, "day": None,
                "day_start_balance": self.rules.starting_balance, "last_entry_time": 0, "updated_at": 0,
                "baseline": None, "started_at": None}

    def _save(self, state: dict) -> None:
        self.conn.execute(
            "INSERT INTO account_state (account, balance, day, day_start_balance, last_entry_time, baseline,"
            " started_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (account) DO UPDATE SET"
            " balance = excluded.balance, day = excluded.day, day_start_balance = excluded.day_start_balance,"
            " last_entry_time = excluded.last_entry_time, baseline = excluded.baseline,"
            " started_at = excluded.started_at, updated_at = excluded.updated_at",
            (ACCOUNT, state["balance"], state["day"], state["day_start_balance"], state["last_entry_time"],
             state["baseline"], state["started_at"], now_ms()),
        )

    @staticmethod
    def _roll_day(state: dict, at: int) -> None:
        """A new UTC day starts with the balance it opens with (the daily loss stop resets)."""
        day = utc_day(at)
        if state["day"] is None or day > state["day"]:
            state["day"] = day
            state["day_start_balance"] = state["balance"]

    def _open_positions(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM account_trades WHERE account = ? AND status = 'open' ORDER BY entry_time, id", (ACCOUNT,)
        ).fetchall()

    def _limits(self, symbol: str) -> MarketLimits:
        row = self.conn.execute("SELECT step_size, min_qty, min_notional, contract_size FROM market_info WHERE symbol = ?",
                                (symbol,)).fetchone()
        return MarketLimits(row["step_size"], row["min_qty"] or 0.0, row["min_notional"] or 0.0, row["contract_size"] or 1.0)

    def _missing_market_info(self) -> list[str]:
        have = {r[0] for r in self.conn.execute("SELECT symbol FROM market_info WHERE step_size IS NOT NULL")}
        return [symbol for symbol in self.settings.exchange.symbols if symbol not in have]

    def _last_price(self, symbol: str) -> tuple[int, float] | None:
        """Time and price of the newest 1m close."""
        row = self.conn.execute(
            "SELECT open_time, close FROM candles WHERE symbol = ? AND timeframe = '1m' ORDER BY open_time DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        return (row["open_time"] + 60_000, row["close"]) if row else None

    # ---- settlement --------------------------------------------------------------------------
    def _settle(self, state: dict, position: sqlite3.Row, report: ExitReport) -> None:
        self._roll_day(state, report.time)
        pnl, fees, funding = position_pnl(position, report)
        state["balance"] += pnl
        self.conn.execute(
            """
            UPDATE account_trades SET status = 'closed', exit_time = ?, exit_reason = ?, pnl_usd = ?, fees_usd = ?,
                funding_usd = ?, r_net = ?, account_pct = ?, balance_after = ?, updated_at = ?
            WHERE id = ?
            """,
            (report.time, report.reason, pnl, fees, funding, pnl / position["risk_usd"],
             pnl / position["balance_before"] * 100, state["balance"], now_ms(), position["id"]),
        )

    def _settle_until(self, state: dict, before: int | None) -> int:
        """Settle, in exit order, every open position whose exit happened before `before` (all known exits if None)."""
        reports = []
        for position in self._open_positions():
            report = self.broker.exit_report(position["trade_id"])
            if report is not None and (before is None or report.time < before):
                reports.append((report.time, position["id"], position, report))
        for _time, _id, position, report in sorted(reports, key=lambda item: (item[0], item[1])):
            self._settle(state, position, report)
        return len(reports)

    # ---- main --------------------------------------------------------------------------------
    def process(self) -> Counter[str]:
        """Handle every new baseline signal, then settle every position that has closed."""
        counts: Counter[str] = Counter()
        baseline = self.conn.execute("SELECT id FROM variants WHERE role = 'baseline'").fetchone()
        if baseline is None:
            return counts
        missing = self._missing_market_info()
        if missing:
            log.warning("paper account waiting: no market info for %s (run market-sync)", ", ".join(missing))
            counts["waiting_market_info"] = 1
            return counts
        kill = get_kill_switch(self.conn)
        if kill == "close_all":
            with self.conn:
                state = self._load()
                counts["settled"] += self._settle_until(state, None)
                counts["closed_by_kill_switch"] = self._close_all(state)
                self._save(state)
            set_kill_switch(self.conn, "pause", "paper account after close_all")
            kill = "pause"
        with self.conn:
            state = self._load()
            if state["baseline"] not in (None, baseline["id"]):
                # A new baseline: follow it from now on. Its earlier trades are exploration history.
                log.info("paper account now follows %s (was %s)", baseline["id"], state["baseline"])
                state["last_entry_time"] = max(state["last_entry_time"], now_ms())
                state["updated_at"] = now_ms()
            state["baseline"] = baseline["id"]
            # New signals, plus signals that arrived since the last run (a late one is recorded, not traded).
            coins = self.rules.symbols
            only = f" AND symbol IN ({', '.join('?' * len(coins))})" if coins else ""
            candidates = self.conn.execute(
                f"""
                SELECT id, variant_id, symbol, timeframe, side, entry_time, entry_ref, stop_initial, venue
                FROM trades WHERE book = 'exploration' AND variant_id = ? AND taken = 1
                  AND status IN ('open', 'closed') AND (entry_time >= ? OR created_at > ?){only}
                  AND id NOT IN (SELECT trade_id FROM account_trades WHERE account = ?)
                ORDER BY entry_time, id
                """,
                (baseline["id"], state["last_entry_time"], state["updated_at"], *(coins or []), ACCOUNT),
            ).fetchall()
            for cand in candidates:
                if cand["entry_time"] < state["last_entry_time"]:
                    self._reject(state, cand, LATE)
                    counts["rejected"] += 1
                    continue
                counts["settled"] += self._settle_until(state, cand["entry_time"])
                self._roll_day(state, cand["entry_time"])
                counts["opened" if self._consider(state, cand, kill) else "rejected"] += 1
                state["last_entry_time"] = cand["entry_time"]
            counts["settled"] += self._settle_until(state, None)
            self._save(state)
        return counts

    def _consider(self, state: dict, cand: sqlite3.Row, kill: str) -> bool:
        open_positions = [OpenPosition(p["symbol"], p["side"], p["notional"]) for p in self._open_positions()]
        reason = check_entry(
            symbol=cand["symbol"], open_positions=open_positions, balance=state["balance"],
            day_start_balance=state["day_start_balance"], rules=self.rules, kill_switch=kill,
        )
        if reason is None:
            sizing = size_position(state["balance"], cand["entry_ref"], cand["stop_initial"], self.rules,
                                   self._limits(cand["symbol"]), used_margin(open_positions, self.rules))
            if isinstance(sizing, str):
                reason = sizing
        if reason is not None:
            self._reject(state, cand, reason)
            return False
        now = now_ms()
        self.conn.execute(
            "INSERT INTO account_trades (account, trade_id, variant_id, symbol, timeframe, side, entry_time,"
            " status, entry_fill, stop, qty, notional, leverage, risk_usd, balance_before, notes, venue, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ACCOUNT, cand["id"], cand["variant_id"], cand["symbol"], cand["timeframe"], cand["side"], cand["entry_time"],
             self.broker.entry_fill(cand["id"]), cand["stop_initial"], sizing.qty, sizing.notional, sizing.leverage,
             sizing.risk_usd, state["balance"], "; ".join(sizing.notes) or None, cand["venue"], now, now),
        )
        return True

    def _reject(self, state: dict, cand: sqlite3.Row, reason: str) -> None:
        now = now_ms()
        self.conn.execute(
            "INSERT INTO account_trades (account, trade_id, variant_id, symbol, timeframe, side, entry_time,"
            " status, reject_reason, balance_before, venue, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'rejected', ?, ?, ?, ?, ?)",
            (ACCOUNT, cand["id"], cand["variant_id"], cand["symbol"], cand["timeframe"], cand["side"], cand["entry_time"],
             reason, state["balance"], cand["venue"], now, now),
        )

    def _close_all(self, state: dict) -> int:
        """Kill switch close_all: close every open position at the newest 1m close (exploration trades go on)."""
        positions = self._open_positions()
        for position in positions:
            last = self._last_price(position["symbol"])
            if last is None:
                raise RuntimeError(f"no 1m candles for {position['symbol']}; run market-sync")
            self._settle(state, position, self.broker.close_now(position["trade_id"], *last))
        return len(positions)

    # ---- reporting ---------------------------------------------------------------------------
    def mark_to_market(self) -> list[dict[str, Any]]:
        """Open positions valued as if closed at market now (exit slippage and fees included)."""
        rows = []
        for position in self._open_positions():
            last = self._last_price(position["symbol"])
            pnl = 0.0
            if last is not None:
                pnl = position_pnl(position, self.broker.close_now(position["trade_id"], *last))[0]
            rows.append({**dict(position), "last_price": last and last[1], "unrealized_usd": pnl,
                         "unrealized_r": pnl / position["risk_usd"]})
        return rows
