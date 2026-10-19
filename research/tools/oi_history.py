"""Idea 2/3 data (research/notes/2026-10-19-liquidity-plan.md): 15m open interest history of the Binance perpetuals,
read from TradingView's OI symbols (BINANCE:XRPUSDT.P_OI) on the Market_check layout, up to 10,000 bars (Essential).
The layout's own symbol is restored at the end. Stored in data/research/oi_history.db (table oi: symbol, time, o, h, l, c).

    .venv\\Scripts\\python research\\tools\\oi_history.py
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tradeagent.tv.cdp import TradingViewCDP  # noqa: E402

LAYOUT = "qteGoFhV"
DB = ROOT / "data" / "research" / "oi_history.db"
COINS = {"XRP": "BINANCE:XRPUSDT.P_OI", "SOL": "BINANCE:SOLUSDT.P_OI", "ETH": "BINANCE:ETHUSDT.P_OI"}
WANT = 10_000

LOAD_JS = """(async function (symbol, res, want) {
  var api = window.TradingViewApi, ch = api.chart(0), cw = api._chartWidgetCollection.getAll()[0];
  var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  if (ch.symbol() !== symbol) ch.setSymbol(symbol, {});
  if (ch.resolution() !== res) ch.setResolution(res, {});
  await sleep(5000);
  var started = Date.now(), requests = 0;
  while (Date.now() - started < 300000) {
    var ms = cw.model().mainSeries();
    if (ms._status.value().seriesStatus === 3 && !ms.isLoading()) {
      var size = ms.bars().size();
      if (size < want && ms.requestMoreDataAvailable() && requests < 60) {
        ms.requestMoreData(want - size + 10); requests++; await sleep(1500); continue;
      }
      return {ok: true, symbol: ch.symbol(), bars: size, requests: requests};
    }
    await sleep(1000);
  }
  return {ok: false, bars: cw.model().mainSeries().bars().size()};
})"""

READ_JS = """(function (fromIndex, count) {
  var api = window.TradingViewApi, cw = api._chartWidgetCollection.getAll()[0], bars = cw.model().mainSeries().bars();
  var start = fromIndex === null ? bars.firstIndex() : Math.max(bars.firstIndex(), fromIndex);
  var end = Math.min(bars.lastIndex(), start + count - 1), out = [];
  for (var k = start; k <= end; k++) { var b = bars.valueAt(k); if (b) out.push([b[0], b[1], b[2], b[3], b[4]]); }
  return {rows: out, next: end + 1, last: bars.lastIndex()};
})"""


async def main() -> None:
    cdp = TradingViewCDP(timeout=400)
    page = next(p for p in await cdp.chart_pages() if p.layout_id == LAYOUT)
    original = await cdp.evaluate(page, "({symbol: window.TradingViewApi.chart(0).symbol(), res: window.TradingViewApi.chart(0).resolution()})")
    db = sqlite3.connect(DB)
    db.execute("CREATE TABLE IF NOT EXISTS oi (symbol TEXT, time INTEGER, o REAL, h REAL, l REAL, c REAL, PRIMARY KEY (symbol, time))")
    try:
        for coin, symbol in COINS.items():
            loaded = await cdp.evaluate(page, f"({LOAD_JS})({json.dumps(symbol)}, '15', {WANT})", await_promise=True)
            print(coin, json.dumps(loaded))
            index, rows = None, []
            while True:
                part = await cdp.evaluate(page, f"({READ_JS})({json.dumps(index)}, 2000)")
                rows += part["rows"]
                if part["next"] > part["last"]:
                    break
                index = part["next"]
            closed = rows[:-1]  # the newest bar is still forming
            db.executemany("INSERT OR REPLACE INTO oi VALUES (?, ?, ?, ?, ?, ?)", [(coin, *r) for r in closed])
            db.commit()
            print(f"  stored {len(closed)} closed 15m bars from {closed[0][0]} to {closed[-1][0]}")
    finally:
        back = await cdp.evaluate(page, f"({LOAD_JS})({json.dumps(original['symbol'])}, {json.dumps(original['res'])}, 300)",
                                  await_promise=True)
        print("Market_check restored:", back.get("symbol"), original["res"])
        db.close()


asyncio.run(main())
