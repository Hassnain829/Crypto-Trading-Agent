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
    tradingview: str  # the signal chart (TradingView symbol)
    markets: dict[str, str] = Field(default_factory=dict)  # venue -> market (ccxt symbol or the exchange's id)
    ccxt: str | None = None  # older settings files: the Binance USDT-M market

    @model_validator(mode="after")
    def _legacy_binance_market(self) -> SymbolConfig:
        if self.ccxt and "binance-usdm" not in self.markets:
            self.markets["binance-usdm"] = self.ccxt
        return self


class ExchangeConfig(_Section):
    # The venue fills the demo trades with its own prices and (Phase 6) takes the live orders; see venues.py.
    venue: str = "binance-usdm"
    name: str | None = None  # older settings files
    market_type: str | None = None  # older settings files
    symbols: dict[str, SymbolConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def _venue_has_every_market(self) -> ExchangeConfig:
        from tradeagent.venues import get_venue

        get_venue(self.venue)
        missing = [coin for coin, cfg in self.symbols.items() if self.venue not in cfg.markets]
        if missing:
            raise ValueError(f"exchange.symbols has no {self.venue} market for {missing}")
        return self


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
    launcher: str = "scripts/launch_tradingview_debug.ps1"
    catalog: str = "config/indicators.yaml"
    signal_version: int = Field(ge=1)
    min_bars: int = Field(default=1500, ge=300, le=10_000)
    read_delay_s: float = Field(default=3.0, ge=0, le=60)
    prepare_timeout_s: float = Field(default=30.0, ge=5, le=300)
    stuck_reload_after_s: float = Field(default=240.0, ge=30)
    draw_trades: bool = True  # draw the paper account's trades on the AGENT charts (synced to all layouts)
    # TradingView Desktop's memory grows over days (5.6 GB after 4 days on an 8 GB VPS). Above this many MB the
    # agent restarts it right after a cycle, at most once per restart_min_gap_hours. None = never.
    restart_above_mb: int | None = Field(default=4000, ge=1500)
    restart_min_gap_hours: float = Field(default=6.0, ge=1)
    # Time zone of the AGENT charts' time axis and of the dashboard's times: "system" (this computer's) or an
    # IANA name such as "Asia/Karachi". Display only: stored times are UTC and candles do not change.
    timezone: str = "system"
    layouts: dict[str, str] = Field(min_length=1)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        if value != "system":
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError(f"unknown time zone {value!r} (use 'system' or a name like 'Asia/Karachi')") from exc
        return value

    @field_validator("layouts")
    @classmethod
    def _has_htf(cls, value: dict[str, str]) -> dict[str, str]:
        if "AGENT-HTF" not in value:
            raise ValueError("layouts must include AGENT-HTF")
        return value


class MarketDataConfig(_Section):
    history_days: int = Field(default=35, ge=1, le=365)
    candle_timeframes: list[str] = Field(default_factory=lambda: ["1m", "5m", "15m"])
    # Reference markets synced as 5m candles only (on Binance USDT-M): BTC's moves, for filters.btc_shock_wait_minutes.
    reference_markets: dict[str, str] = Field(default_factory=lambda: {"BTC": "BTC/USDT:USDT"})
    fear_greed: bool = True  # sync the daily Fear & Greed Index (alternative.me), for filters.fear_greed_extremes

    @field_validator("candle_timeframes")
    @classmethod
    def _known(cls, value: list[str]) -> list[str]:
        unknown = [tf for tf in value if tf not in KNOWN_TIMEFRAMES]
        if unknown:
            raise ValueError(f"unknown timeframes {unknown}")
        if "1m" not in value:
            raise ValueError("1m candles are required to track shadow trades")
        return value


class ShadowConfig(_Section):
    setups: str = "config/setups.yaml"
    max_hold_hours: float = Field(default=72, gt=0, le=24 * 30)


class CostsConfig(_Section):
    maker_fee: float = Field(ge=0, le=0.01)
    taker_fee: float = Field(ge=0, le=0.01)
    slippage: float = Field(ge=0, le=0.01)


class PaperAccountConfig(_Section):
    """Account rules. null = no limit (the paper account takes every signal; live limits are set before going live)."""

    starting_balance: float = Field(gt=0)
    risk_per_trade: float = Field(gt=0, le=0.05)
    # Risk on quality-A trades (confirmed by a 15m Trendline breakout); None = risk_per_trade for every trade.
    risk_tier_a: float | None = Field(default=None, gt=0, le=0.05)
    max_positions: int | None = Field(default=None, ge=1, le=100)
    max_positions_per_coin: int | None = Field(default=None, ge=1, le=50)
    daily_loss_stop: float | None = Field(default=None, gt=0, le=0.5)
    # Open-risk budget: the open positions together may lose at most this share of the balance at their stops.
    # A new trade that would go over it is made smaller (never skipped unless the budget is used up). None = off.
    max_open_risk: float | None = Field(default=None, gt=0, le=0.5)
    leverage_cap: float = Field(ge=1, le=50)
    # Coins the account trades; None = every coin. The shadow book keeps testing every coin either way.
    symbols: list[str] | None = None
    # False: a signal against a coin's open position is skipped, so a coin never holds a long and a short together.
    allow_opposite: bool = True
    # True: max_positions never blocks a coin's first position (every coin can always hold one).
    first_position_always: bool = False
    # Drawdown brake: while the balance is this share below its highest balance, every trade risks brake_factor
    # times its normal risk; back to normal at a new high. None = off. Research 2026-10-21: at 10% and half the risk,
    # the 4-year drawdown fell from 62% to 42% and the return halved.
    drawdown_brake: float | None = Field(default=None, gt=0, le=0.5)
    brake_factor: float = Field(default=0.5, gt=0, le=1)

    @model_validator(mode="after")
    def _per_coin_within_total(self) -> PaperAccountConfig:
        if self.max_positions_per_coin is not None and self.max_positions is not None \
                and self.max_positions_per_coin > self.max_positions:
            raise ValueError("max_positions_per_coin cannot be larger than max_positions")
        return self


class GoalConfig(_Section):
    min_trades: int = Field(ge=1)
    min_days: int = Field(ge=1)
    min_expectancy_r: float
    # The expectancy must be above this with 90% confidence (cluster bootstrap, account/report.py edge_lower_bound).
    min_edge_lower_r: float = 0.0
    min_profit_factor: float = Field(gt=0)
    max_drawdown: float = Field(gt=0, lt=1)
    min_snapshot_coverage: float = Field(gt=0, le=1)


class LiveAccountConfig(PaperAccountConfig):
    """Limits for live trading (Phase 6). Edited in the dashboard; the live preview replays trades through them."""

    exchange: str | None = None  # older settings files; live orders go to the trading venue (exchange.venue)


class ResearchConfig(_Section):
    enabled: bool = False  # the daily Claude research run (Phase 5)
    daily_time_utc: str = Field(default="06:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class LearningConfig(_Section):
    """How experiments are judged (Phase 5). A challenger wins only if every rule holds."""

    min_trades: int = Field(default=100, ge=10)  # closed trades of the challenger and the baseline in the same period
    min_edge_r: float = Field(default=0.05, ge=0)  # challenger expectancy >= baseline + this
    max_drawdown_worse: float = Field(default=0.25, ge=0, le=2)  # max drawdown (R) at most this much worse
    reconfirm_trades: int = Field(default=50, ge=10)  # fresh trades the winner must stay ahead on
    max_challengers: int = Field(default=15, ge=1, le=40)
    auto_promote: bool = True  # a confirmed winner becomes the demo baseline by itself (live always needs approval)
    screen_on_history: bool = True  # proposals must first beat the baseline in both halves of the history
    # ...and then in both halves of the long research history (years of Binance candles with research-only indicator
    # values, learning/long_screen.py), when that journal exists. A short history cannot tell a good rule from a
    # lucky period (2026-10-21: the forward leaders session_07_21/13_21 made about 0R over 4 years).
    screen_on_long_history: bool = True
    long_history: str | None = "data/research/long4/journal.db"
    long_history_years: int | None = Field(default=3, ge=1, le=10)  # only the newest N years of it (None = all)
    # Coins of the leaderboard's long backtest (None = the demo's coins). Proposals are always judged on the demo's coins.
    long_backtest_coins: list[str] | None = Field(default_factory=lambda: ["XRP", "SOL", "ETH", "BTC"])


class AlertsConfig(_Section):
    """Messages to the user's phone through the ntfy app (alerts.py). They need NTFY_TOPIC in .env."""

    enabled: bool = True
    trades: bool = True  # a message for every demo trade opened and closed
    failed_cycles: int = Field(default=3, ge=1, le=100)  # alert after this many cycles in a row with failed reads
    clock_offset_ms: int = Field(default=1000, ge=100)  # alert when this computer's clock is off by more
    stale_minutes: float = Field(default=15, ge=6)  # the dashboard alerts when the agent's last cycle is older
    status_hours: int | None = Field(default=4, ge=1, le=24)  # open positions every N hours (UTC multiples); None = off
    repeat_hours: float = Field(default=6, ge=0.5)  # an unsolved problem is repeated at most this often


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
    bitget_api_key: SecretStr | None = None
    bitget_api_secret: SecretStr | None = None
    bitget_api_passphrase: SecretStr | None = None
    mexc_api_key: SecretStr | None = None
    mexc_api_secret: SecretStr | None = None
    coinbase_api_key: SecretStr | None = None
    coinbase_api_secret: SecretStr | None = None
    ntfy_topic: SecretStr | None = None  # alerts.py: the phone app subscribes to this topic (works like a password)
    ntfy_server: SecretStr | None = None  # default https://ntfy.sh
    healthcheck_url: SecretStr | None = None  # pinged after every cycle (an outside dead-man switch)

    @property
    def has_binance_keys(self) -> bool:
        return bool(self.binance_api_key and self.binance_api_secret)


class Settings(_Section):
    exchange: ExchangeConfig
    timeframes: TimeframesConfig
    tradingview: TradingViewConfig
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig)
    shadow: ShadowConfig = Field(default_factory=ShadowConfig)
    costs: CostsConfig
    paper_account: PaperAccountConfig
    live_account: LiveAccountConfig = Field(default_factory=lambda: LiveAccountConfig(
        starting_balance=150, risk_per_trade=0.02, max_positions=2, max_positions_per_coin=1,
        daily_loss_stop=0.10, leverage_cap=10))
    goal: GoalConfig
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    journal: JournalConfig = Field(default_factory=JournalConfig)

    _root: Path = PrivateAttr(default_factory=Path.cwd)
    _secrets: Secrets = PrivateAttr(default_factory=Secrets)

    @model_validator(mode="after")
    def _layout_per_symbol(self) -> Settings:
        missing = [f"AGENT-{coin}" for coin in self.exchange.symbols if f"AGENT-{coin}" not in self.tradingview.layouts]
        if missing:
            raise ValueError(f"tradingview.layouts is missing {missing}")
        for section in ("paper_account", "live_account"):
            unknown = [c for c in getattr(self, section).symbols or [] if c not in self.exchange.symbols]
            if unknown:
                raise ValueError(f"{section}.symbols has coins that are not in exchange.symbols: {unknown}")
        untracked = [tf for tf in self.timeframes.trade if tf not in self.market_data.candle_timeframes]
        if untracked:
            raise ValueError(f"market_data.candle_timeframes must include the trading timeframes {untracked}")
        return self

    @property
    def venue(self) -> str:
        return self.exchange.venue

    def market(self, coin: str, venue: str | None = None) -> str:
        """The coin's market on the venue (default: the configured venue)."""
        return self.exchange.symbols[coin].markets[venue or self.exchange.venue]

    def markets(self, venue: str | None = None) -> dict[str, str]:
        """Agent coin -> market on the venue."""
        return {coin: self.market(coin, venue) for coin in self.exchange.symbols}

    def layout_for(self, coin: str) -> str:
        """Layout id of the chart tab that shows `coin` on the trading timeframes."""
        return self.tradingview.layouts[f"AGENT-{coin}"]

    @property
    def htf_layout(self) -> str:
        return self.tradingview.layouts["AGENT-HTF"]

    @property
    def all_timeframes(self) -> list[str]:
        return list(dict.fromkeys(self.timeframes.trade + self.timeframes.overview))

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

    return Secrets(**{field: get(field.upper()) for field in Secrets.model_fields})
