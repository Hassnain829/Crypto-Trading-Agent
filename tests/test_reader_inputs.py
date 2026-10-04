import asyncio

import pytest

from tradeagent.journal import connect, migrate
from tradeagent.tv import js
from tradeagent.tv import reader as reader_module
from tradeagent.tv.catalog import load_catalog
from tradeagent.tv.cdp import CDPError, ChartPage
from tradeagent.tv.reader import SignalReader


class FakeClock:
    offset_ms = 0

    def measure(self) -> int:
        return 0


class InputsCDP:
    """Every AGENT tab is open; read_inputs answers from `charts(layout_id, call)`."""

    def __init__(self, settings, charts) -> None:
        self.pages = [ChartPage(str(i), f"https://www.tradingview.com/chart/{layout_id}/", f"ws://{i}")
                      for i, layout_id in enumerate(settings.tradingview.layouts.values())]
        self.charts = charts
        self.calls: dict[str, int] = {}

    async def version(self) -> dict:
        return {}

    async def chart_pages(self) -> list[ChartPage]:
        return self.pages

    async def evaluate(self, page: ChartPage, expression: str, *, await_promise: bool = False):
        if "studyNames" not in expression:
            return {"charts": []}
        n = self.calls[page.layout_id] = self.calls.get(page.layout_id, 0) + 1
        return self.charts(page.layout_id, n)


@pytest.fixture(autouse=True)
def instant_sleep(monkeypatch):
    async def instant(_seconds):
        return None
    monkeypatch.setattr(reader_module.asyncio, "sleep", instant)


def _full(settings, catalog):
    """What every chart shows when its indicators have loaded (the template's studies, with inputs)."""
    def charts(layout_id: str) -> list[dict]:
        overview = layout_id == settings.htf_layout
        result = []
        for tf in (settings.timeframes.overview if overview else settings.timeframes.trade):
            template = "trend" if overview else "scalp"
            studies = {ind["study"]: {"in_0": 1} for ind in catalog.js_spec(template).values()}
            result.append({"interval": {"5m": "5", "15m": "15", "1h": "60", "4h": "240"}[tf], "studies": studies})
        return result
    return charts


def _reader(settings, cdp, catalog):
    conn = connect(settings.resolve(settings.journal.path))
    migrate(conn)
    return SignalReader(settings, catalog, conn, cdp=cdp, clock=FakeClock()), conn


def test_a_tab_still_loading_its_indicators_does_not_start_a_new_signal_version(settings):
    catalog = load_catalog(settings.resolve(settings.tradingview.catalog))
    full = _full(settings, catalog)
    sol = settings.layout_for("SOL")
    reader, conn = _reader(settings, InputsCDP(settings, lambda layout_id, n: full(layout_id)), catalog)
    assert asyncio.run(reader.check_signal_version(wait_s=5)) == 1

    def loading_first(layout_id: str, call: int) -> list[dict]:
        charts = full(layout_id)
        if layout_id == sol and call == 1:  # right after a TradingView restart: charts there, indicators not yet
            return [{"interval": c["interval"], "studies": {}} for c in charts]
        return charts
    reader.cdp = reader.watchdog.cdp = InputsCDP(settings, loading_first)
    assert asyncio.run(reader.check_signal_version(wait_s=5)) == 1
    assert [r[0] for r in conn.execute("SELECT signal_version FROM indicator_settings")] == [1]


def test_indicators_that_never_load_stop_the_start_instead_of_changing_the_version(settings):
    catalog = load_catalog(settings.resolve(settings.tradingview.catalog))
    full = _full(settings, catalog)
    sol = settings.layout_for("SOL")
    never = InputsCDP(settings, lambda layout_id, n: [{"interval": c["interval"], "studies": {}} for c in full(layout_id)]
                      if layout_id == sol else full(layout_id))
    reader, conn = _reader(settings, never, catalog)
    with pytest.raises(CDPError, match="AGENT-SOL 5: .*not loaded"):
        asyncio.run(reader.check_signal_version(wait_s=0.01))
    assert conn.execute("SELECT count(*) FROM indicator_settings").fetchone()[0] == 0


def test_read_inputs_is_what_the_fake_answers():
    assert "studyNames" in js.read_inputs(["Q-Trend"])


def test_a_candle_close_noticed_long_after_sleep_is_skipped_not_read(settings, caplog):
    import logging

    catalog = load_catalog(settings.resolve(settings.tradingview.catalog))
    stop = asyncio.Event()

    class JumpingClock:
        """The first look at the time is before a candle close; every later look is an hour later."""
        offset_ms = 0

        def __init__(self) -> None:
            self.calls = 0

        def now_s(self) -> float:
            self.calls += 1
            return 1_791_000_000 if self.calls == 1 else 1_791_000_000 + 3600

        def measure(self) -> int:  # called after the wake-up is noticed: end the test there
            stop.set()
            return 0

    clock = JumpingClock()
    reader, conn = _reader(settings, InputsCDP(settings, lambda layout_id, n: []), catalog)
    reader.clock = clock
    reads = []

    async def no_start():
        return []

    async def no_hourly(_hourly):
        return None

    async def record_read(timeframes, boundary_s=None):
        reads.append(boundary_s)
        return []
    reader.start, reader._run_hourly, reader.read = no_start, no_hourly, record_read
    with caplog.at_level(logging.WARNING, logger="tradeagent.reader"):
        asyncio.run(asyncio.wait_for(reader.run(stop=stop), timeout=5))
    assert reads == []
    assert any("the computer was asleep or busy" in r.getMessage() for r in caplog.records)
    assert conn.execute("SELECT count(*) FROM events WHERE message LIKE '%asleep%'").fetchone()[0] == 1


def test_connection_problems_are_one_line():
    import ccxt

    from tradeagent.tv.reader import _is_connection_problem, _short

    exc = ccxt.RequestTimeout("binanceusdm GET https://fapi.binance.com/fapi/v1/klines\n  Read timed out")
    assert _is_connection_problem(exc) and not _is_connection_problem(ValueError("bug"))
    assert _short(exc) == "RequestTimeout: binanceusdm GET https://fapi.binance.com/fapi/v1/klines Read timed out"
