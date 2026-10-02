"""Minimal Chrome DevTools Protocol client for TradingView Desktop.

TradingView Desktop must run with --remote-debugging-port
(see scripts/launch_tradingview_debug.ps1). The port listens on localhost only.
"""

from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass
from typing import Any

import aiohttp

_CHART_URL = re.compile(r"tradingview\.com/chart/([^/?#]+)")


class CDPError(RuntimeError):
    """TradingView is unreachable, or a JavaScript evaluation failed."""


@dataclass(frozen=True)
class ChartPage:
    id: str
    url: str
    ws_url: str

    @property
    def layout_id(self) -> str | None:
        match = _CHART_URL.search(self.url)
        return match.group(1) if match else None


def chart_pages(targets: list[dict[str, Any]]) -> list[ChartPage]:
    """Keep only the TradingView chart tabs from a /json/list response."""
    return [
        ChartPage(t["id"], t["url"], t["webSocketDebuggerUrl"])
        for t in targets
        if t.get("type") == "page" and _CHART_URL.search(t.get("url", "")) and t.get("webSocketDebuggerUrl")
    ]


class TradingViewCDP:
    def __init__(self, host: str = "127.0.0.1", port: int = 9222, timeout: float = 10.0) -> None:
        self.base_url = f"http://{host}:{port}"
        self._timeout = timeout
        self._ids = itertools.count(1)

    async def _get_json(self, path: str) -> Any:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._timeout)) as session:
                async with session.get(self.base_url + path) as resp:
                    resp.raise_for_status()
                    return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise CDPError(f"TradingView debug port not reachable at {self.base_url} ({exc})") from exc

    async def version(self) -> dict[str, Any]:
        return await self._get_json("/json/version")

    async def chart_pages(self) -> list[ChartPage]:
        return chart_pages(await self._get_json("/json/list"))

    async def evaluate(self, page: ChartPage, expression: str, *, await_promise: bool = False) -> Any:
        """Run a JavaScript expression in a chart tab and return its JSON-serialisable value."""
        msg_id = next(self._ids)
        request = {
            "id": msg_id,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True, "awaitPromise": await_promise},
        }
        ws_timeout = aiohttp.ClientWSTimeout(ws_receive=self._timeout, ws_close=self._timeout)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None)) as session:
                async with session.ws_connect(page.ws_url, max_msg_size=0, timeout=ws_timeout) as ws:
                    await ws.send_json(request)
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        reply = json.loads(msg.data)
                        if reply.get("id") == msg_id:
                            break
                    else:
                        raise CDPError("connection closed before TradingView answered")
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise CDPError(f"evaluation in TradingView failed ({exc})") from exc

        if "error" in reply:
            raise CDPError(f"CDP error: {reply['error']}")
        result = reply.get("result", {})
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            description = details.get("exception", {}).get("description") or details.get("text", "unknown")
            raise CDPError(f"JavaScript error: {description}")
        return result.get("result", {}).get("value")
