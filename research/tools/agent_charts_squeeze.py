"""One-off (2026-10-20): on the AGENT-XRP, AGENT-SOL and AGENT-ETH layouts, replace VWAP with Squeeze Momentum
[LazyBear] (PUB;175) on both charts and save the layouts. Runs right after an agent cycle and then asks the agent to
restart, so it reads with the new catalog (config/indicators.yaml) from the next candle close on.

    .venv\\Scripts\\python -u research\\tools\\agent_charts_squeeze.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tradeagent.config import load_settings  # noqa: E402
from tradeagent.journal import connect  # noqa: E402
from tradeagent.supervisor import request_stop  # noqa: E402
from tradeagent.tv.cdp import TradingViewCDP  # noqa: E402

SWAP_JS = """(async function () {
  var api = window.TradingViewApi, sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  var out = [];
  for (var i = 0; i < api.chartsCount(); i++) {
    var ch = api.chart(i), names = ch.getAllStudies().map(function (s) { return s.name; });
    var vwap = ch.getAllStudies().filter(function (s) { return s.name === 'Volume-weighted average price'; })[0];
    if (vwap) ch.removeEntity(vwap.id);
    if (names.indexOf('Squeeze Momentum Indicator [LazyBear]') < 0) {
      var before = ch.getAllStudies().map(function (s) { return s.id; });
      var j = await (await fetch('https://pine-facade.tradingview.com/pine-facade/translate/PUB%3B175/last', {credentials: 'include'})).json();
      var res = ch.insertStudyWithoutCheck(j.result.metaInfo); if (res && res.then) await res;
      for (var w = 0; w < 30; w++) {
        await sleep(300);
        if (ch.getAllStudies().some(function (s) { return before.indexOf(s.id) < 0; })) break;
      }
    }
    out.push({chart: i, interval: ch.resolution(), studies: ch.getAllStudies().map(function (s) { return s.name; })});
  }
  await sleep(1500);
  try { api.getSaveChartService()._renameController._doSaveCurrentLayout(api.layoutName()); } catch (e) { out.push({save: String(e)}); }
  await sleep(2000);
  return out;
})()"""


async def main() -> None:
    settings = load_settings(ROOT)
    log = settings.resolve(settings.logging.file)
    begun = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    for _ in range(400):  # wait for the next finished cycle
        last = log.read_text(encoding="utf-8", errors="replace").splitlines()[-1]
        if "agent: shadow:" in last and last[:19] > begun:
            break
        time.sleep(1)
    print("cycle finished:", last[:70], flush=True)
    cdp = TradingViewCDP(timeout=120)
    pages = {p.layout_id: p for p in await cdp.chart_pages()}
    for coin in settings.exchange.symbols:
        page = pages.get(settings.layout_for(coin))
        print(coin, json.dumps(await cdp.evaluate(page, SWAP_JS, await_promise=True)), flush=True)
    conn = connect(settings.resolve(settings.journal.path))
    request_stop(conn)
    conn.close()
    print("agent stop requested at", time.strftime("%H:%M:%S"), "- the dashboard starts it again with the new catalog")


asyncio.run(main())
