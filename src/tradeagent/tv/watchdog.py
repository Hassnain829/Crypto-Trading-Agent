"""Keeps TradingView usable for the reader: debug port up, AGENT tabs open, no chart stuck loading."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time

from tradeagent.config import Settings
from tradeagent.tv import js
from tradeagent.tv.cdp import CDPError, ChartPage, TradingViewCDP

log = logging.getLogger("tradeagent.watchdog")

RESTORE_WAIT_S = 90  # after a start TradingView reopens its last tabs by itself, which takes up to about a minute


def pages_by_layout(pages: list[ChartPage]) -> dict[str, ChartPage]:
    """First open tab for every layout id. The order of /json/list changes, so never rely on it."""
    found: dict[str, ChartPage] = {}
    for page in pages:
        if page.layout_id and page.layout_id not in found:
            found[page.layout_id] = page
    return found


class Watchdog:
    def __init__(self, settings: Settings, cdp: TradingViewCDP) -> None:
        self.settings = settings
        self.cdp = cdp
        self.required = list(settings.tradingview.layouts.values())
        self._stuck_since: dict[str, float] = {}
        self._duplicates: set[str] = set()

    async def pages(self) -> dict[str, ChartPage]:
        return pages_by_layout(await self.cdp.chart_pages())

    async def _port_up(self, attempts: int = 3) -> bool:
        """The debug port answers. A single failed request is not enough to restart TradingView."""
        for attempt in range(attempts):
            try:
                await self.cdp.version()
                return True
            except CDPError:
                if attempt < attempts - 1:
                    await asyncio.sleep(2)
        return False

    async def _ready_page(self, timeout_s: float = 60) -> ChartPage | None:
        """A chart tab whose TradingView API has finished loading (needed to open other layouts)."""
        probe = "typeof window.TradingViewApi !== 'undefined' && typeof window.TradingViewApi.loadLayoutFromServerByLayoutId === 'function'"
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for page in await self.cdp.chart_pages():
                try:
                    if await self.cdp.evaluate(page, probe):
                        return page
                except CDPError:
                    pass
            await asyncio.sleep(2)
        return None

    async def _wait_for_restored_tabs(self, timeout_s: float, poll_s: float = 2) -> None:
        """Wait until TradingView has reopened the AGENT layouts itself, so none is opened a second time."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                pages = await self.pages()
                if all(layout_id in pages for layout_id in self.required):
                    return
            except CDPError:
                pass
            await asyncio.sleep(poll_s)

    async def _report_duplicates(self) -> None:
        """Warn once when an AGENT layout is open in more than one tab (more memory; the copies save over each other)."""
        layouts = [page.layout_id for page in await self.cdp.chart_pages()]
        duplicates = {layout_id for layout_id in self.required if layouts.count(layout_id) > 1}
        for layout_id in sorted(duplicates - self._duplicates):
            log.warning("layout %s is open in %d tabs; close the extra tabs in TradingView",
                        layout_id, layouts.count(layout_id))
        self._duplicates = duplicates

    async def _apply_timezone(self, pages: dict[str, ChartPage]) -> None:
        """Every AGENT chart shows the time zone of the setting tradingview.timezone ('system' = this computer's).
        Only the time axis changes; a chart already in that zone is left alone."""
        wanted = self.settings.tradingview.timezone
        for layout_id in self.required:
            page = pages.get(layout_id)
            if page is None:
                continue
            try:
                result = await self.cdp.evaluate(page, js.set_timezone(wanted))
            except CDPError:
                continue  # tab still loading; tried again next cycle
            if isinstance(result, dict) and result.get("changed"):
                log.info("layout %s: %d chart(s) now show times in %s", layout_id, result["changed"], result["target"])

    async def ensure(self) -> list[str]:
        """Repair what is broken. Returns the actions taken (empty when everything was fine). Never raises
        for a missing tab: the reader then records that problem and the next cycle tries again."""
        actions: list[str] = []
        if not await self._port_up():
            log.warning("TradingView debug port not reachable; starting TradingView")
            result = await asyncio.to_thread(self._launch)
            actions.append(f"started TradingView ({result})")
            await self._wait_for_restored_tabs(RESTORE_WAIT_S)

        pages = await self.pages()
        missing = [layout_id for layout_id in self.required if layout_id not in pages]
        if missing:
            opener = await self._ready_page()
            if opener is None:
                actions.append("could not open the missing AGENT layouts: TradingView is not ready")
            else:
                for layout_id in missing:
                    try:
                        await self.cdp.evaluate(opener, js.open_layout_tab(layout_id), await_promise=True)
                        actions.append(f"opened layout {layout_id}")
                    except CDPError as exc:
                        actions.append(f"could not open layout {layout_id}: {exc}")
                    await asyncio.sleep(3)
                await asyncio.sleep(5)
                pages = await self.pages()
        await self._report_duplicates()
        await self._apply_timezone(pages)

        for layout_id in self.required:
            page = pages.get(layout_id)
            if page is None:
                continue
            try:
                state = await self.cdp.evaluate(page, js.tab_state())
            except CDPError:
                continue  # tab still loading; checked again next cycle
            stuck = any(c["series_status"] != 3 or c["is_loading"] for c in state["charts"])
            if not stuck:
                self._stuck_since.pop(layout_id, None)
                continue
            since = self._stuck_since.setdefault(layout_id, time.monotonic())
            if time.monotonic() - since >= self.settings.tradingview.stuck_reload_after_s:
                await self.cdp.evaluate(page, js.reload_tab())
                self._stuck_since.pop(layout_id, None)
                actions.append(f"reloaded stuck layout {layout_id}")
                await asyncio.sleep(10)
        for action in actions:
            log.warning("watchdog: %s", action)
        return actions

    def _launch(self) -> str:
        tv = self.settings.tradingview
        script = self.settings.resolve(tv.launcher)
        proc = subprocess.run(
            [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                "-Port", str(tv.cdp_port), "-AppId", tv.app_id,
            ],
            capture_output=True, text=True, timeout=180,
        )
        output = (proc.stdout or proc.stderr).strip()
        return output.splitlines()[-1] if output else f"exit code {proc.returncode}"
