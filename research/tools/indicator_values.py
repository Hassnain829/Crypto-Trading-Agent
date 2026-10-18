"""Put a set of indicators on chart 2 of the Market_check layout, load 10,000 bars and store every plot value
(research, not part of the agent). Built-in studies are created by name, community scripts from pine-facade.

Run:  .venv\\Scripts\\python research\\tools\\indicator_values.py builtin XRP,SOL,ETH 15
      .venv\\Scripts\\python research\\tools\\indicator_values.py utbot XRP,SOL,ETH 15
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path

from tradeagent.tv.cdp import TradingViewCDP

sys.path.insert(0, str(Path(__file__).resolve().parent))
from indicator_history import PREPARE_JS, SYMBOLS  # noqa: E402

LAYOUT = "qteGoFhV"
DB = Path(__file__).resolve().parents[2] / "data" / "research" / "indicators_history.db"
SETS = {
    # built-in study name -> {input id: value}
    "builtin": {"Average Directional Index": {}, "Supertrend": {}, "Relative Strength Index": {},
                "Bollinger Bands %B": {}, "Moving Average Exponential": {"in_0": 200}},
    "utbot": {"PUB;fvKf7ZbacOxo47bpXI9rDSN0npXIk48x": {}},
    "trend": {"STD;Average%1Directional%1Index": {}, "STD;Supertrend": {}, "STD;EMA": {"in_0": 200},
              "STD;Chandelier_Exit": {}, "PUB;fvKf7ZbacOxo47bpXI9rDSN0npXIk48x": {}},
    "fix": {"STD;Average%1Directional%1Index": {}, "STD;EMA": {"in_0": 200}},
}

SETUP_JS = """(async function (wanted) {
  var api = window.TradingViewApi, ch = api.chart(1), sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  var model = api._chartWidgetCollection.getAll()[1].model().model();
  ch.getAllStudies().forEach(function (s) { ch.removeEntity(s.id); });
  await sleep(2000);
  var log = [];
  for (var name in wanted) {
    try {
      var id;
      if (name.indexOf('PUB;') === 0 || name.indexOf('STD;') === 0) {
        var j = await (await fetch('https://pine-facade.tradingview.com/pine-facade/translate/' + encodeURIComponent(name) + '/last', {credentials: 'include'})).json();
        var before = ch.getAllStudies().map(function (s) { return s.id; });
        var res = ch.insertStudyWithoutCheck(j.result.metaInfo); if (res && res.then) res = await res;
        await sleep(3000);
        id = ch.getAllStudies().map(function (s) { return s.id; }).filter(function (x) { return before.indexOf(x) < 0; })[0];
      } else {
        id = await ch.createStudy(name, false, false);
      }
      var study = ch.getStudyById(id), info = study.getInputsInfo();
      var changes = [];
      for (var key in wanted[name]) { changes.push({id: key, value: wanted[name][key]}); }
      if (changes.length) { study.setInputValues(changes); await sleep(2000); }
      var inputs = {}; info.slice(0, 4).forEach(function (x) { inputs[x.id + ':' + x.name] = true; });
      log.push(name + ': ' + id + ' inputs ' + Object.keys(inputs).join(', ') + ' now ' + JSON.stringify(study.getInputValues().filter(function (x) { return x.id.indexOf('in_') === 0; }).slice(0, 3)));
    } catch (e) { log.push(name + ': ERROR ' + String(e).slice(0, 150)); }
  }
  await sleep(3000);
  return {log: log, studies: ch.getAllStudies().map(function (s) { return s.name; })};
})"""

READ_JS = """(function (fromIndex, count) {
  var api = window.TradingViewApi, ch = api.chart(1);
  var cw = api._chartWidgetCollection.getAll()[1], model = cw.model().model();
  var bars = cw.model().mainSeries().bars();
  var start = fromIndex === null ? bars.firstIndex() : Math.max(bars.firstIndex(), fromIndex);
  var end = Math.min(bars.lastIndex(), start + count - 1), out = [];
  ch.getAllStudies().forEach(function (s) {
    var src = model.dataSourceForId(s.id), mi = src.metaInfo(), styles = mi.styles || {}, d = src.data();
    var plots = (mi.plots || []).map(function (p, i) {
      return [i, (styles[p.id] && styles[p.id].title) || p.id, p.type]; }).filter(function (p) {
      return ['line', 'alertcondition', 'shapes', 'histogram', 'area', 'circles', 'cross'].indexOf(p[2]) >= 0 ||
             p[2].indexOf('line') >= 0; });
    for (var k = start; k <= end; k++) {
      var row = d.valueAt(k); if (!row) continue;
      plots.forEach(function (p) {
        var v = row[p[0] + 1];
        if (v !== null && v !== undefined && !isNaN(v)) out.push([row[0], s.name, p[0] + ':' + p[2] + ':' + p[1], v]);
      });
    }
  });
  return {rows: out, next: end < bars.lastIndex() ? end + 1 : null};
})"""


async def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "builtin"
    coins = sys.argv[2].split(",") if len(sys.argv) > 2 else list(SYMBOLS)
    res = sys.argv[3] if len(sys.argv) > 3 else "15"
    tf = {"60": "1h", "15": "15m"}[res]
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS ind_values (symbol TEXT, tf TEXT, time INTEGER, study TEXT, plot TEXT,"
                 " value REAL, PRIMARY KEY (symbol, tf, time, study, plot))")
    cdp = TradingViewCDP("127.0.0.1", 9222, timeout=700)
    page = next(p for p in await cdp.chart_pages() if p.layout_id == LAYOUT)
    print(await cdp.evaluate(page, f"({SETUP_JS})({json.dumps(SETS[which])})", await_promise=True), flush=True)
    for coin in coins:
        t0 = time.monotonic()
        prep = await cdp.evaluate(page, f"({PREPARE_JS})('{SYMBOLS[coin]}', '{res}', 10000, [])", await_promise=True)
        if not prep.get("ok"):
            print(f"{coin}: not prepared {prep}", flush=True)
            continue
        index, n, first = None, 0, True
        while first or index is not None:
            first = False
            out = await cdp.evaluate(page, f"({READ_JS})({'null' if index is None else index}, 1000)")
            with conn:
                conn.executemany("INSERT OR REPLACE INTO ind_values VALUES (?, ?, ?, ?, ?, ?)",
                                 [(coin, tf, r[0] * 1000, r[1], r[2], r[3]) for r in out["rows"]])
            n += len(out["rows"])
            index = out["next"]
        print(f"{coin} {tf}: {prep['bars']} bars, {n} values, {time.monotonic() - t0:.0f} s", flush=True)


if __name__ == "__main__":
    asyncio.run(main())



