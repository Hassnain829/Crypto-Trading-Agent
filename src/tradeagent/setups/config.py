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
    indicator: Literal["qtrend", "zerolag"]
    long: str
    short: str


class ConfirmationParams(_Strict):
    window: int = Field(ge=0, le=10)
    klinger: bool
    candle_direction: bool


class FilterParams(_Strict):
    vwap: bool
    macd_trend: bool
    htf: Literal["none", "1h", "1h+4h"]
    min_stop_pct: float = Field(ge=0, le=5)


class StopParams(_Strict):
    lookback: int = Field(ge=1, le=100)


class ExitParams(_Strict):
    mode: Literal["fixed", "hybrid", "htf_rule"]
    take_profit_r: float = Field(ge=0.25, le=10)
    partial_r: float = Field(ge=0.25, le=10)
    partial_fraction: float = Field(gt=0, lt=1)
    trail_lookback: int = Field(ge=1, le=50)


class SetupParams(_Strict):
    timeframes: list[str] = Field(min_length=1)
    trigger: TriggerParams
    confirmation: ConfirmationParams
    filters: FilterParams
    stop: StopParams
    exit: ExitParams

    @field_validator("timeframes")
    @classmethod
    def _trading_timeframes(cls, value: list[str]) -> list[str]:
        if any(tf not in ("1m", "3m", "5m", "15m", "30m") for tf in value):
            raise ValueError(f"setups run on trading timeframes only, got {value}")
        return value


@dataclass(frozen=True)
class Variant:
    name: str
    params: SetupParams
    role: str  # baseline | challenger

    @property
    def params_hash(self) -> str:
        canonical = json.dumps(self.params.model_dump(), sort_keys=True, separators=(",", ":"))
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
