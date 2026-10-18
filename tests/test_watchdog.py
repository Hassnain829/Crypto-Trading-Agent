import asyncio
import logging

import pytest

from tradeagent.tv import js
from tradeagent.tv import watchdog as watchdog_module
from tradeagent.tv.cdp import ChartPage
from tradeagent.tv.watchdog import Watchdog

READY = {"charts": [{"series_status": 3, "is_loading": False}]}


def _page(n: int, layout_id: str) -> ChartPage:
    return ChartPage(str(n), f"https://www.tradingview.com/chart/{layout_id}/", f"ws://{n}")


class FakeCDP:
    """Answers /json/list from a script of tab lists (the last one repeats) and records evaluations."""

    def __init__(self, lists: list[list[ChartPage]]) -> None:
        self.lists = lists
        self.evaluated: list[str] = []

    async def version(self) -> dict:
        return {"Browser": "fake"}

    async def chart_pages(self) -> list[ChartPage]:
        return self.lists.pop(0) if len(self.lists) > 1 else self.lists[0]

    async def evaluate(self, page: ChartPage, expression: str, *, await_promise: bool = False):
        self.evaluated.append(expression)
        return True if expression.startswith("typeof") else READY


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    async def instant(_seconds):
        return None
    monkeypatch.setattr(watchdog_module.asyncio, "sleep", instant)
    monkeypatch.setattr(watchdog_module, "RESTORE_WAIT_S", 0.05)


def _restart(settings, lists):
    cdp = FakeCDP(lists)
    dog = Watchdog(settings, cdp)

    async def port_down() -> bool:
        return False
    dog._port_up = port_down
    dog._launch = lambda: "started"
    return dog, cdp


def test_restart_waits_for_restored_tabs_instead_of_opening_them_again(settings):
    layouts = list(settings.tradingview.layouts.values())
    restored = [_page(i, layout_id) for i, layout_id in enumerate(layouts)]
    dog, cdp = _restart(settings, [[], [], restored])  # TradingView needs a moment to reopen its tabs
    actions = asyncio.run(dog.ensure())
    assert actions == ["started TradingView (started)"]
    assert not [e for e in cdp.evaluated if e in {js.open_layout_tab(layout_id) for layout_id in layouts}]


def test_restart_opens_a_layout_that_was_not_restored(settings):
    layouts = list(settings.tradingview.layouts.values())
    restored = [_page(i, layout_id) for i, layout_id in enumerate(layouts[:-1])]
    dog, cdp = _restart(settings, [restored])
    actions = asyncio.run(dog.ensure())
    assert f"opened layout {layouts[-1]}" in actions
    assert js.open_layout_tab(layouts[-1]) in cdp.evaluated
    assert js.open_layout_tab(layouts[0]) not in cdp.evaluated


def test_duplicate_tabs_are_reported_once(settings, caplog):
    layouts = list(settings.tradingview.layouts.values())
    pages = [_page(i, layout_id) for i, layout_id in enumerate(layouts)] + [_page(99, layouts[0])]
    dog = Watchdog(settings, FakeCDP([pages]))
    with caplog.at_level(logging.WARNING, logger="tradeagent.watchdog"):
        asyncio.run(dog.ensure())
        asyncio.run(dog.ensure())
    warnings = [r.getMessage() for r in caplog.records if "open in" in r.getMessage()]
    assert warnings == [f"layout {layouts[0]} is open in 2 tabs; close the extra tabs in TradingView"]


def test_every_agent_layout_gets_the_time_zone_setting(settings):
    layouts = list(settings.tradingview.layouts.values())
    settings.tradingview.timezone = "Asia/Karachi"
    cdp = FakeCDP([[_page(i, layout_id) for i, layout_id in enumerate(layouts)] + [_page(50, "qteGoFhV")]])
    asyncio.run(Watchdog(settings, cdp).ensure())
    assert cdp.evaluated.count(js.set_timezone("Asia/Karachi")) == len(layouts)  # never the user's own layout


# ---- memory restart ---------------------------------------------------------------------------

def _heavy(settings, monkeypatch, mb, port_answers):
    """A watchdog whose TradingView uses `mb`; the debug port answers `port_answers` more times after the close."""
    dog = Watchdog(settings, FakeCDP([[]]))
    calls = []
    monkeypatch.setattr(watchdog_module.resources, "tradingview_mb", lambda: mb)
    monkeypatch.setattr(watchdog_module, "close_tradingview", lambda force=False: calls.append("kill" if force else "close"))
    answers = {"left": port_answers}

    async def port_up(attempts: int = 3) -> bool:
        answers["left"] -= 1
        return answers["left"] >= 0
    dog._port_up = port_up
    dog._launch = lambda: calls.append("launch") or "started"

    async def restored(_timeout):
        calls.append("tabs")
    dog._wait_for_restored_tabs = restored
    return dog, calls


def test_a_heavy_tradingview_is_closed_then_started_again(settings, monkeypatch):
    dog, calls = _heavy(settings, monkeypatch, mb=5600, port_answers=3)
    result = asyncio.run(dog.restart_if_heavy(seconds_left=240))
    assert result == "TradingView used 5600 MB; restarted it (started)"
    assert calls == ["close", "launch", "tabs"]  # launched only after the old debug port went away
    assert asyncio.run(dog.restart_if_heavy(seconds_left=240)) is None  # at most once per restart_min_gap_hours


def test_a_process_that_keeps_the_port_after_the_close_is_ended(settings, monkeypatch):
    monkeypatch.setattr(watchdog_module, "CLOSE_WAIT_S", 0.01)
    dog, calls = _heavy(settings, monkeypatch, mb=5600, port_answers=10_000)
    asyncio.run(dog.restart_if_heavy(seconds_left=240))
    assert calls[:2] == ["close", "kill"] and calls[-2:] == ["launch", "tabs"]


def test_no_restart_when_light_too_close_to_a_read_or_switched_off(settings, monkeypatch):
    dog, calls = _heavy(settings, monkeypatch, mb=2100, port_answers=0)
    assert asyncio.run(dog.restart_if_heavy(seconds_left=240)) is None
    dog, calls = _heavy(settings, monkeypatch, mb=5600, port_answers=0)
    assert asyncio.run(dog.restart_if_heavy(seconds_left=60)) is None  # the next read is too close
    settings.tradingview.restart_above_mb = None
    assert asyncio.run(dog.restart_if_heavy(seconds_left=240)) is None
    assert calls == []
