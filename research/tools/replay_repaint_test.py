"""Repaint test with TradingView's bar replay (research, not part of the agent).

On chart 2 of the Market_check layout, replay starts N bars back and steps one bar at a time. After every step it
records the non-zero alert flags of the last 15 bars, so we know at which step each signal first appeared. A signal
that first appears several bars after its own bar was drawn back in time (repaint / offset). The replayed flags are
compared with the full-history extraction in data/research/indicators_history.db.

Run:  .venv\\Scripts\\python research\\tools\\replay_repaint_test.py XRP 60 400
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

START_JS = """(async function (symbol, res, startMs) {
  var api = window.TradingViewApi, sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  var r = await api.replayApi();
  if (r.isReplayStarted().value()) { r.stopReplay(); await sleep(3000); }
  api.setActiveChart(1);
  var ch = api.chart(1);
  if (ch.symbol() !== symbol) ch.setSymbol(symbol, {});
  if (ch.resolution() !== res) ch.setResolution(res, {});
  await sleep(5000);
  await r.selectDate(startMs);
  for (var i = 0; i < 60 && !r.isReplayStarted().value(); i++) await sleep(500);
  await sleep(3000);
  return r.isReplayStarted().value();
})"""

STEP_JS = """(async function (steps) {
  var api = window.TradingViewApi, sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  var r = await api.replayApi(), ch = api.chart(1);
  var cw = api._chartWidgetCollection.getAll()[1], model = cw.model().model();
  function lastBar() { var b = cw.model().mainSeries().bars(); var v = b.valueAt(b.lastIndex()); return v ? v[0] : null; }
  var out = [];
  for (var s = 0; s < steps; s++) {
    if (!r.isReplayStarted().value()) break;
    var before = lastBar();
    r.doStep();
    var bar = before;
    for (var w = 0; w < 30; w++) {
      await sleep(50);
      bar = lastBar();
      if (bar === before) continue;
      // study rows align with the candle index; some studies also hold rows further right (offset plots), so check
      // the row at the new candle's own index instead of the study's last row
      var idx = cw.model().mainSeries().bars().lastIndex();
      var ready = ch.getAllStudies().every(function (st) {
        var src = model.dataSourceForId(st.id); var d = src && src.data();
        if (!src || src.isLoading() || !d) return false;
        var row = d.valueAt(idx);
        return row && row[0] === bar;
      });
      if (ready) break;
    }
    ch.getAllStudies().forEach(function (st) {
      var src = model.dataSourceForId(st.id), mi = src.metaInfo(), styles = mi.styles || {}, d = src.data();
      for (var k = Math.max(d.firstIndex(), d.lastIndex() - 14); k <= d.lastIndex(); k++) {
        var row = d.valueAt(k); if (!row) continue;
        (mi.plots || []).forEach(function (p, i) {
          if (p.type !== 'alertcondition') return;
          var v = row[i + 1];
          if (v !== null && v !== 0 && !isNaN(v)) out.push([bar, row[0], st.name, (styles[p.id] && styles[p.id].title) || p.id]);
        });
      }
    });
  }
  return {rows: out, last: lastBar(), started: r.isReplayStarted().value()};
})"""

STOP_JS = """(async function () {
  var r = await window.TradingViewApi.replayApi();
  if (r.isReplayStarted().value()) r.stopReplay();
  await new Promise(function (res) { setTimeout(res, 3000); });
  return r.isReplayStarted().value();
})()"""


async def main() -> None:
    coin = sys.argv[1] if len(sys.argv) > 1 else "XRP"
    res = sys.argv[2] if len(sys.argv) > 2 else "60"
    steps = int(sys.argv[3]) if len(sys.argv) > 3 else 400
    tf = {"60": "1h", "15": "15m"}[res]
    step_ms = {"60": 3_600_000, "15": 900_000}[res]
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS replay (symbol TEXT, tf TEXT, step_bar INTEGER, bar_time INTEGER,"
                 " study TEXT, plot TEXT, PRIMARY KEY (symbol, tf, step_bar, bar_time, study, plot))")
    with conn:
        conn.execute("DELETE FROM replay WHERE symbol = ? AND tf = ?", (coin, tf))
    cdp = TradingViewCDP("127.0.0.1", 9222, timeout=600)
    page = next(p for p in await cdp.chart_pages() if p.layout_id == LAYOUT)
    start_ms = int(time.time() * 1000) - (steps + 60) * step_ms
    try:
        if not await cdp.evaluate(page, f"({START_JS})('{SYMBOLS[coin]}', '{res}', {start_ms})", await_promise=True):
            raise SystemExit("replay did not start")
        done = 0
        while done < steps:
            out = await cdp.evaluate(page, f"({STEP_JS})(25)", await_promise=True)
            with conn:
                conn.executemany("INSERT OR IGNORE INTO replay VALUES (?, ?, ?, ?, ?, ?)",
                                 [(coin, tf, r[0] * 1000, r[1] * 1000, r[2], r[3]) for r in out["rows"]])
            done += 25
            print(f"{coin} {tf}: {done} steps, at {time.strftime('%m-%d %H:%M', time.gmtime(out['last']))} UTC", flush=True)
            if not out["started"]:
                break
    finally:
        await cdp.evaluate(page, STOP_JS, await_promise=True)


if __name__ == "__main__":
    asyncio.run(main())

