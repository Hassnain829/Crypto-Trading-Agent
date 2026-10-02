"""Candle timing: which timeframes close at a boundary and which candle closed last. Times in UTC seconds."""

from __future__ import annotations

from collections.abc import Iterable

TF_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400,
}
TV_INTERVAL = {
    "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
    "1h": "60", "2h": "120", "4h": "240", "1d": "1D",
}


def last_closed_bar(now_s: float, timeframe: str) -> int:
    """Open time of the newest candle that has fully closed at `now_s`."""
    tf = TF_SECONDS[timeframe]
    return int(now_s // tf) * tf - tf


def next_boundary(now_s: float, step_s: int) -> int:
    """The next multiple of `step_s` strictly after `now_s`."""
    return (int(now_s // step_s) + 1) * step_s


def closing_at(boundary_s: int, timeframes: Iterable[str]) -> list[str]:
    """Timeframes whose candles close exactly at `boundary_s`."""
    return [tf for tf in timeframes if boundary_s % TF_SECONDS[tf] == 0]
