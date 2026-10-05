"""Setup engine + tracker on synthetic snapshots and candles."""

import json

import pytest

from tradeagent.journal import connect, migrate
from tradeagent.setups.config import SetupParams, Variant, deep_merge, load_variants, register_variants
from tradeagent.setups.engine import SetupEngine
from tradeagent.sim.tracker import Tracker
from tradeagent.tv.snapshots import Snapshot, store_snapshot

M1, M5, H = 60_000, 300_000, 3_600_000
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


# Fixed rules (the original video checklist), so these tests do not change when config/setups.yaml evolves.
VIDEO_RULES = {
    "timeframes": ["5m", "15m"],
    "trigger": {"indicator": "qtrend", "long": "buy", "short": "sell"},
    "confirmation": {"window": 3, "klinger": True, "candle_direction": True},
    "filters": {"vwap": False, "macd_trend": False, "htf": "none", "min_stop_pct": 0.0},
    "stop": {"lookback": 10},
    "exit": {"mode": "fixed", "take_profit_r": 1.5, "partial_r": 1.0, "partial_fraction": 0.5, "trail_lookback": 3},
}


def _variant(name, override=None, role="challenger"):
    return Variant(name, SetupParams.model_validate(deep_merge(VIDEO_RULES, override or {})), role)


@pytest.fixture
def world(settings, repo_root):
    conn = connect(settings.resolve(settings.journal.path))
    migrate(conn)
    variants = [_variant("v0", role="baseline"), _variant("filter_vwap", {"filters": {"vwap": True}})]
    register_variants(conn, variants)
    # 5m candles: lows step down so the 10-candle stop is easy to predict (both stops > 1% away);
    # 1m candles flat at 100.
    rows5 = [("XRP", "5m", T0 + i * M5, 100.0, 101.5, 99.0 + 0.01 * (i % 7), 100.2, 1.0) for i in range(-15, 15)]
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


def _with(world, repo_root, custom):
    """The world's variants plus custom ones (overrides on the fixed video rules)."""
    conn, variants, settings = world
    extra = [_variant(name, override) for name, override in custom.items()]
    register_variants(conn, variants + extra)
    return conn, variants + extra, settings


def _trade(conn, name, side=None):
    query = "SELECT * FROM trades WHERE variant_id LIKE ?" + (" AND side = ?" if side else "")
    return conn.execute(query, (f"{name}-%", side) if side else (f"{name}-%",)).fetchone()


def test_own_trend_and_session_filters(world, repo_root):
    conn, variants, settings = _with(world, repo_root, custom={
        "zl_own": {"filters": {"zl_own": True}},
        "day": {"filters": {"session_utc": [7, 21]}},
        "night": {"filters": {"session_utc": [0, 7]}},
    })
    _snap(conn, 0, _values(sell=1, hist=-2.0), open_=100.4, close=100.0)  # short against a bullish Zero Lag
    SetupEngine(settings, variants, conn).process()
    assert _trade(conn, "v0")["taken"] == 1
    assert (_trade(conn, "zl_own")["taken"], _trade(conn, "zl_own")["reason"]) == (0, "zl_own")
    assert _trade(conn, "day")["taken"] == 1  # entry at 14:20 UTC
    assert (_trade(conn, "night")["taken"], _trade(conn, "night")["reason"]) == (0, "session")


def test_against_4h_filter(world, repo_root):
    conn, variants, settings = _with(world, repo_root, custom={"against": {"filters": {"htf": "against_4h"}}})
    four_hours = 4 * H
    bar_4h = T0 - T0 % four_hours - four_hours  # the last closed 4h candle at the entry
    bear = _values()
    bear["zerolag"].update(lower_band=None, upper_band=101.0)
    store_snapshot(conn, Snapshot("XRP", "4h", bar_4h, 1, bar_4h + four_hours + 3000, values=bear,
                                  ohlcv=[100.0, 101.0, 99.0, 100.5, 1.0]))
    _snap(conn, 0, _values(buy=1, hist=2.0), close=100.4)  # long while the 4h trend is bearish: against it
    _snap(conn, 1, _values(sell=1, hist=-2.0), open_=100.4, close=100.0)  # short: with the 4h trend
    SetupEngine(settings, variants, conn).process()
    assert _trade(conn, "against", side="long")["taken"] == 1
    short = _trade(conn, "against", side="short")
    assert (short["taken"], short["reason"]) == (0, "htf_against_4h")


def test_moved_stops_keep_the_baseline_target(world, repo_root):
    conn, variants, settings = _with(world, repo_root, custom={
        "wide": {"stop": {"multiplier": 2.0}},
        "hourly": {"stop": {"anchor": "1h"}},
    })
    hour = T0 - T0 % H
    conn.executemany("INSERT INTO candles VALUES ('XRP', '1h', ?, 100.0, 100.6, ?, 100.2, 1.0)",
                     [(hour - k * H, 98.0 if k == 6 else 99.5) for k in range(1, 11)])
    conn.commit()
    _snap(conn, 0, _values(buy=1, hist=2.0), close=100.4)
    SetupEngine(settings, variants, conn).process()
    base, wide, hourly = (_trade(conn, name) for name in ("v0", "wide", "hourly"))
    distance = base["entry_ref"] - base["stop_initial"]
    assert wide["stop_initial"] == pytest.approx(base["entry_ref"] - 2 * distance)
    assert hourly["stop_initial"] == pytest.approx(98.0)  # the 1h swing is further than the 5m swing
    assert wide["target"] == pytest.approx(base["target"]) and hourly["target"] == pytest.approx(base["target"])


