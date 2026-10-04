"""Trading venues: the exchange whose prices fill the demo trades and that will take the live orders.

Signals always come from the TradingView charts (Binance perpetuals by default). The venue only decides the
market data the trades are simulated on (candles, funding, contract sizes) and, from Phase 6, where orders go.
Every venue is reached through ccxt with public market data (no API key needed to simulate).

Facts below were checked on 2026-10-04 (ccxt 4.5.85 and the exchanges' public pages). Fees are the defaults
for a new account; the `costs` settings decide what the simulation uses.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("tradeagent.venues")


@dataclass(frozen=True)
class Venue:
    id: str
    label: str
    ccxt_id: str
    settle: str  # USDT | USD | USDC
    who: str  # who may open an account (the KYC country decides, not where the computer is)
    options: dict[str, Any] = field(default_factory=dict)
    candle_limit: int = 1000  # max candles per request
    sparse_candles: bool = False  # minutes without trades have no candle: they are filled flat
    funding_history: bool = True  # the funding history can be downloaded (else funding is not simulated)
    server_time: bool = True  # the exchange tells the time (else the computer's synced clock is used)
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005
    fee_note: str = ""
    max_leverage: float = 10


VENUES: dict[str, Venue] = {v.id: v for v in (
    Venue("binance-usdm", "Binance USDT-M perpetuals", "binanceusdm", "USDT",
          "Non-US residents. Binance's API refuses US IP addresses, so it cannot be used from a US VPS.",
          candle_limit=1500, fee_note="VIP 0: 0.02% maker, 0.05% taker"),
    Venue("coinbase-us", "Coinbase US perpetual-style futures", "coinbase", "USD",
          "US residents (Coinbase Financial Markets, CFTC regulated).",
          candle_limit=300, sparse_candles=True, funding_history=False,
          fee_note="from 0.02% per contract, at least $0.15 per contract, exchange/clearing/NFA fees included. "
                   "Contracts: XRP 500, SOL 5, LINK 50 coins. Funding accrues hourly and is not simulated."),
    Venue("kraken-futures", "Kraken Futures perpetuals (international)", "krakenfutures", "USD",
          "Non-US residents (Kraken Futures). US clients use Kraken Derivatives US, which has no public API yet.",
          candle_limit=2000, server_time=False, fee_note="0.02% maker, 0.05% taker"),
    Venue("coinbase-intl", "Coinbase International perpetuals", "coinbaseinternational", "USDC",
          "Eligible non-US residents in selected countries.",
          candle_limit=300, sparse_candles=True, server_time=False, maker_fee=0.0, taker_fee=0.0003,
          fee_note="0% maker, 0.03% taker for qualified traders; XRP and SOL up to 5x", max_leverage=5),
    Venue("bitget", "Bitget USDT-M perpetuals", "bitget", "USDT", "Non-US residents.",
          options={"defaultType": "swap"}, candle_limit=1000, fee_note="0.02% maker, 0.06% taker",
          taker_fee=0.0006),
    Venue("mexc", "MEXC USDT-M perpetuals", "mexc", "USDT", "Non-US residents.",
          options={"defaultType": "swap"}, candle_limit=1000, maker_fee=0.0, taker_fee=0.0002,
          fee_note="0% maker, 0.02% taker (check your tier)"),
)}

# Venues looked at but not usable for automated trading yet.
NOT_YET = {
    "kraken-us": "Kraken US perpetuals (Bitnomial, CFTC regulated): PXRPUH 100 XRP, PSOLUS 1 SOL, PLNKUD 10 LINK. "
                 "No public trading API was found on 2026-10-04; ask Kraken support about API access.",
}


def get_venue(venue_id: str) -> Venue:
    try:
        return VENUES[venue_id]
    except KeyError:
        raise ValueError(f"unknown venue {venue_id!r}; known: {', '.join(VENUES)}") from None


class MarketData:
    """Public market data of one venue through ccxt. Methods take the market as written in settings.yaml
    (a ccxt symbol such as XRP/USDT:USDT or the exchange's own id such as XPP-20DEC30-CDE)."""

    def __init__(self, venue: Venue | str, timeout_ms: int = 15_000) -> None:
        import ccxt

        self.venue = get_venue(venue) if isinstance(venue, str) else venue
        cls = getattr(ccxt, self.venue.ccxt_id)
        self.exchange = cls({"enableRateLimit": True, "timeout": timeout_ms, "options": dict(self.venue.options)})
        self.candle_limit = self.venue.candle_limit
        self._markets: dict[str, Any] | None = None

    def load_markets(self) -> dict[str, Any]:
        if self._markets is None:
            self._markets = self.exchange.load_markets()
        return self._markets

    def symbol(self, ref: str) -> str:
        markets = self.load_markets()
        if ref in markets:
            return ref
        by_id = self.exchange.markets_by_id.get(ref)
        if by_id:
            return (by_id[0] if isinstance(by_id, list) else by_id)["symbol"]
        raise ValueError(f"{self.venue.id}: market {ref!r} not found")

    def market(self, ref: str) -> dict[str, Any]:
        return self.load_markets()[self.symbol(ref)]

    def fetch_ohlcv(self, ref: str, timeframe: str, since: int | None = None, limit: int | None = None) -> list[list[float]]:
        return self.exchange.fetch_ohlcv(self.symbol(ref), timeframe, since=since, limit=limit or self.candle_limit)

    def fetch_funding_rate_history(self, ref: str, since: int | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        if not self.venue.funding_history:
            return []
        return self.exchange.fetch_funding_rate_history(self.symbol(ref), since=since, limit=limit)

    def fetch_time(self) -> int:
        """Server time in ms; the computer's clock where the venue does not provide one."""
        if self.venue.server_time:
            return int(self.exchange.fetch_time())
        return int(time.time() * 1000)


def market_data(settings: Any, timeout_ms: int = 15_000) -> MarketData:
    """The configured venue's market data client."""
    return MarketData(settings.exchange.venue, timeout_ms)
