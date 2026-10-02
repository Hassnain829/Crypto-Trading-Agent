import pytest

from tradeagent.journal import connect, migrate
from tradeagent.market.candles import fetch_range, find_gaps, latest_closed_open, store_candles

M1 = 60_000


class FakeClient:
    """Serves 1m candles from 0 to 9_999 minutes, at most `limit` per call, like Binance."""

    def __init__(self):
        self.calls = 0

    def fetch_ohlcv(self, symbol, timeframe, since, limit):
        self.calls += 1
        start = since // M1
        return [[m * M1, 1.0, 2.0, 0.5, 1.5, 10.0] for m in range(start, min(start + limit, 10_000))]


def test_fetch_range_pages_and_stops_at_the_last_closed_candle():
    client = FakeClient()
    rows = fetch_range(client, "XRP/USDT:USDT", "1m", 0, 3_200 * M1)
    assert len(rows) == 3_201 and rows[-1][0] == 3_200 * M1
    assert client.calls == 3  # 1500 + 1500 + 201


def test_latest_closed_open_excludes_the_forming_candle():
    assert latest_closed_open(10 * M1 + 5_000, "1m") == 9 * M1
    assert latest_closed_open(10 * M1, "1m") == 9 * M1


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "journal.db")
    migrate(c)
    yield c
    c.close()


def test_find_gaps(conn):
    store_candles(conn, "XRP", "1m", [[m * M1, 1, 1, 1, 1, 1] for m in [0, 1, 2, 5, 6, 9]])
    assert find_gaps(conn, "XRP", "1m", 0, 9 * M1) == [(3 * M1, 4 * M1), (7 * M1, 8 * M1)]
