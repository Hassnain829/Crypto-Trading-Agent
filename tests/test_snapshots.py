import json

import pytest

from tradeagent.journal import connect, migrate
from tradeagent.tv.coverage import coverage, expected_bars
from tradeagent.tv.repaint import compare_values
from tradeagent.tv.snapshots import (
    Snapshot,
    build_snapshot,
    resolve_signal_version,
    settings_fingerprint,
    store_snapshot,
)
from tradeagent.tv.watchdog import pages_by_layout
from tradeagent.tv.cdp import ChartPage

SPEC = {"klinger": {"study": "Klinger Volume Oscillator", "fields": [{"name": "hist", "plot": "plot_0", "title": "Histogram", "kind": "value"}]}}
BAR = 1790935200  # 2026-10-02 10:00 UTC


def _raw(**overrides):
    raw = {
        "symbol": "BINANCE:XRPUSDT.P", "interval": "5", "series_status": 3, "is_loading": False,
        "bar_time": BAR, "ohlcv": [1.5, 1.6, 1.4, 1.55, 1000.0], "values": {"klinger": {"hist": 12.5}}, "problems": [],
    }
    raw.update(overrides)
    return raw


def _build(raw, read_at_ms=(BAR + 303) * 1000):
    return build_snapshot(raw, symbol="XRP", timeframe="5m", tradingview_symbol="BINANCE:XRPUSDT.P",
                          bar_time_s=BAR, signal_version=1, read_at_ms=read_at_ms, spec=SPEC)


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "journal.db")
    migrate(connection)
    yield connection
    connection.close()


def test_good_snapshot_and_latency():
    snap = _build(_raw())
    assert snap.ok, snap.problems
    assert snap.latency_ms == 3000  # read 3 s after the 10:05 close


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"symbol": "BINANCE:SOLUSDT.P"}, "chart shows BINANCE:SOLUSDT.P"),
        ({"interval": "15"}, "chart interval 15"),
        ({"series_status": 1}, "still loading"),
        ({"values": {}}, "missing klinger.hist"),
        ({"problems": ["candle 1 not loaded"]}, "candle 1 not loaded"),
    ],
)
def test_bad_snapshots_explain_the_problem(overrides, problem):
    snap = _build(_raw(**overrides))
    assert not snap.ok
    assert any(problem in p for p in snap.problems)


def test_store_replaces_failed_read_but_never_a_good_one(conn):
    store_snapshot(conn, _build(_raw(series_status=1)))
    store_snapshot(conn, _build(_raw()))
    assert [tuple(r) for r in conn.execute("SELECT problems_json FROM snapshots")] == [(None,)]
    store_snapshot(conn, _build(_raw(series_status=1, values={"klinger": {"hist": -1.0}})))
    row = conn.execute("SELECT problems_json, values_json FROM snapshots").fetchone()
    assert row[0] is None and json.loads(row[1]) == {"klinger": {"hist": 12.5}}


def test_signal_versions(conn):
    first = settings_fingerprint({"AGENT-XRP/5": {"Q-Trend": {"in_2": 32}}})
    changed = settings_fingerprint({"AGENT-XRP/5": {"Q-Trend": {"in_2": 28}}})
    assert resolve_signal_version(conn, 1, *first) == (1, False)
    assert resolve_signal_version(conn, 1, *first) == (1, False)
    assert resolve_signal_version(conn, 1, *changed) == (2, True)
    assert resolve_signal_version(conn, 1, *first) == (1, True)  # reverted to an older version


def test_coverage_counts_ok_failed_and_missing(conn):
    start, end = BAR * 1000, (BAR + 900) * 1000  # 15 minutes -> three 5m candles
    assert expected_bars(start, end, "5m") == [BAR * 1000, (BAR + 300) * 1000, (BAR + 600) * 1000]
    store_snapshot(conn, Snapshot("XRP", "5m", BAR * 1000, 1, (BAR + 303) * 1000))
    store_snapshot(conn, Snapshot("XRP", "5m", (BAR + 300) * 1000, 1, (BAR + 605) * 1000, problems=["x"]))
    [row] = coverage(conn, ["XRP"], ["5m"], start, end)
    assert (row["expected"], row["ok"], row["failed"], row["missing"]) == (3, 1, 1, 1)
    assert row["latency_max_s"] == 3.0


def test_compare_values_finds_changes_only():
    stored = {"qtrend": {"buy": 1, "trend_line": 1.5}, "zerolag": {"upper_band": None}}
    assert compare_values(stored, {"qtrend": {"buy": 1, "trend_line": 1.5 + 1e-15}, "zerolag": {"upper_band": None}}) == []
    assert compare_values(stored, {"qtrend": {"buy": 0, "trend_line": 1.5}, "zerolag": {"upper_band": 2.0}}) == [
        "qtrend.buy", "zerolag.upper_band"
    ]


def test_pages_by_layout_ignores_order_and_duplicates():
    pages = [
        ChartPage("1", "https://www.tradingview.com/chart/K7xX5RYP/", "ws://1"),
        ChartPage("2", "https://www.tradingview.com/chart/9yUw9zox/", "ws://2"),
        ChartPage("3", "https://www.tradingview.com/chart/K7xX5RYP/", "ws://3"),
    ]
    found = pages_by_layout(pages)
    assert {k: v.id for k, v in found.items()} == {"K7xX5RYP": "1", "9yUw9zox": "2"}
