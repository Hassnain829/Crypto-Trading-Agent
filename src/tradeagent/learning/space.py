"""What an experiment may change: one rule of config/setups.yaml, within these limits.

Claude (or the user) proposes {"path": "stop.min_pct", "value": 1.5}; nothing else can be changed this way.
Costs, data, indicator settings, account limits and the evaluation rules are off limits to experiments.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from tradeagent.setups.config import SetupParams


@dataclass(frozen=True)
class Knob:
    path: str  # section.key in the setup rules
    kind: str  # bool | choice | number | session | timeframes
    help: str
    choices: tuple[Any, ...] = ()
    lo: float | None = None
    hi: float | None = None
    step: float | None = None
    nullable: bool = False  # null switches the rule off
    extra: dict[str, Any] = field(default_factory=dict)


SPACE: dict[str, Knob] = {k.path: k for k in (
    Knob("timeframes", "timeframes", "which charts give signals", choices=("5m", "15m")),
    Knob("trigger.long", "choice", "the long trigger flag", choices=("buy", "strong_buy")),
    Knob("trigger.short", "choice", "the short trigger flag", choices=("sell", "strong_sell")),
    Knob("confirmation.window", "number", "candles after the trigger in which confirmation may come", lo=0, hi=5, step=1),
    Knob("confirmation.klinger", "bool", "Klinger histogram must agree"),
    Knob("confirmation.candle_direction", "bool", "the confirming candle must close in the trade's direction"),
    Knob("filters.vwap", "bool", "longs only above VWAP, shorts only below"),
    Knob("filters.macd_trend", "bool", "ATP MACD line on the trade's side of zero"),
    Knob("filters.htf", "choice", "higher-timeframe Zero Lag trend rule", choices=("none", "1h", "1h+4h", "against_4h")),
    Knob("filters.min_stop_pct", "number", "skip setups whose swing stop is closer than this %", lo=0, hi=3, step=0.25),
    Knob("filters.zl_own", "bool", "the signal must agree with its own chart's Zero Lag trend"),
    Knob("filters.trend_15m", "bool", "5m signals only with the 15m Zero Lag trend"),
    Knob("filters.session_utc", "session", "only entries in these UTC hours [start, end)", nullable=True),
    Knob("entry.mode", "choice", "market (taker) or limit (maker) entry", choices=("market", "limit")),
    Knob("entry.limit_minutes", "number", "minutes a limit order rests", lo=1, hi=60, step=1),
    Knob("entry.offset_r", "number", "limit price this share of the way toward the stop", lo=0, hi=0.6, step=0.05),
    Knob("stop.lookback", "number", "candles of the swing stop", lo=3, hi=30, step=1),
    Knob("stop.anchor", "choice", "also beyond the 1h swing", choices=("trade", "1h")),
    Knob("stop.multiplier", "number", "stop distance times this", lo=0.75, hi=2.5, step=0.05),
    Knob("stop.min_pct", "number", "move a tighter swing stop out to this % (instead of skipping it)", lo=0.5, hi=3,
         step=0.25, nullable=True),
    Knob("exit.mode", "choice", "fixed target, or partial at partial_r then trail", choices=("fixed", "hybrid")),
    Knob("exit.take_profit_r", "number", "target in R", lo=0.75, hi=4, step=0.05),
    Knob("exit.partial_r", "number", "hybrid: R of the partial close", lo=0.5, hi=2, step=0.05),
    Knob("exit.breakeven_r", "number", "stop to break-even after +X R", lo=0.5, hi=2, step=0.05, nullable=True),
    Knob("exit.opposite_signal", "bool", "close on the opposite trigger of the same chart"),
    Knob("exit.max_candles", "number", "close at market after N chart candles", lo=6, hi=576, step=1, nullable=True),
)}


def get_path(data: dict[str, Any], path: str) -> Any:
    node: Any = data
    for key in path.split("."):
        node = node[key]
    return node


def override_for(path: str, value: Any) -> dict[str, Any]:
    """{"stop": {"min_pct": 1.5}} for ("stop.min_pct", 1.5)."""
    out: dict[str, Any] = {}
    node = out
    keys = path.split(".")
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value
    return out


def _on_grid(value: float, knob: Knob) -> bool:
    if knob.step is None or knob.lo is None:
        return True
    steps = (value - knob.lo) / knob.step
    return abs(steps - round(steps)) < 1e-6


def check_value(knob: Knob, value: Any) -> str | None:
    if value is None:
        return None if knob.nullable else f"{knob.path} cannot be null"
    if knob.kind == "bool":
        return None if isinstance(value, bool) else f"{knob.path} must be true or false"
    if knob.kind == "choice":
        return None if value in knob.choices else f"{knob.path} must be one of {list(knob.choices)}"
    if knob.kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{knob.path} must be a number"
        if not knob.lo <= value <= knob.hi:
            return f"{knob.path} must be between {knob.lo:g} and {knob.hi:g}"
        if not _on_grid(float(value), knob):
            return f"{knob.path} must be a multiple of {knob.step:g} from {knob.lo:g}"
        return None
    if knob.kind == "session":
        ok = isinstance(value, (list, tuple)) and len(value) == 2 and all(isinstance(h, int) for h in value) \
            and 0 <= value[0] < value[1] <= 24 and value[1] - value[0] >= 4
        return None if ok else "filters.session_utc must be [start, end) whole UTC hours, at least 4 hours long"
    if knob.kind == "timeframes":
        ok = isinstance(value, list) and value and all(v in knob.choices for v in value) and len(set(value)) == len(value)
        return None if ok else f"timeframes must be a non-empty list from {list(knob.choices)}"
    return f"{knob.path}: unknown kind {knob.kind}"


def validate_change(baseline: dict[str, Any], path: str, value: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """Check one proposed change against the baseline rules. Returns (the challenger's rules, problems)."""
    knob = SPACE.get(path)
    if knob is None:
        return None, [f"{path} cannot be changed by an experiment; allowed: {', '.join(SPACE)}"]
    problem = check_value(knob, value)
    if problem:
        return None, [problem]
    try:
        current = get_path(baseline, path)
    except (KeyError, TypeError):
        current = None
    if current == value or (isinstance(current, tuple) and list(current) == value):
        return None, [f"{path} is already {value!r} in the baseline"]
    rules = copy.deepcopy(baseline)
    node = rules
    keys = path.split(".")
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value
    try:
        SetupParams.model_validate(rules)
    except ValidationError as exc:
        return None, [f"the changed rules are invalid: {exc.errors()[0]['msg']}"]
    return rules, []


def proposal_schema() -> dict[str, Any]:
    """JSON schema of a research run's output (research/proposal.schema.json is generated from this)."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Research run output",
        "type": "object",
        "required": ["summary", "proposals"],
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string", "description": "what the pack showed and why these proposals"},
            "proposals": {
                "type": "array", "maxItems": 5,
                "items": {
                    "type": "object",
                    "required": ["name", "change", "hypothesis", "expected", "confidence"],
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]{2,40}$"},
                        "change": {
                            "type": "object", "required": ["path", "value"], "additionalProperties": False,
                            "properties": {"path": {"type": "string", "enum": list(SPACE)}, "value": {}},
                        },
                        "hypothesis": {"type": "string", "minLength": 20},
                        "expected": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                },
            },
            "lessons": {
                "type": "array",
                "items": {
                    "type": "object", "required": ["experiment_id", "text"], "additionalProperties": False,
                    "properties": {"experiment_id": {"type": "integer"}, "text": {"type": "string", "minLength": 10}},
                },
            },
        },
    }
