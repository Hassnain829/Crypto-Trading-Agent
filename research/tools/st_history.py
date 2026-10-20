"""Read the Supertrend test studies' history from Market_check (set up by st_setup.py) into data/research/st_tests.db.
The studies stay on Market_check afterwards (the user's wish). Plot positions come from st_setup.py's listing:
Supertrend Up Trend / Down Trend / flips, DEMA, WaveTrend wt1 (plot_5) / wt2 (plot_6), Squeeze value (plot_0) and
its state colour (plot_3, a palette index).

    .venv\\Scripts\\python -u research\\tools\\st_history.py
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tradeagent.tv.cdp import TradingViewCDP  # noqa: E402

LAYOUT = "qteGoFhV"
DB = ROOT / "data" / "research" / "st_tests.db"
JOBS = [("XRP", "5"), ("XRP", "15"), ("SOL", "5"), ("SOL", "15"), ("ETH", "5"), ("ETH", "15"), ("DOGE", "15"), ("LTC", "15")]

LOAD_JS = """(async function (symbol, res, want) {
  var api = window.TradingViewApi, ch = api.chart(0), cw = api._chartWidgetCollection.getAll()[0];
  var model = cw.model().model(), sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  if (ch.symbol() !== symbol) ch.setSymbol(symbol, {});
  if (ch.resolution() !== res) ch.setResolution(res, {});
  await sleep(5000);
  var started = Date.now(), requests = 0;
  while (Date.now() - started < 600000) {
    var ms = cw.model().mainSeries();
    if (ms._status.value().seriesStatus === 3 && !ms.isLoading()) {
      var bars = ms.bars(), size = bars.size();
      if (size < want && ms.requestMoreDataAvailable() && requests < 80) { ms.requestMoreData(want - size + 10); requests++; await sleep(1500); continue; }
      var lastTime = bars.valueAt(bars.lastIndex())[0];
      var ready = ch.getAllStudies().every(function (s) {
        var src = model.dataSourceForId(s.id);
        if (!src || src.isLoading() || src.isFailed()) return false;
        var row = src.data().valueAt(bars.lastIndex());
        return !!row && row[0] === lastTime;  // DEMA 200 has fewer rows than bars (warm-up)
      });
      if (ready) return {ok: true, symbol: ch.symbol(), bars: size};
    }
    await sleep(1000);
  }
  return {ok: false};
})"""

# Every closed bar after a 300-bar warm-up: [time, o, h, l, c, stUp, stDown, stBuy, stSell, dema, wt1, wt2, sqz, sqzColor]
READ_JS = """(function (fromIndex, count) {
  var api = window.TradingViewApi, ch = api.chart(0), cw = api._chartWidgetCollection.getAll()[0], model = cw.model().model();
  var bars = cw.model().mainSeries().bars(), byDesc = {};
  ch.getAllStudies().forEach(function (s) { var src = model.dataSourceForId(s.id); byDesc[src.metaInfo().shortDescription] = src; });
  var st = byDesc['Supertrend'], de = byDesc['DEMA'], wt = byDesc['WT_LB'], sq = byDesc['SQZMOM_LB'];
  var pal = sq.metaInfo().palettes || {}, palettes = {};
  Object.keys(pal).forEach(function (k) { palettes[k] = pal[k]; });
  var start = fromIndex === null ? bars.firstIndex() + 300 : fromIndex, end = Math.min(bars.lastIndex() - 1, start + count - 1), out = [];
  var at = function (src, i, t) { var r = src.data().valueAt(i); return r && r[0] === t ? r : null; };
  for (var i = start; i <= end; i++) {
    var b = bars.valueAt(i); if (!b) continue;
    var a = at(st, i, b[0]), d = at(de, i, b[0]), w = at(wt, i, b[0]), q = at(sq, i, b[0]);
    if (!a || !d || !w || !q) continue;
    out.push([b[0], b[1], b[2], b[3], b[4], a[1], a[2], a[4], a[5], d[1], w[6], w[7], q[1], q[4]]);
  }
  return {rows: out, next: end + 1, last: bars.lastIndex() - 1, palettes: fromIndex === null ? palettes : null,
          sqzStyles: fromIndex === null ? sq.metaInfo().defaults : null};
})"""


async def main() -> None:
    cdp = TradingViewCDP(timeout=700)
    page = next(p for p in await cdp.chart_pages() if p.layout_id == LAYOUT)
    db = sqlite3.connect(DB)
    db.execute("CREATE TABLE IF NOT EXISTS bars (symbol TEXT, tf TEXT, time INTEGER, o REAL, h REAL, l REAL, c REAL, st_up REAL,"
               " st_down REAL, st_buy REAL, st_sell REAL, dema REAL, wt1 REAL, wt2 REAL, sqz REAL, sqz_color REAL,"
               " PRIMARY KEY (symbol, tf, time))")
    for coin, res in JOBS:
        tf = {"5": "5m", "15": "15m"}[res]
        if db.execute("SELECT count(*) FROM bars WHERE symbol = ? AND tf = ?", (coin, tf)).fetchone()[0] > 1000:
            print(f"{coin} {tf}: already stored")
            continue
        started = time.monotonic()
        loaded = await cdp.evaluate(page, f"({LOAD_JS})({json.dumps(f'BINANCE:{coin}USDT.P')}, {json.dumps(res)}, 10000)",
                                    await_promise=True)
        if not loaded.get("ok"):
            print(f"{coin} {tf}: not loaded {loaded}")
            continue
        index, stored = None, 0
        while True:
            part = await cdp.evaluate(page, f"({READ_JS})({json.dumps(index)}, 2000)")
            if index is None and part.get("palettes"):
                print("  squeeze palettes:", json.dumps(part["palettes"])[:400])
            db.executemany("INSERT OR REPLACE INTO bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           [(coin, tf, r[0] * 1000, *r[1:]) for r in part["rows"]])
            db.commit()
            stored += len(part["rows"])
            if part["next"] > part["last"]:
                break
            index = part["next"]
        print(f"{coin} {tf}: {loaded['bars']} bars, {stored} stored in {time.monotonic() - started:.0f} s", flush=True)
    db.close()


asyncio.run(main())