def test_opposite_signal_closes_the_trade_at_the_next_open(world, repo_root):
    conn, variants, settings = _with(world, repo_root, custom={"opposite": {"exit": {"opposite_signal": True}}})
    _snap(conn, 0, _values(buy=1, hist=2.0), close=100.4)  # long, entry at T0 + 5m
    _snap(conn, 3, _values(sell=1, hist=-2.0), open_=100.4, close=100.0)  # opposite arrow on candle 3
    counts = SetupEngine(settings, variants, conn).process()
    assert counts["exits_scheduled"] == 1
    Tracker(settings, conn).update()
    long_trade = _trade(conn, "opposite", side="long")
    assert (long_trade["status"], long_trade["exit_reason"]) == ("closed", "opposite signal")
    assert long_trade["exit_time"] == T0 + 4 * M5  # the 1m open right after candle 3 closed
    assert _trade(conn, "v0", side="long")["status"] == "open"  # the baseline keeps its trade


def test_time_stop_closes_after_n_candles(world, repo_root):
    conn, variants, settings = _with(world, repo_root, custom={"timed": {"exit": {"max_candles": 3}}})
    _snap(conn, 0, _values(buy=1, hist=2.0), close=100.4)
    SetupEngine(settings, variants, conn).process()
    Tracker(settings, conn).update()
    timed = _trade(conn, "timed")
    assert (timed["status"], timed["exit_reason"]) == ("closed", "time stop")
    assert timed["exit_time"] == timed["entry_time"] + 3 * M5
    assert _trade(conn, "v0")["status"] == "open"


def test_atp_macd_trigger(world, repo_root):
    conn, variants, settings = _with(world, repo_root, custom={
        "macd": {"trigger": {"indicator": "atp_macd", "long": "buy", "short": "sell"}}})
    values = _values(hist=2.0)
    values["atp_macd"]["buy"] = 1  # no Q-Trend arrow: only the MACD variant may trade
    _snap(conn, 0, values, close=100.4)
    SetupEngine(settings, variants, conn).process()
    assert _trade(conn, "macd")["side"] == "long" and _trade(conn, "v0") is None


def test_limit_entry_fills_only_when_the_entry_minute_trades_through(world, repo_root):
    conn, variants, settings = _with(world, repo_root, custom={"limit": {"entry": {"mode": "limit"}}})
    _snap(conn, 0, _values(buy=1, hist=2.0), close=100.4)  # entry minute T0+5m: low 99.9 < open 100.1
    with conn:  # the next long's entry minute never trades below its open
        conn.execute("UPDATE candles SET low = open WHERE symbol = 'XRP' AND timeframe = '1m' AND open_time = ?",
                     (T0 + 6 * M5,))
    _snap(conn, 5, _values(buy=1, hist=2.0), close=100.4)
    counts = SetupEngine(settings, variants, conn).process()
    filled, missed = conn.execute(
        "SELECT * FROM trades WHERE variant_id LIKE 'limit-%' ORDER BY entry_time").fetchall()
    assert filled["status"] == "open" and json.loads(filled["state_json"])["entry_fill"] == pytest.approx(100.1)
    assert (missed["status"], missed["reason"]) == ("missed", "limit not filled")
    assert counts["trades_missed"] == 1
    assert conn.execute("SELECT count(*) FROM trades WHERE variant_id LIKE 'v0-%'").fetchone()[0] == 2


def test_the_real_setups_file_loads(repo_root):
    from tradeagent.tv.catalog import load_catalog

    variants = load_variants(repo_root / "config" / "setups.yaml", load_catalog(repo_root / "config" / "indicators.yaml"))
    assert variants[0].role == "baseline" and len({v.name for v in variants}) == len(variants)


