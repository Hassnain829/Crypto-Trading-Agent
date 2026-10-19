"""Probe: can TradingView's Market_check layout show a perpetual's open interest as a symbol (e.g. BINANCE:XRPUSDT.P_OI)?
Prints the layout's current state first (to restore it), tries the OI symbol on 15m, then switches back.

    .venv\\Scripts\\python research\\tools\\oi_probe.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from tradeagent.tv.cdp import TradingViewCDP  # noqa: E402

LAYOUT = "qteGoFhV"

STATE_JS = """(function () {
  var api = window.TradingViewApi;
  return api._chartWidgetCollection.getAll().slice(0, api.chartsCount()).map(function (cw, i) {
    var ch = api.chart(i);
    return {index: i, symbol: ch.symbol(), resolution: ch.resolution(), bars: cw.model().mainSeries().bars().size(),
            studies: ch.getAllStudies().map(function (s) { return s.name; })};
  });
})()"""

TRY_JS = """(async function (symbol) {
  var api = window.TradingViewApi, ch = api.chart(0), cw = api._chartWidgetCollection.getAll()[0];
  var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  ch.setSymbol(symbol, {});
  await sleep(6000);
  var ms = cw.model().mainSeries(), bars = ms.bars();
  var last = bars.size() ? bars.valueAt(bars.lastIndex()) : null, first = bars.size() ? bars.valueAt(bars.firstIndex()) : null;
  return {asked: symbol, shown: ch.symbol(), status: ms._status.value().seriesStatus, bars: bars.size(),
          more: ms.requestMoreDataAvailable(), first: first, last: last};
})"""


async def main() -> None:
    cdp = TradingViewCDP(timeout=60)
    page = next(p for p in await cdp.chart_pages() if p.layout_id == LAYOUT)
    before = await cdp.evaluate(page, STATE_JS)
    print("before:", json.dumps(before))
    original = before[0]["symbol"]
    for symbol in ("BINANCE:XRPUSDT.P_OI",):
        print("try:", json.dumps(await cdp.evaluate(page, f"({TRY_JS})({json.dumps(symbol)})", await_promise=True)))
    restore = await cdp.evaluate(page, f"({TRY_JS})({json.dumps(original)})", await_promise=True)
    print("restored:", restore["shown"], restore["bars"], "bars")


asyncio.run(main())
