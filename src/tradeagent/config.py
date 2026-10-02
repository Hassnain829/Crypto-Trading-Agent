"""Settings: config/settings.yaml validated with pydantic; secrets come from .env."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, SecretStr, field_validator, model_validator

from tradeagent.paths import CONFIG_RELATIVE, find_project_root

KNOWN_TIMEFRAMES = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d")


class _Section(BaseModel):
    # Unknown keys are errors, so a typo in settings.yaml is caught instead of silently ignored.
    model_config = ConfigDict(extra="forbid")


class SymbolConfig(_Section):
    ccxt: str
    tradingview: str


class ExchangeConfig(_Section):
    name: Literal["binance"]
    market_type: Literal["usdm"]
    symbols: dict[str, SymbolConfig] = Field(min_length=1)


class TimeframesConfig(_Section):
    trade: list[str] = Field(min_length=1)
    overview: list[str] = Field(default_factory=list)

    @field_validator("trade", "overview")
    @classmethod
    def _known(cls, value: list[str]) -> list[str]:
        unknown = [tf for tf in value if tf not in KNOWN_TIMEFRAMES]
        if unknown:
            raise ValueError(f"unknown timeframes {unknown}; use one of {list(KNOWN_TIMEFRAMES)}")
        return value


class TradingViewConfig(_Section):
    cdp_host: str = "127.0.0.1"
    cdp_port: int = Field(default=9222, ge=1, le=65535)
    app_id: str
    signal_version: int = Field(ge=1)
    layouts: dict[str, str] = Field(min_length=1)


class CostsConfig(_Section):
    maker_fee: float = Field(ge=0, le=0.01)
    taker_fee: float = Field(ge=0, le=0.01)
    slippage: float = Field(ge=0, le=0.01)


class PaperAccountConfig(_Section):
    starting_balance: float = Field(gt=0)
    risk_per_trade: float = Field(gt=0, le=0.05)
    max_positions: int = Field(ge=1, le=10)
    max_positions_per_coin: int = Field(ge=1, le=5)
    daily_loss_stop: float = Field(gt=0, le=0.5)
    leverage_cap: float = Field(ge=1, le=50)

    @model_validator(mode="after")
    def _per_coin_within_total(self) -> PaperAccountConfig:
        if self.max_positions_per_coin > self.max_positions:
            raise ValueError("max_positions_per_coin cannot be larger than max_positions")
        return self


class GoalConfig(_Section):
    min_trades: int = Field(ge=1)
    min_days: int = Field(ge=1)
    min_expectancy_r: float
    min_profit_factor: float = Field(gt=0)
    max_drawdown: float = Field(gt=0, lt=1)
    min_snapshot_coverage: float = Field(gt=0, le=1)


class LoggingConfig(_Section):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    file: str = "data/logs/agent.log"
    max_bytes: int = Field(default=5_000_000, ge=10_000)
    backups: int = Field(default=5, ge=0, le=50)


class JournalConfig(_Section):
    path: str = "data/journal.db"


class Secrets(BaseModel):
    binance_api_key: SecretStr | None = None
    binance_api_secret: SecretStr | None = None

    @property
    def has_binance_keys(self) -> bool:
        return bool(self.binance_api_key and self.binance_api_secret)


class Settings(_Section):
    exchange: ExchangeConfig
    timeframes: TimeframesConfig
    tradingview: TradingViewConfig
    costs: CostsConfig
    paper_account: PaperAccountConfig
    goal: GoalConfig
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    journal: JournalConfig = Field(default_factory=JournalConfig)

    _root: Path = PrivateAttr(default_factory=Path.cwd)
    _secrets: Secrets = PrivateAttr(default_factory=Secrets)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def secrets(self) -> Secrets:
        return self._secrets

    def resolve(self, path: str) -> Path:
        """Turn a path from settings.yaml into an absolute path; relative paths start at the project root."""
        p = Path(path)
        return p if p.is_absolute() else self._root / p


def load_settings(root: Path | None = None) -> Settings:
    root = (root or find_project_root()).resolve()
    with (root / CONFIG_RELATIVE).open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    settings = Settings.model_validate(raw)
    settings._root = root
    settings._secrets = _load_secrets(root / ".env")
    return settings


def _load_secrets(env_file: Path) -> Secrets:
    # Real environment variables win over .env, so a server can inject keys without a file.
    file_values = dotenv_values(env_file) if env_file.is_file() else {}

    def get(name: str) -> str | None:
        return os.environ.get(name) or file_values.get(name) or None

    return Secrets(binance_api_key=get("BINANCE_API_KEY"), binance_api_secret=get("BINANCE_API_SECRET"))
