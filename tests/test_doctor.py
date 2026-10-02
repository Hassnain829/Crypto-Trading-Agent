import socket

import pytest

from tradeagent import doctor
from tradeagent.doctor import CheckResult, Status
from tradeagent.journal import connect
from tradeagent.tv.cdp import chart_pages


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_exit_code_fails_only_on_fail():
    assert doctor.exit_code([CheckResult("a", Status.OK, ""), CheckResult("b", Status.WARN, "")]) == 0
    assert doctor.exit_code([CheckResult("a", Status.OK, ""), CheckResult("b", Status.FAIL, "")]) == 1


def test_render_shows_status_detail_and_hint():
    text = doctor.render([CheckResult("TradingView", Status.FAIL, "port closed", hint="start it")])
    assert "[FAIL]" in text
    assert "port closed" in text
    assert "-> start it" in text
    assert "1 check(s) failed" in text


def test_journal_check_creates_database_and_leaves_no_rows(settings):
    result = doctor.check_journal(settings)
    assert result.status is Status.OK, result.detail
    conn = connect(settings.resolve(settings.journal.path))
    try:
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    finally:
        conn.close()


def test_catalog_check(settings, tmp_path):
    assert doctor.check_catalog(settings).status is Status.OK
    settings.tradingview.catalog = str(tmp_path / "missing.yaml")
    assert doctor.check_catalog(settings).status is Status.FAIL


def test_tradingview_unreachable_points_to_the_launcher(settings):
    settings.tradingview.cdp_port = _free_port()
    result = doctor.check_tradingview(settings)
    assert result.status is Status.FAIL
    assert "launch_tradingview_debug.ps1" in result.hint


def test_chart_pages_keeps_only_chart_tabs():
    targets = [
        {"type": "page", "id": "1", "url": "https://www.tradingview.com/chart/K7xX5RYP/", "webSocketDebuggerUrl": "ws://x/1"},
        {"type": "page", "id": "2", "url": "file:///C:/TradingView/app/window/index.html", "webSocketDebuggerUrl": "ws://x/2"},
        {"type": "service_worker", "id": "3", "url": "https://www.tradingview.com/chart/abc/", "webSocketDebuggerUrl": "ws://x/3"},
    ]
    assert [page.layout_id for page in chart_pages(targets)] == ["K7xX5RYP"]


@pytest.mark.network
def test_binance_public_api_answers(settings):
    result = doctor.check_binance(settings)
    assert result.status is not Status.FAIL, result.detail
