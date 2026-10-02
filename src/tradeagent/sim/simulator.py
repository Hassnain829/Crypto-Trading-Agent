"""Shadow trade simulation on closed 1m candles. Pure logic; the tracker stores the state.

Rules (docs/phases/phase-2-shadow-engine.md):
- Entry at the reference price plus adverse slippage, taker fee.
- Stops are market exits: taker fee and adverse slippage; a candle that opens beyond the stop fills at its open.
- Take-profits and the hybrid partial are limit exits: maker fee, filled exactly at the level.
- If the stop and a profit level are both touched inside one 1m candle, the stop counts (flagged as ambiguous).
- Hybrid: close `partial_fraction` at `partial_r`, move the stop to break-even plus fees, then trail it behind
  the low (long) / high (short) of the last `trail_lookback` closed candles of the trading timeframe.
- R is measured against the planned risk |entry_ref - stop_initial|.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

Candle = tuple[int, float, float, float, float]  # open_time, open, high, low, close


@dataclass(frozen=True)
class Costs:
    maker_fee: float
    taker_fee: float
    slippage: float


@dataclass
class Leg:
    time: int
    ref: float  # price the exit was aimed at
    fill: float  # price after slippage
    fraction: float  # share of the position closed
    fee_rate: float
    reason: str


@dataclass
class TradeState:
    side: str  # long | short
    mode: str  # fixed | hybrid
    entry_time: int
    entry_ref: float
    entry_fill: float
    stop_initial: float
    stop: float  # current stop
    target: float | None  # fixed mode take-profit price
    partial_price: float | None  # hybrid mode partial take-profit price
    partial_fraction: float
    trail_lookback: int
    best: float  # best price reached (for MFE)
    worst: float  # worst price reached (for MAE)
    remaining: float = 1.0
    legs: list[Leg] = field(default_factory=list)
    funding_per_unit: float = 0.0  # positive = cost
    partial_done: bool = False
    ambiguous: bool = False
    closed: bool = False
    exit_reason: str | None = None
    last_time: int | None = None  # open time of the last processed 1m candle

    @property
    def sign(self) -> int:
        return 1 if self.side == "long" else -1

    @property
    def risk(self) -> float:
        return abs(self.entry_ref - self.stop_initial)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> TradeState:
        legs = [Leg(**leg) for leg in data.get("legs", [])]
        return cls(**{**data, "legs": legs})


def open_trade(
    *,
    side: str,
    mode: str,
    entry_time: int,
    entry_ref: float,
    stop: float,
    take_profit_r: float,
    partial_r: float,
    partial_fraction: float,
    trail_lookback: int,
    costs: Costs,
) -> TradeState:
    if mode not in ("fixed", "hybrid"):
        raise ValueError(f"unknown exit mode {mode!r}")
    sign = 1 if side == "long" else -1
    if sign * (entry_ref - stop) <= 0:
        raise ValueError("the stop must be below the entry for longs and above it for shorts")
    risk = abs(entry_ref - stop)
    return TradeState(
        side=side,
        mode=mode,
        entry_time=entry_time,
        entry_ref=entry_ref,
        entry_fill=entry_ref * (1 + sign * costs.slippage),
        stop_initial=stop,
        stop=stop,
        target=entry_ref + sign * take_profit_r * risk if mode == "fixed" else None,
        partial_price=entry_ref + sign * partial_r * risk if mode == "hybrid" else None,
        partial_fraction=partial_fraction,
        trail_lookback=trail_lookback,
        best=entry_ref,
        worst=entry_ref,
    )


def _exit(state: TradeState, time: int, ref: float, fraction: float, fee_rate: float, reason: str, costs: Costs, *, market: bool) -> None:
    fill = ref * (1 - state.sign * costs.slippage) if market else ref
    fraction = min(fraction, state.remaining)
    state.legs.append(Leg(time, ref, fill, fraction, fee_rate, reason))
    state.remaining = round(state.remaining - fraction, 12)
    if state.remaining <= 0:
        state.remaining = 0.0
        state.closed = True
        state.exit_reason = reason


def _touched(state: TradeState, level: float, high: float, low: float) -> bool:
    return high >= level if state.sign > 0 else low <= level


def step(state: TradeState, candle: Candle, costs: Costs) -> None:
    """Process one closed 1m candle. The stop is checked first (conservative)."""
    if state.closed:
        return
    t, o, h, l, _c = candle[:5]
    if state.sign > 0:
        state.best, state.worst = max(state.best, h), min(state.worst, l)
    else:
        state.best, state.worst = min(state.best, l), max(state.worst, h)

    stop_hit = l <= state.stop if state.sign > 0 else h >= state.stop
    if stop_hit:
        gapped = o <= state.stop if state.sign > 0 else o >= state.stop
        level = state.target if state.target is not None else (None if state.partial_done else state.partial_price)
        if level is not None and _touched(state, level, h, l):
            state.ambiguous = True
        reason = "trail" if state.partial_done else "stop"
        _exit(state, t, o if gapped else state.stop, state.remaining, costs.taker_fee, reason, costs, market=True)
    elif state.target is not None and _touched(state, state.target, h, l):
        _exit(state, t, state.target, state.remaining, costs.maker_fee, "target", costs, market=False)
    elif state.partial_price is not None and not state.partial_done and _touched(state, state.partial_price, h, l):
        _exit(state, t, state.partial_price, state.partial_fraction, costs.maker_fee, "partial", costs, market=False)
        state.partial_done = True
        breakeven = state.entry_fill * (1 + state.sign * (2 * costs.taker_fee + costs.slippage))
        state.stop = max(state.stop, breakeven) if state.sign > 0 else min(state.stop, breakeven)
    state.last_time = t


def trail(state: TradeState, closed_candles: list[Candle]) -> None:
    """After the hybrid partial, move the stop behind the last N closed trading-timeframe candles (never back)."""
    if state.closed or state.mode != "hybrid" or not state.partial_done:
        return
    window = closed_candles[-state.trail_lookback:]
    if len(window) < state.trail_lookback:
        return
    if state.sign > 0:
        state.stop = max(state.stop, min(c[3] for c in window))
    else:
        state.stop = min(state.stop, max(c[2] for c in window))


def apply_funding(state: TradeState, rate: float, price: float) -> None:
    """Funding settled while the position is open: longs pay positive rates, shorts receive them."""
    if not state.closed:
        state.funding_per_unit += state.sign * rate * price * state.remaining


def close_now(state: TradeState, time: int, price: float, costs: Costs, reason: str) -> None:
    """Market exit of whatever is left (for example a time limit)."""
    if not state.closed:
        _exit(state, time, price, state.remaining, costs.taker_fee, reason, costs, market=True)
        state.last_time = time


def results(state: TradeState, costs: Costs) -> dict[str, float]:
    """Trade outcome in R (planned risk). r_net = r_gross - slippage_r - fees_r - funding_r."""
    risk, sign = state.risk, state.sign
    gross = sum(sign * (leg.ref - state.entry_ref) * leg.fraction for leg in state.legs)
    slippage = sign * (state.entry_fill - state.entry_ref) + sum(
        sign * (leg.ref - leg.fill) * leg.fraction for leg in state.legs
    )
    fees = state.entry_fill * costs.taker_fee + sum(leg.fill * leg.fee_rate * leg.fraction for leg in state.legs)
    out = {
        "r_gross": gross / risk,
        "slippage_r": slippage / risk,
        "fees_r": fees / risk,
        "funding_r": state.funding_per_unit / risk,
        "mfe_r": sign * (state.best - state.entry_ref) / risk,
        "mae_r": sign * (state.worst - state.entry_ref) / risk,
    }
    out["r_net"] = out["r_gross"] - out["slippage_r"] - out["fees_r"] - out["funding_r"]
    return out
