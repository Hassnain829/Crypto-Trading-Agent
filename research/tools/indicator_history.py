"""Read the test indicators' signal flags from TradingView history (research, not part of the agent).

Uses chart 2 of the Market_check layout (qteGoFhV): for each coin and interval it loads up to 10,000 bars
(Essential's limit), waits until every study has recomputed over them, and stores the bars and every non-zero
alert/shape flag in data/research/indicators_history.db.

Run:  .venv\\Scripts\\python research\\tools\\indicator_history.py [XRP,SOL,ETH] [60,15]
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import time
from pathlib import Path

from tradeagent.tv.cdp import TradingViewCDP

LAYOUT = "qteGoFhV"
DB = Path(__file__).resolve().parents[2] / "data" / "research" / "indicators_history.db"
SYMBOLS = {"XRP": "BINANCE:XRPUSDT.P", "SOL": "BINANCE:SOLUSDT.P", "ETH": "BINANCE:ETHUSDT.P"}
UNREADABLE = ["Smart Money Concepts Pro [RFX]"]  # no data rows: drawings only

PREPARE_JS = """(async function (symbol, res, want, removeNames) {
  var api = window.TradingViewApi, ch = api.chart(1);
  var cw = api._chartWidgetCollection.getAll()[1], model = cw.model().model();
  ch.getAllStudies().forEach(function (s) { if (removeNames.indexOf(s.name) >= 0) ch.removeEntity(s.id); });
  if (ch.symbol() !== symbol) ch.setSymbol(symbol, {});
  if (ch.resolution() !== res) ch.setResolution(res, {});
  var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  await sleep(5000);
  var started = Date.now(), requests = 0;
  while (Date.now() - started < 600000) {
    var ms = cw.model().mainSeries();
    if (ms._status.value().seriesStatus === 3 && !ms.isLoading()) {
      var size = ms.bars().size();
      if (size < want && ms.requestMoreDataAvailable() && requests < 60) {
        ms.requestMoreData(want - size + 10); requests++;
        await sleep(1500); continue;
      }
      var lastTime = ms.bars().valueAt(ms.bars().lastIndex())[0];
      var ready = ch.getAllStudies().every(function (s) {
        var src = model.dataSourceForId(s.id);
        if (!src || src.isLoading() || src.isFailed()) return false;
        var d = src.data();
        return d.size() >= size && d.valueAt(d.lastIndex())[0] === lastTime;
      });
      if (ready) return {ok: true, bars: size, symbol: ch.symbol(), res: ch.resolution(),
                         first: ms.bars().valueAt(ms.bars().firstIndex())[0], requests: requests,
                         studies: ch.getAllStudies().map(function (s) { return s.name; })};
    }
    await sleep(1000);
  }
  return {ok: false, bars: cw.model().mainSeries().bars().size()};
})"""

READ_JS = """(function (fromIndex, count) {
  var api = window.TradingViewApi, ch = api.chart(1);
  var cw = api._chartWidgetCollection.getAll()[1], model = cw.model().model();
  var bars = cw.model().mainSeries().bars();
  var out = {bars: [], flags: [], last: bars.lastIndex()};
  // bars loaded later have negative indexes: start at firstIndex() on the first call
  var start = fromIndex === null ? bars.firstIndex() : Math.max(bars.firstIndex(), fromIndex);
  var end = Math.min(bars.lastIndex(), start + count - 1);
  for (var k = start; k <= end; k++) { var b = bars.valueAt(k); if (b) out.bars.push([b[0], b[1], b[2], b[3], b[4]]); }
  ch.getAllStudies().forEach(function (s) {
    var src = model.dataSourceForId(s.id), mi = src.metaInfo(), styles = mi.styles || {}, d = src.data();
    var wanted = [];
    (mi.plots || []).forEach(function (p, i) {
      if (p.type === 'alertcondition' || p.type === 'shapes')
        wanted.push([i, (styles[p.id] && styles[p.id].title) || p.id, p.type]);
    });
    for (var k = start; k <= end; k++) {
      var row = d.valueAt(k); if (!row) continue;
      wanted.forEach(function (w) {
        var v = row[w[0] + 1];
        if (v !== null && v !== 0 && !isNaN(v)) out.flags.push([row[0], s.name, w[0] + ':' + w[2] + ':' + w[1], v]);
      });
    }
  });
  out.next = end < bars.lastIndex() ? end + 1 : null;
  return out;
})"""


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS bars (symbol TEXT, tf TEXT, time INTEGER, open REAL, high REAL, low REAL,"
                 " close REAL, PRIMARY KEY (symbol, tf, time))")
    conn.execute("CREATE TABLE IF NOT EXISTS flags (symbol TEXT, tf TEXT, time INTEGER, study TEXT, plot TEXT, value REAL,"
                 " PRIMARY KEY (symbol, tf, time, study, plot))")
    return conn


async def extract(cdp: TradingViewCDP, conn: sqlite3.Connection, coin: str, res: str) -> str:
    page = next(p for p in await cdp.chart_pages() if p.layout_id == LAYOUT)
    t0 = time.monotonic()
    prep = await cdp.evaluate(page, f"({PREPARE_JS})('{SYMBOLS[coin]}', '{res}', 10000, {UNREADABLE!r})",
                              await_promise=True)
    if not prep.get("ok"):
        return f"{coin} {res}: not prepared ({prep})"
    tf = {"60": "1h", "15": "15m", "5": "5m"}[res]
    index, nbars, nflags, first_call = None, 0, 0, True
    while first_call or index is not None:
        first_call = False
        out = await cdp.evaluate(page, f"({READ_JS})({'null' if index is None else index}, 1500)")
        with conn:
            conn.executemany("INSERT OR REPLACE INTO bars VALUES (?, ?, ?, ?, ?, ?, ?)",
                             [(coin, tf, b[0] * 1000, b[1], b[2], b[3], b[4]) for b in out["bars"]])
            conn.executemany("INSERT OR REPLACE INTO flags VALUES (?, ?, ?, ?, ?, ?)",
                             [(coin, tf, r[0] * 1000, r[1], r[2], r[3]) for r in out["flags"]])
        nbars += len(out["bars"])
        nflags += len(out["flags"])
        index = out["next"]
    first = time.strftime("%Y-%m-%d", time.gmtime(prep["first"]))
    return f"{coin} {tf}: {nbars} bars from {first}, {nflags} flags, {time.monotonic() - t0:.0f} s"


async def main() -> None:
    coins = sys.argv[1].split(",") if len(sys.argv) > 1 else list(SYMBOLS)
    resolutions = sys.argv[2].split(",") if len(sys.argv) > 2 else ["60", "15"]
    conn = connect()
    cdp = TradingViewCDP("127.0.0.1", 9222, timeout=700)
    for res in resolutions:
        for coin in coins:
            print(await extract(cdp, conn, coin, res), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
