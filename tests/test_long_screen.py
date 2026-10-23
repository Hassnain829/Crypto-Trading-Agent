"""The long-history screen and backtest (learning/long_screen.py) and the two-stage proposal screen."""

import json

import pytest
import yaml

from tradeagent.journal import connect, migrate
from tradeagent.learning import experiments as ex
from tradeagent.learning import long_screen, screen
from tradeagent.setups.config import SetupParams, Variant, register_variants
from tradeagent.tv.snapshots import Snapshot, store_snapshot

M1, M5 = 60_000, 300_000
T0 = 1_790_000_100_000 - (1_790_000_100_000 % M5)
RULES = {
    "timeframes": ["5m"],
    "trigger": {"indicator": "qtrend", "long": "buy", "short": "sell"},
    "confirmation": {"window": 3, "klinger": True, "candle_direction": True},
    "filters": {"vwap": False, "macd_trend": False, "htf": "none", "min_stop_pct": 0.0},
    "stop": {"lookback": 10},
    "exit": {"mode": "fixed", "take_profit_r": 1.5, "partial_r": 1.0, "partial_fraction": 0.5, "trail_lookback": 3},
}


def _values(buy=0, hist=-1.0):
    return {"qtrend": {"buy": buy, "sell": 0, "strong_buy": 0, "strong_sell": 0, "trend_line": 100.0},
            "klinger": {"hist": hist, "kvo": 0.0, "signal": 0.0}}


