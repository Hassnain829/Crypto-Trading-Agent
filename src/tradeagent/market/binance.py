"""Binance USDT-M perpetual futures through ccxt. Public market data needs no API key."""

from __future__ import annotations

import ccxt


def public_client(timeout_ms: int = 15_000) -> ccxt.binanceusdm:
    return ccxt.binanceusdm({"enableRateLimit": True, "timeout": timeout_ms})
