from pathlib import Path

import pytest
from pydantic import ValidationError

from tradeagent import exchanges
from tradeagent.account.rules import MarketLimits, size_position
from tradeagent.config import ExchangeConfig, PaperAccountConfig
from tradeagent.journal import connect, migrate
from tradeagent.market.candles import ensure_venue, fill_quiet, repair_gaps, sync_candles
from tradeagent.venues import VENUES, Venue

MIN = 60_000
T0 = 1_790_000_040_000 - 1_790_000_040_000 % MIN


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "journal.db")
    migrate(c)
    yield c
    c.close()


def test_quiet_minutes_get_a_flat_candle_from_the_previous_close():
    rows = [[T0, 1.0, 1.2, 0.9, 1.1, 5.0], [T0 + 3 * MIN, 1.2, 1.3, 1.1, 1.25, 2.0]]
    filled = fill_quiet(rows, "1m", T0, T0 + 4 * MIN, prev_close=None)
    assert [r[0] for r in filled] == [T0 + i * MIN for i in range(5)]
    assert filled[1] == [T0 + MIN, 1.1, 1.1, 1.1, 1.1, 0.0]  # nothing traded: flat at the last close
    assert filled[4] == [T0 + 4 * MIN, 1.25, 1.25, 1.25, 1.25, 0.0]


def test_a_new_venue_clears_the_market_data_but_the_first_upgrade_keeps_it(conn):
    conn.execute("INSERT INTO candles VALUES ('XRP', '1m', ?, 1, 1, 1, 1, 1)", (T0,))
    conn.execute("INSERT INTO funding VALUES ('XRP', ?, 0.0001)", (T0,))
    assert ensure_venue(conn, "binance-usdm") is False  # existing journals hold Binance data
    assert conn.execute("SELECT count(*) FROM candles").fetchone()[0] == 1
    assert ensure_venue(conn, "coinbase-us") is True
    assert conn.execute("SELECT count(*) FROM candles").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM funding").fetchone()[0] == 0
    assert ensure_venue(conn, "coinbase-us") is False


class SparseClient:
    """A venue that sends no candle for minutes without trades."""
    venue = Venue("test-sparse", "test", "none", "USD", "test", candle_limit=3, sparse_candles=True)
    candle_limit = 3

    def __init__(self, traded: dict[int, list[float]]) -> None:
        self.traded = traded

    def fetch_ohlcv(self, ref, timeframe, since=None, limit=None):
        return [self.traded[t] for t in sorted(self.traded) if since <= t < since + limit * MIN]


def test_sync_stores_one_candle_per_minute_on_a_sparse_venue(conn):
    traded = {T0 + i * MIN: [T0 + i * MIN, 1.0 + i, 1.0 + i, 1.0 + i, 1.0 + i, 1.0] for i in (0, 1, 5, 9)}
    now = T0 + 20 * MIN  # minutes up to now - 3 are settled
    sync_candles(conn, SparseClient(traded), "XRP", "XPP", "1m", now, history_days=1)
    rows = conn.execute("SELECT open_time, close, volume FROM candles ORDER BY open_time").fetchall()
    times = [r[0] for r in rows]
    assert times[:10] == [T0 + i * MIN for i in range(10)], "minutes 2-4 and 6-8 filled"
    assert tuple(rows[3]) == (T0 + 3 * MIN, 2.0, 0.0)
    assert repair_gaps(conn, SparseClient(traded), "XRP", "XPP", "1m", T0, now) == 0


def test_contracts_are_whole_and_one_contract_must_fit_the_risk():
    rules = PaperAccountConfig(starting_balance=1000, risk_per_trade=0.02, leverage_cap=10)
    xpp = MarketLimits(step_size=1, min_qty=1, min_notional=0, contract_size=500)  # Coinbase: 500 XRP per contract
    sized = size_position(1000, 1.50, 1.465, rules, xpp)
    assert sized.qty == 500 and sized.risk_usd == pytest.approx(17.5)
    assert "1 contract(s) of 500" in sized.notes
    small = size_position(150, 1.50, 1.465, rules, xpp)
    assert small == "one contract (500 coins) would risk 17.50 (11.7% of the balance), more than allowed"
    binance = MarketLimits(step_size=0.1, min_qty=0.1, min_notional=5)  # coins, as before
    assert size_position(150, 1.50, 1.465, rules, binance).qty == pytest.approx(85.7)


def test_settings_need_a_market_for_the_chosen_venue():
    old = ExchangeConfig.model_validate({"name": "binance", "market_type": "usdm",
                                         "symbols": {"XRP": {"ccxt": "XRP/USDT:USDT", "tradingview": "BINANCE:XRPUSDT.P"}}})
    assert old.venue == "binance-usdm" and old.symbols["XRP"].markets == {"binance-usdm": "XRP/USDT:USDT"}
    with pytest.raises(ValidationError, match="no coinbase-us market"):
        ExchangeConfig.model_validate({"venue": "coinbase-us",
                                       "symbols": {"XRP": {"ccxt": "XRP/USDT:USDT", "tradingview": "BINANCE:XRPUSDT.P"}}})
    with pytest.raises(ValidationError, match="unknown venue"):
        ExchangeConfig.model_validate({"venue": "ftx", "symbols": {"XRP": {"tradingview": "X", "markets": {"ftx": "X"}}}})


def test_every_venue_names_its_ccxt_exchange():
    import ccxt

    for venue in VENUES.values():
        assert hasattr(ccxt, venue.ccxt_id), venue.id
        assert venue.who and venue.settle in ("USDT", "USD", "USDC")


def test_a_pem_private_key_survives_the_env_file(tmp_path: Path):
    env = tmp_path / ".env"
    pem = "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIabc\ndef==\n-----END EC PRIVATE KEY-----\n"
    values = {"apiKey": "organizations/abc-123/apiKeys/def-456", "secret": pem}
    assert exchanges.check("coinbase", values) == []
    exchanges.save(env, "coinbase", values)
    assert "\n-----END" not in env.read_text(encoding="utf-8")  # one line in the file
    assert exchanges.read(env, "coinbase") == {"apiKey": values["apiKey"], "secret": pem.strip()}


def test_after_a_venue_change_history_comes_newest_first_in_small_steps(conn):
    class DenseClient(SparseClient):
        venue = Venue("test-dense", "test", "none", "USD", "test", candle_limit=3)

    traded = {T0 + i * MIN: [T0 + i * MIN, 1.0, 1.0, 1.0, 1.0, 1.0] for i in range(60)}
    now = T0 + 60 * MIN
    client = DenseClient(traded)
    sync_candles(conn, client, "XRP", "X", "1m", now, history_days=1, backfill_pages=2)
    first = tuple(conn.execute("SELECT min(open_time), max(open_time) FROM candles").fetchone())
    assert first == (T0 + 53 * MIN, T0 + 59 * MIN)  # the newest pages first
    sync_candles(conn, client, "XRP", "X", "1m", now, history_days=1, backfill_pages=2)
    assert conn.execute("SELECT min(open_time) FROM candles").fetchone()[0] == T0 + 47 * MIN  # then 6 older
