"""Read-only: the script ids and input values of every study on the AGENT-XRP charts (5m and 15m), so a research
layout can carry exactly the same indicators. Prints JSON.

    .venv\\Scripts\\python research\\tools\\agent_study_inputs.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tradeagent.config import load_settings  # noqa: E402
from tradeagent.tv.cdp import TradingViewCDP  # noqa: E402

READ_JS = """(function () {
  var api = window.TradingViewApi, out = [];
  api._chartWidgetCollection.getAll().slice(0, api.chartsCount()).forEach(function (cw, i) {
    var ch = api.chart(i), model = cw.model().model();
    ch.getAllStudies().forEach(function (s) {
      var src = model.dataSourceForId(s.id), mi = src.metaInfo(), types = {};
      (mi.inputs || []).forEach(function (inp) { types[inp.id] = inp.type; });
      var childs = src.properties().childs().inputs.childs(), vals = {};
      Object.keys(childs).forEach(function (k) {
        if (types[k] === 'color') return;
        try { vals[k] = childs[k].value(); } catch (e) {}
      });
      out.push({chart: i, interval: cw.model().mainSeries().interval(), name: s.name, id: mi.id,
                scriptIdPart: mi.scriptIdPart || null, pine: mi.pine || null, inputs: vals});
    });
  });
  return out;
})()"""


async def main() -> None:
    settings = load_settings(ROOT)
    cdp = TradingViewCDP(timeout=60)
    page = next(p for p in await cdp.chart_pages() if p.layout_id == settings.layout_for("XRP"))
    print(json.dumps(await cdp.evaluate(page, READ_JS), indent=1))


asyncio.run(main())