@pytest.fixture
def research(settings, tmp_path):
    """A tiny long research journal: one XRP long that reaches its target."""
    path = tmp_path / "long.db"
    src = connect(path)
    migrate(src)
    rows5 = [("XRP", "5m", T0 + i * M5, 100.0, 101.5, 99.0 + 0.01 * (i % 7), 100.2, 1.0) for i in range(-15, 15)]
    rows1 = [("XRP", "1m", T0 + i * M1, 100.1, 100.3, 99.9, 100.1, 1.0) for i in range(-75, 150)]
    src.executemany("INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows5 + rows1)
    src.execute("UPDATE candles SET high = 103.0 WHERE timeframe = '1m' AND open_time = ?", (T0 + 100 * M1,))
    src.execute("INSERT INTO market_info (symbol, tick_size, step_size, min_qty, min_notional, updated_at)"
                " VALUES ('XRP', 0.0001, 0.1, 0.1, 5.0, 0)")
    store_snapshot(src, Snapshot("XRP", "5m", T0, 6, T0 + M5 + 3000, values=_values(buy=1, hist=2.0),
                                 ohlcv=[100.0, 100.5, 99.0, 100.4, 1.0], source="backfill"))
    src.commit()
    src.close()
    settings.learning.long_history = str(path)
    return path


def test_the_overlay_replays_the_research_history_without_writing_it(settings, research):
    v = Variant("v0", SetupParams.model_validate(RULES), "baseline")
    db, coins, _ = long_screen.replay(settings, [v], "test")
    try:
        assert coins == ["XRP"]
        t = db.execute("SELECT status, exit_reason, r_net FROM trades").fetchone()
        assert (t["status"], t["exit_reason"]) == ("closed", "target") and t["r_net"] > 1.0
    finally:
        db.close()
    src = connect(research)
    assert src.execute("SELECT count(*) FROM trades").fetchone()[0] == 0  # the research journal is only read
    src.close()


def test_a_resumed_replay_continues_and_other_variants_start_over(settings, research):
    v = Variant("v0", SetupParams.model_validate(RULES), "baseline")
    db, _, _ = long_screen.replay(settings, [v], "test")
    db.close()
    db, _, _ = long_screen.replay(settings, [v], "test", resume=True)  # nothing left to do: the same one trade
    try:
        assert db.execute("SELECT count(*) FROM trades").fetchone()[0] == 1
    finally:
        db.close()
    other = Variant("v1", SetupParams.model_validate({**RULES, "stop": {"lookback": 12}}), "baseline")
    db, _, _ = long_screen.replay(settings, [other], "test", resume=True)  # not the same variants: a fresh journal
    try:
        assert {r[0] for r in db.execute("SELECT DISTINCT variant_id FROM trades")} == {other.id}
    finally:
        db.close()


def test_the_backtest_stores_a_result_per_variant_for_the_leaderboard(settings, research):
    conn = connect(settings.resolve(settings.journal.path))
    migrate(conn)
    v = Variant("v0", SetupParams.model_validate(RULES), "baseline")
    lines = long_screen.backtest(settings, conn, [v])
    row = conn.execute("SELECT variant_id, params_hash, result_json FROM long_results").fetchone()
    result = json.loads(row["result_json"])
    assert row["variant_id"] == v.id and row["params_hash"] == v.params_hash and v.id in lines[0]
    assert result["all"]["trades"] == 1 and result["account"]["all"]["trades"] == 1
    assert result["account"]["all"]["return_pct"] > 0  # the one target in the demo account at the demo rules
    assert long_screen.missing(conn, [v]) == []
    conn.close()


def test_without_the_research_journal_the_long_screen_is_off(settings, tmp_path):
    settings.learning.long_history = str(tmp_path / "missing.db")
    assert long_screen.source(settings) is None and not screen.long_screen_on(settings)
    settings.learning.long_history = None
    assert long_screen.source(settings) is None


@pytest.fixture
def lab(settings, tmp_path, research):
    setups = tmp_path / "setups.yaml"
    setups.write_text(yaml.safe_dump({"baseline": {**RULES, "timeframes": ["5m", "15m"]}, "variants": {}}), encoding="utf-8")
    settings.shadow.setups = str(setups)
    settings._root = tmp_path
    conn = connect(settings.resolve(settings.journal.path))
    migrate(conn)
    register_variants(conn, ex.active_variants(settings, conn))
    yield conn, settings
    conn.close()


def _proposal(name, path="exit.take_profit_r", value=2.0):
    return {"name": name, "change": {"path": path, "value": value}, "hypothesis": "test", "expected": "+0.02R",
            "confidence": 0.3}


def test_a_proposal_must_pass_the_history_and_then_the_long_history(lab, monkeypatch):
    conn, settings = lab
    good, _ = ex.propose(conn, settings, _proposal("tp_2"))
    lucky, _ = ex.propose(conn, settings, _proposal("tp_175", value=1.75))
    weak, _ = ex.propose(conn, settings, _proposal("tp_125", value=1.25))
    monkeypatch.setattr(screen, "history_compare", lambda s, c, changes: {
        "tp_2": {"passed": True, "why": "beat it"}, "tp_175": {"passed": True, "why": "beat it"},
        "tp_125": {"passed": False, "why": "half 1 worse"}})
    status = lambda i: conn.execute("SELECT status FROM experiments WHERE id = ?", (i,)).fetchone()[0]  # noqa: E731
    lines = screen.screen_pending(settings, conn, long_stage=False)  # as `experiment propose` does
    assert (status(good), status(lucky), status(weak)) == ("screening", "screening", "rejected")
    assert any("4-year screen follows" in line for line in lines)
    monkeypatch.setattr(long_screen, "compare", lambda s, c, changes: {
        "tp_2": {"passed": True, "why": "beat it over 4 years"}, "tp_175": {"passed": False, "why": "half 2: -0.020R"}})
    screen.screen_pending(settings, conn)  # the agent's background job
    assert (status(good), status(lucky)) == ("running", "rejected")
    saved = json.loads(conn.execute("SELECT screen_json FROM experiments WHERE id = ?", (lucky,)).fetchone()[0])
    assert saved["history_passed"] and saved["long"]["why"] == "half 2: -0.020R" and saved["why"].startswith("4 years:")


def test_with_the_long_screen_off_the_history_screen_decides_alone(lab, monkeypatch):
    conn, settings = lab
    settings.learning.screen_on_long_history = False
    exp, _ = ex.propose(conn, settings, _proposal("tp_2"))
    monkeypatch.setattr(screen, "history_compare", lambda s, c, changes: {"tp_2": {"passed": True, "why": "beat it"}})
    screen.screen_pending(settings, conn)
    assert conn.execute("SELECT status FROM experiments WHERE id = ?", (exp,)).fetchone()[0] == "running"
