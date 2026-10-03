"""Account rules as pure functions: position sizing and the risk checks (paper now, live in Phase 6)."""

from __future__ import annotations

import math
from decimal import Decimal
from dataclasses import dataclass, field

from tradeagent.config import PaperAccountConfig


@dataclass(frozen=True)
class MarketLimits:
    step_size: float  # quantity increment
    min_qty: float
    min_notional: float  # minimum order value in USDT


@dataclass
class Sizing:
    qty: float
    notional: float
    leverage: float
    risk_usd: float
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OpenPosition:
    symbol: str
    side: str
    notional: float


def round_down(qty: float, step: float) -> float:
    """Round a quantity down to the exchange step size (with a small tolerance for float noise)."""
    steps = math.floor(qty / step + 1e-9)
    decimals = max(0, -Decimal(str(step)).normalize().as_tuple().exponent)
    return round(steps * step, decimals)


def size_position(
    balance: float, entry: float, stop: float, rules: PaperAccountConfig, limits: MarketLimits, used_margin: float = 0.0
) -> Sizing | str:
    """Quantity for `risk_per_trade` of the balance, then the leverage cap and the free margin, then rounding.

    Isolated margin at the leverage cap: each position locks notional / leverage_cap of the balance.
    A string means the trade is rejected.
    """
    distance = abs(entry - stop)
    if distance <= 0 or balance <= 0:
        return "invalid stop or empty balance"
    notes = []
    qty = rules.risk_per_trade * balance / distance
    by_leverage = rules.leverage_cap * balance / entry
    if qty > by_leverage:
        qty = by_leverage
        notes.append(f"size reduced by the {rules.leverage_cap:g}x leverage cap")
    free_margin = balance - used_margin
    by_margin = rules.leverage_cap * max(free_margin, 0.0) / entry
    if qty > by_margin:
        qty = by_margin
        notes.append(f"size reduced to the free margin ({free_margin:.2f} USDT at {rules.leverage_cap:g}x)")
    qty = round_down(qty, limits.step_size)
    notional = qty * entry
    if qty <= 0 or qty < limits.min_qty or notional < limits.min_notional:
        return f"below the minimum order size ({limits.min_notional:g} USDT)"
    return Sizing(qty, notional, notional / balance, qty * distance, notes)


def check_entry(
    *,
    symbol: str,
    open_positions: list[OpenPosition],
    balance: float,
    day_start_balance: float,
    rules: PaperAccountConfig,
    kill_switch: str,
) -> str | None:
    """Why a new position may not be opened right now (None = allowed)."""
    if kill_switch != "off":
        return f"kill switch is {kill_switch}"
    stop = rules.daily_loss_stop
    if stop is not None and day_start_balance > 0 and (day_start_balance - balance) >= stop * day_start_balance:
        return f"daily loss stop ({stop:.0%} of the day's starting balance) reached"
    per_coin = rules.max_positions_per_coin
    if per_coin is not None and sum(1 for p in open_positions if p.symbol == symbol) >= per_coin:
        return f"{symbol} already has an open position" if per_coin == 1 else f"max {per_coin} open positions on {symbol}"
    if rules.max_positions is not None and len(open_positions) >= rules.max_positions:
        return f"max {rules.max_positions} open positions"
    return None


def used_margin(open_positions: list[OpenPosition], rules: PaperAccountConfig) -> float:
    """Balance locked as isolated margin by the open positions."""
    return sum(p.notional for p in open_positions) / rules.leverage_cap
