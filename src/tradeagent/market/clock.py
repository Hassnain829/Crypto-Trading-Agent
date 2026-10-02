"""Binance server time. The PC clock can drift, so candle timing uses the server clock."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

log = logging.getLogger("tradeagent.clock")


def _local_ms() -> int:
    return int(time.time() * 1000)


class ServerClock:
    def __init__(self, fetch_time: Callable[[], int] | None = None) -> None:
        if fetch_time is None:
            from tradeagent.market.binance import public_client

            fetch_time = public_client().fetch_time
        self._fetch_time = fetch_time
        self.offset_ms = 0  # server minus local
        self.measured = False

    def measure(self) -> int:
        """Measure the offset against the middle of the request, so latency is not counted. Blocking."""
        self._fetch_time()  # warm up the connection
        sent = _local_ms()
        server = self._fetch_time()
        self.offset_ms = server - (sent + _local_ms()) // 2
        self.measured = True
        log.info("server clock offset %+d ms", self.offset_ms)
        return self.offset_ms

    def now_ms(self) -> int:
        return _local_ms() + self.offset_ms

    def now_s(self) -> float:
        return self.now_ms() / 1000
