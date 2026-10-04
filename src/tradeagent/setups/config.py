"""Setup rules (config/setups.yaml): the baseline and its one-change variants."""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from tradeagent.journal.db import now_ms
from tradeagent.tv.catalog import Catalog

BASELINE_NAME = "v0"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TriggerParams(_Strict):
    indicator: Literal["qtrend", "zerolag", "atp_macd"]
    long: str
    short: str


class ConfirmationParams(_Strict):
    window: int = Field(ge=0, le=10)
    klinger: bool
    candle_direction: bool


class FilterParams(_Strict):
    vwap: bool
    macd_trend: bool
    htf: Literal["none", "1h", "1h+4h", "against_4h"]  # with the 1h / 1h+4h Zero Lag trend, or against the 4h one
    min_stop_pct: float = Field(ge=0, le=5)
    zl_own: bool = False  # the signal must agree with the Zero Lag trend of its own chart
    trend_15m: bool = False  # 5m signals only when the 15m Zero Lag trend agrees (15m signals are not affected)
    session_utc: tuple[int, int] | None = None  # only entries whose UTC hour is in [start, end)

    @field_validator("session_utc")
    @classmethod
    def _session(cls, value: tuple[int, int] | None) -> tuple[int, int] | None:
        if value is not None and not 0 <= value[0] < value[1] <= 24:
            raise ValueError("session_utc must be [start, end) UTC hours with 0 <= start < end <= 24")
        return value


class EntryParams(_Strict):
    # market: at the 1m open after the signal (taker fee + slippage). limit: a limit order at that price,
    # filled only if the price trades through it within that first minute (maker fee, no slippage).
    mode: Literal["market", "limit"] = "market"
    # limit: how many minutes the order rests. It fills in the first of these minutes that trades through
    # the price; the trade starts in that minute.
    limit_minutes: int = Field(default=1, ge=1, le=60)
    # limit: price this share of the way from the open toward the stop (0 = the open), e.g. 0.3 waits for a
    # pullback toward support. The target stays the planned price, so a filled order has a better R:R.
    offset_r: float = Field(default=0.0, ge=0.0, le=0.9)


class StopParams(_Strict):
    lookback: int = Field(ge=1, le=100)
    anchor: Literal["trade", "1h"] = "trade"  # swing of the trading chart, or also of the last 1h candles
    multiplier: float = Field(default=1.0, ge=0.5, le=5)  # stop distance times this


class ExitParams(_Strict):
    """Targets are measured from the chart's swing stop, so moving the stop (anchor, multiplier) keeps the target."""

    mode: Literal["fixed", "hybrid", "htf_rule"]
    take_profit_r: float = Field(ge=0.25, le=10)
    partial_r: float = Field(ge=0.25, le=10)
    partial_fraction: float = Field(gt=0, lt=1)
    trail_lookback: int = Field(ge=1, le=50)
    breakeven_r: float | None = Field(default=None, ge=0.25, le=10)  # stop to break-even after the price went +X R
    opposite_signal: bool = False  # close at market when the opposite trigger appears on the same chart
    max_candles: int | None = Field(default=None, ge=1, le=500)  # time stop: close at market after N chart candles


class SetupParams(_Strict):
    timeframes: list[str] = Field(min_length=1)
    trigger: TriggerParams
    confirmation: ConfirmationParams
    filters: FilterParams
    entry: EntryParams = Field(default_factory=EntryParams)
    stop: StopParams
    exit: ExitParams

    @field_validator("timeframes")
    @classmethod
    def _trading_timeframes(cls, value: list[str]) -> list[str]:
        if any(tf not in ("1m", "3m", "5m", "15m", "30m", "1h") for tf in value):
            raise ValueError(f"setups run on 1m to 1h charts only, got {value}")
        return value


# Options added after variants were first stored, with their defaults. At the default they are left out of
# the hash, so adding an option never renames the existing variants (which would split their history).
ADDED_LATER: dict[tuple[str, str], Any] = {
    ("entry", "limit_minutes"): 1, ("entry", "offset_r"): 0.0, ("filters", "trend_15m"): False,
}


def hashable_params(params: SetupParams) -> dict[str, Any]:
    data = params.model_dump()
    for (section, key), default in ADDED_LATER.items():
        if data.get(section, {}).get(key) == default:
            del data[section][key]
    return data


@dataclass(frozen=True)
class Variant:
    name: str
    params: SetupParams
    role: str  # baseline | challenger

    @property
    def params_hash(self) -> str:
        canonical = json.dumps(hashable_params(self.params), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    @property
    def id(self) -> str:
        """Name plus a short hash, so changed rules never mix with old results."""
        return f"{self.name}-{self.params_hash[:6]}"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_variants(path: Path, catalog: Catalog | None = None) -> list[Variant]:
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    baseline = raw["baseline"]
    variants = [Variant(BASELINE_NAME, SetupParams.model_validate(baseline), "baseline")]
    for name, override in (raw.get("variants") or {}).items():
        if name == BASELINE_NAME:
            raise ValueError(f"variant name {BASELINE_NAME!r} is reserved for the baseline")
        variants.append(Variant(name, SetupParams.model_validate(deep_merge(baseline, override or {})), "challenger"))
    if catalog is not None:
        for v in variants:
            fields = catalog.indicators[v.params.trigger.indicator].fields
            for side in (v.params.trigger.long, v.params.trigger.short):
                if side not in fields or fields[side].kind != "flag":
                    raise ValueError(f"variant {v.name}: {v.params.trigger.indicator}.{side} is not a flag in the catalog")
    return variants


def register_variants(conn: sqlite3.Connection, variants: list[Variant]) -> None:
    """Record the active variants; variants no longer in the config are marked retired."""
    active = {v.id for v in variants}
    with conn:
        for v in variants:
            conn.execute(
                "INSERT INTO variants (id, params_json, params_hash, role, parent, created_at) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (id) DO UPDATE SET role = excluded.role",
                (v.id, json.dumps(v.params.model_dump(), sort_keys=True), v.params_hash, v.role,
                 None if v.role == "baseline" else BASELINE_NAME, now_ms()),
            )
        for (variant_id,) in conn.execute("SELECT id FROM variants WHERE role != 'retired'").fetchall():
            if variant_id not in active:
                conn.execute("UPDATE variants SET role = 'retired' WHERE id = ?", (variant_id,))
