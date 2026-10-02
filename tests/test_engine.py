"""Setup engine + tracker on synthetic snapshots and candles."""

import json

import pytest

from tradeagent.journal import connect, migrate
from tradeagent.setups.config import load_variants, register_variants
from tradeagent.setups.engine import SetupEngine
from tradeagent.sim.tracker import Tracker
from tradeagent.tv.snapshots import Snapshot, store_snapshot

M1, M5 = 60_000, 300_000
T0 = 1_790_000_100_000 - (1_790_000_100_000 % M5)  # a 5m boundary


def _values(buy=0, sell=0, hist=-1.0, vwap=100.0):
    return {
        "qtrend": {"buy": buy, "sell": sell, "strong_buy": 0, "strong_sell": 0, "trend_line": 100.0},
        "klinger": {"hist": hist, "kvo": 0.0, "signal": 0.0},
        "vwap": {"vwap": vwap, "upper1": None, "lower1": None, "upper2": None, "lower2": None},
        "zerolag": {"basis": 100.0, "upper_band": None, "lower_band": 99.0, "bullish_entry": 0,
                    "bearish_entry": 0, "bullish_trend": 0, "bearish_trend": 0},
        "atp_macd": {"hist": 0.0, "macd": 0.1, "signal": 0.0, "buy": 0, "sell": 0,
                     "bullish_divergence": 0, "bearish_divergence": 0},
    }


@pytest.fixture
def world(settings, repo_root):
    conn = connect(settings.resolve(settings.journal.path))
    migrate(conn)
    variants = [v for v in load_variants(repo_root / "config" / "setups.yaml") if v.name in ("v0", "filter_vwap")]
    register_variants(conn, variants)
    # 5m candles: lows step down so the 10-candle stop is easy to predict; 1m candles flat at 100.
    rows5 = [("XRP", "5m", T0 + i * M5, 100.0, 100.5, 99.0 + 0.01 * (i % 7), 100.2, 1.0) for i in range(-15, 15)]
    rows1 = [("XRP", "1m", T0 + i * M1, 100.1, 100.3, 99.9, 100.1, 1.0) for i in range(-75, 75)]
    conn.executemany("INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows5 + rows1)
    conn.commit()
    yield conn, variants, settings
    conn.close()


def _snap(conn, i, values, open_=100.0, close=100.2):
    store_snapshot(conn, Snapshot("XRP", "5m", T0 + i * M5, 1, T0 + i * M5 + M5 + 3000,
                                  values=values, ohlcv=[open_, 100.5, 99.0, close, 1.0]))


def test_trigger_confirms_within_window_and_opens_a_trade(world):
    conn, variants, settings = world
    _snap(conn, 0, _values(buy=1, hist=-5.0))        # trigger, Klinger red: not yet
    _snap(conn, 1, _values(hist=-1.0))                # still red
    _snap(conn, 2, _values(hist=2.0), close=100.4)    # green + bullish candle: confirmed
    counts = SetupEngine(settings, variants, conn).process()
    assert counts["trades_taken"] == 2  # v0 and filter_vwap (close 100.4 >= VWAP 100)
    trade = conn.execute("SELECT * FROM trades WHERE variant_id LIKE 'v0-%'").fetchone()
    assert trade["side"] == "long" and trade["confirm_time"] == T0 + 2 * M5
    assert trade["entry_time"] == T0 + 3 * M5 and trade["entry_ref"] == pytest.approx(100.1)
    expected_stop = min(99.0 + 0.01 * (i % 7) for i in range(-7, 3))  # last 10 candles up to the confirming one
    assert trade["stop_initial"] == pytest.approx(expected_stop)
    assert trade["target"] == pytest.approx(100.1 + 1.5 * (100.1 - expected_stop))
    assert conn.execute("SELECT status FROM setups WHERE variant_id = ?", (trade["variant_id"],)).fetchone()[0] == "confirmed"


def test_window_expiry_cancellation_and_filters(world):
    conn, variants, settings = world
    _snap(conn, 0, _values(buy=1))                    # long trigger, never confirmed...
    _snap(conn, 1, _values(sell=1))                   # ...cancelled by a short trigger
    for i in range(2, 6):
        _snap(conn, i, _values(hist=1.0), close=100.4)   # green: never confirms a short -> expires
    counts = SetupEngine(settings, variants, conn).process()
    statuses = dict(conn.execute("SELECT side, status FROM setups WHERE variant_id LIKE 'v0-%'").fetchall())
    assert statuses == {"long": "cancelled", "short": "expired"}
    assert counts["trades_taken"] == 0

    # A short that confirms below VWAP passes; a long below VWAP is a counterfactual for filter_vwap.
    _snap(conn, 6, _values(buy=1, hist=1.0, vwap=101.0), close=100.4)
    SetupEngine(settings, variants, conn).process()
    rows = dict(conn.execute("SELECT variant_id, taken FROM trades WHERE confirm_time = ?", (T0 + 6 * M5,)).fetchall())
    taken = {k.split("-")[0]: v for k, v in rows.items()}
    assert taken == {"v0": 1, "filter_vwap": 0}
    reason = conn.execute("SELECT reason FROM trades WHERE variant_id LIKE 'filter_vwap-%'").fetchone()[0]
    assert reason == "vwap"


def test_processing_twice_creates_nothing_new(world):
    conn, variants, settings = world
    _snap(conn, 0, _values(buy=1, hist=2.0), close=100.4)
    engine = SetupEngine(settings, variants, conn)
    engine.process()
    before = conn.execute("SELECT count(*) FROM trades").fetchone()[0]
    conn.execute("DELETE FROM engine_state")  # simulate lost progress: replay must not duplicate
    conn.commit()
    engine.process()
    assert conn.execute("SELECT count(*) FROM trades").fetchone()[0] == before == 2


def test_engine_waits_for_the_entry_candle(world):
    conn, variants, settings = world
    _snap(conn, 20, _values(buy=1, hist=2.0), close=100.4)  # entry candle (T0 + 21*5m) not stored yet
    counts = SetupEngine(settings, variants, conn).process()
    assert counts["candles"] == 0 and counts["trades_taken"] == 0


def test_tracker_closes_the_trade_at_the_target(world):
    conn, variants, settings = world
    _snap(conn, 0, _values(buy=1, hist=2.0), close=100.4)
    SetupEngine(settings, variants, conn).process()
    trade = conn.execute("SELECT id, target, entry_time FROM trades WHERE variant_id LIKE 'v0-%'").fetchone()
    hit = trade["entry_time"] + 80 * M1
    conn.execute("INSERT OR REPLACE INTO candles VALUES ('XRP', '1m', ?, 100.1, ?, 100.0, 100.2, 1.0)",
                 (hit, trade["target"] + 0.01))
    conn.commit()
    Tracker(settings, conn).update()
    row = conn.execute("SELECT status, exit_reason, exit_time, r_gross, r_net, fees_r FROM trades WHERE id = ?",
                       (trade["id"],)).fetchone()
    assert (row["status"], row["exit_reason"], row["exit_time"]) == ("closed", "target", hit)
    assert row["r_gross"] == pytest.approx(1.5)
    assert row["r_net"] < row["r_gross"] and row["fees_r"] > 0
    state = json.loads(conn.execute("SELECT state_json FROM trades WHERE id = ?", (trade["id"],)).fetchone()[0])
    assert state["closed"] is True
