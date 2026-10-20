"""Put the Supertrend test studies on Market_check (the user asked for them to stay there afterwards) and print
their inputs and plots: Supertrend (ATR 12, factor 3), DEMA 200, WaveTrend [LazyBear], Squeeze Momentum [LazyBear].

    .venv\\Scripts\\python -u research\\tools\\st_setup.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tradeagent.tv.cdp import TradingViewCDP  # noqa: E402

LAYOUT = "qteGoFhV"
STUDIES = [("STD;Supertrend", {"in_0": 12, "in_1": 3}), ("STD;DEMA", {"in_0": 200}), ("PUB;1", {}), ("PUB;175", {})]

SETUP_JS = """(async function (studies) {
  var api = window.TradingViewApi, ch = api.chart(0), model = api._chartWidgetCollection.getAll()[0].model().model();
  var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  ch.getAllStudies().forEach(function (s) { ch.removeEntity(s.id); });
  await sleep(2000);
  var out = [];
  for (var n = 0; n < studies.length; n++) {
    var sid = studies[n][0], want = studies[n][1], rec = {asked: sid};
    try {
      var before = ch.getAllStudies().map(function (s) { return s.id; });
      var j = await (await fetch('https://pine-facade.tradingview.com/pine-facade/translate/' + encodeURIComponent(sid) + '/last', {credentials: 'include'})).json();
      if (!j.result) { rec.error = JSON.stringify(j).slice(0, 200); out.push(rec); continue; }
      var res = ch.insertStudyWithoutCheck(j.result.metaInfo); if (res && res.then) await res;
      var id = null;
      for (var w = 0; w < 30 && !id; w++) { await sleep(300); id = ch.getAllStudies().map(function (s) { return s.id; }).filter(function (x) { return before.indexOf(x) < 0; })[0]; }
      var src = model.dataSourceForId(id), mi = src.metaInfo(), childs = src.properties().childs().inputs.childs();
      Object.keys(want).forEach(function (k) { if (childs[k]) childs[k].setValue(want[k]); });
      rec.name = ch.getStudyById(id).name ? null : null;
      rec.study = mi.description; rec.shortName = mi.shortDescription;
      rec.inputs = (mi.inputs || []).filter(function (i) { return i.type !== 'color'; }).map(function (i) {
        return [i.id, i.name, i.defval, childs[i.id] ? childs[i.id].value() : null]; });
      rec.plots = (mi.plots || []).map(function (p, k) { return [k + 1, p.id, p.type, (mi.styles && mi.styles[p.id] && mi.styles[p.id].title) || p.target || '']; });
    } catch (e) { rec.error = String(e).slice(0, 200); }
    out.push(rec);
  }
  return out;
})"""


async def main() -> None:
    cdp = TradingViewCDP(timeout=300)
    page = next(p for p in await cdp.chart_pages() if p.layout_id == LAYOUT)
    print(json.dumps(await cdp.evaluate(page, f"({SETUP_JS})({json.dumps(STUDIES)})", await_promise=True), indent=1))


asyncio.run(main())
