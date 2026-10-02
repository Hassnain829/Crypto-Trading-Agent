"""Brokers execute what the account engine decides. PaperBroker now; BinanceBroker joins in Phase 6.

The account engine only talks to this interface, so paper and live trading share one code path.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Protocol

from tradeagent.sim.simulator import Costs, Leg, TradeState


@dataclass(frozen=True)
class ExitReport:
    time: int
    reason: str
    legs: list[Leg]  # every partial and final exit, per unit of quantity
    funding_per_unit: float  # positive = cost


class Broker(Protocol):
    def entry_fill(self, trade_id: int) -> float:
        """Average entry price of the position that follows `trade_id`."""
        ...

    def exit_report(self, trade_id: int) -> ExitReport | None:
        """How the position closed, or None while it is still open."""
        ...

    def close_now(self, trade_id: int, time: int, price: float) -> ExitReport:
        """Close what is left at market (kill switch)."""
        ...


class PaperBroker:
    """Follows the exploration trade of the same signal: identical fills, fees, slippage and funding."""

    def __init__(self, conn: sqlite3.Connection, costs: Costs) -> None:
        self.conn = conn
        self.costs = costs

    def _trade(self, trade_id: int) -> sqlite3.Row:
        return self.conn.execute("SELECT status, exit_time, state_json FROM trades WHERE id = ?", (trade_id,)).fetchone()

    def entry_fill(self, trade_id: int) -> float:
        return TradeState.from_json(json.loads(self._trade(trade_id)["state_json"])).entry_fill

    def exit_report(self, trade_id: int) -> ExitReport | None:
        row = self._trade(trade_id)
        if row["status"] != "closed":
            return None
        state = TradeState.from_json(json.loads(row["state_json"]))
        return ExitReport(row["exit_time"], state.exit_reason or "closed", state.legs, state.funding_per_unit)

    def close_now(self, trade_id: int, time: int, price: float) -> ExitReport:
        state = TradeState.from_json(json.loads(self._trade(trade_id)["state_json"]))
        fill = price * (1 - state.sign * self.costs.slippage)
        legs = list(state.legs) + [Leg(time, price, fill, state.remaining, self.costs.taker_fee, "kill switch")]
        return ExitReport(time, "kill switch", legs, state.funding_per_unit)