def test_engine_waits_for_a_quiet_entry_minute_to_get_its_candle(world):
    conn, variants, settings = world
    conn.executemany("INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     [("XRP", "1m", T0 + i * M1, 100.1, 100.3, 99.9, 100.1, 1.0) for i in (76, 77)])
    _snap(conn, 14, _values(buy=1, hist=2.0), close=100.4)  # entry minute T0+75m: no trades, no candle yet
    counts = SetupEngine(settings, variants, conn).process()
    assert counts["no_entry_candle"] == 0 and counts["trades_taken"] == 0  # waited instead of skipping the signal
    conn.execute("INSERT INTO candles VALUES ('XRP', '1m', ?, 100.1, 100.1, 100.1, 100.1, 0)", (T0 + 75 * M1,))
    counts = SetupEngine(settings, variants, conn).process()  # the flat candle arrived once the minute settled
    assert counts["trades_taken"] == 2


def test_a_new_option_at_its_default_keeps_the_variant_ids():
    from tradeagent.setups.config import hashable_params

    plain = _variant("v0")
    explicit = _variant("v0", {"entry": {"limit_minutes": 1}})
    assert plain.id == explicit.id  # adding an option must not rename stored variants
    assert "limit_minutes" not in hashable_params(plain.params)["entry"]
    assert _variant("v0", {"entry": {"limit_minutes": 3}}).id != plain.id


def test_a_resting_limit_order_fills_in_a_later_minute(world, repo_root):
    conn, variants, settings = world
    resting = _variant("rest3", {"entry": {"mode": "limit", "limit_minutes": 3}}, role="baseline")
    one = _variant("rest1", {"entry": {"mode": "limit", "limit_minutes": 1}})
    register_variants(conn, [resting, one])
    entry = T0 + 5 * M1  # the confirming candle (i=0) closes at T0+5m
    conn.execute("UPDATE candles SET low = 100.1 WHERE timeframe = '1m' AND open_time IN (?, ?)",
                 (entry, entry + M1))  # minutes 1 and 2 do not trade through 100.1
    conn.execute("UPDATE candles SET low = 100.0 WHERE timeframe = '1m' AND open_time = ?", (entry + 2 * M1,))
    _snap(conn, 0, _values(buy=1, hist=2.0), close=100.4)
    SetupEngine(settings, [resting, one], conn).process()
    rows = {r["variant_id"].split("-")[0]: r for r in conn.execute("SELECT * FROM trades")}
    assert rows["rest1"]["status"] == "missed"
    assert rows["rest3"]["status"] == "open" and rows["rest3"]["entry_time"] == entry + 2 * M1
    assert rows["rest3"]["entry_ref"] == pytest.approx(100.1)  # the price of the first minute's open


def test_an_offset_limit_waits_for_a_pullback_and_keeps_the_planned_target(world):
    conn, variants, settings = world
    pull = _variant("pull", {"entry": {"mode": "limit", "limit_minutes": 30, "offset_r": 0.5}}, role="baseline")
    register_variants(conn, [pull])
    _snap(conn, 0, _values(buy=1, hist=2.0), close=100.4)
    SetupEngine(settings, [pull], conn).process()
    t = conn.execute("SELECT * FROM trades").fetchone()
    swing = min(99.0 + 0.01 * (i % 7) for i in range(-7, 3))
    reference = 100.1 - swing
    assert t["status"] == "missed"  # the 1m lows (99.9) never reach the price halfway to the stop
    conn.execute("DELETE FROM trades")
    conn.execute("DELETE FROM setups")
    conn.execute("DELETE FROM engine_state")
    conn.execute("UPDATE candles SET low = 99.0 WHERE timeframe = '1m' AND open_time = ?", (T0 + 9 * M1,))
    SetupEngine(settings, [pull], conn).process()
    t = conn.execute("SELECT * FROM trades").fetchone()
    assert t["status"] == "open" and t["entry_time"] == T0 + 9 * M1
    assert t["entry_ref"] == pytest.approx(100.1 - 0.5 * reference)
    assert t["target"] == pytest.approx(100.1 + 1.5 * reference)  # the planned target, not 1.5R from the fill


def test_trend_15m_filters_5m_signals_against_the_15m_trend(world):
    conn, variants, settings = world
    with15 = _variant("with15", {"filters": {"trend_15m": True}}, role="baseline")
    register_variants(conn, [with15])
    bearish15 = {"zerolag": {"upper_band": 101.0, "lower_band": None, "basis": 100.0}}
    store_snapshot(conn, Snapshot("XRP", "15m", T0 - 15 * M1, 1, T0, values=bearish15, ohlcv=[100, 101, 99, 100, 1]))
    _snap(conn, 0, _values(buy=1, hist=2.0), close=100.4)
    SetupEngine(settings, [with15], conn).process()
    t = conn.execute("SELECT taken, reason FROM trades").fetchone()
    assert (t["taken"], t["reason"]) == (0, "trend_15m")


def test_a_stop_floor_widens_a_tight_swing_instead_of_skipping_it(world):
    conn, variants, settings = world
    floor = _variant("floor", {"filters": {"min_stop_pct": 1.5}, "stop": {"min_pct": 1.5}}, role="baseline")
    skip = _variant("skip", {"filters": {"min_stop_pct": 1.5}})
    register_variants(conn, [floor, skip])
    _snap(conn, 0, _values(buy=1, hist=2.0), close=100.4)  # the swing stop is ~1.1% below the 100.1 entry
    SetupEngine(settings, [floor, skip], conn).process()
    rows = {r["variant_id"].split("-")[0]: r for r in conn.execute("SELECT * FROM trades")}
    assert (rows["skip"]["taken"], rows["skip"]["reason"]) == (0, "min_stop_pct")
    f = rows["floor"]
    assert f["taken"] == 1 and f["stop_initial"] == pytest.approx(100.1 * (1 - 0.015))
    assert f["target"] == pytest.approx(100.1 + 1.5 * 100.1 * 0.015)
