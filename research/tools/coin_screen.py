"""Coin screen (research/notes/2026-10-19-coin-screen.md): replay the baseline strategy on other coins from
TradingView history read on the Market_check layout. Nothing touches the live journal or the AGENT layouts.

    .venv\\Scripts\\python research\\tools\\coin_screen.py tv ZEC,NEAR     # snapshots from TradingView (resumable)
    .venv\\Scripts\\python research\\tools\\coin_screen.py candles ZEC,NEAR  # Binance candles and funding
    .venv\\Scripts\\python research\\tools\\coin_screen.py replay          # baseline trades with the agent's engine
    .venv\\Scripts\\python research\\tools\\coin_screen.py report          # results and the decision rule
    .venv\\Scripts\\python research\\tools\\coin_screen.py restore         # put Market_check back as it was
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import statistics as st
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tradeagent.config import SymbolConfig, load_settings  # noqa: E402
from tradeagent.journal import connect, migrate  # noqa: E402
from tradeagent.tv import js  # noqa: E402
from tradeagent.tv.catalog import load_catalog  # noqa: E402
from tradeagent.tv.cdp import TradingViewCDP  # noqa: E402
from tradeagent.tv.snapshots import Snapshot, store_snapshots  # noqa: E402

LAYOUT = "qteGoFhV"
DB = ROOT / "data" / "research" / "coin_screen.db"
ORIGINAL = ROOT / "data" / "research" / "market_check_original.json"
AGENT_STUDIES = Path(__file__).resolve().parent / "agent_studies.json"
WANT_BARS = 10_000
WARMUP = 300
# Both timeframes are read with the scalp template: the baseline needs Q-Trend and Klinger only, and the closed-source
# Trendline study fails on 10,000 bars on Market_check (the quality tier is not part of this screen).
TEMPLATES = {"5": ("5m", "scalp"), "15": ("15m", "scalp")}
SKIP_STUDIES = ("Dynamic Trendline Breakout [RFX]",)
settings = load_settings(ROOT)
catalog = load_catalog(settings.resolve(settings.tradingview.catalog))

STATE_JS = """(function () {
  var api = window.TradingViewApi, ch = api.chart(0), model = api._chartWidgetCollection.getAll()[0].model().model();
  return {symbol: ch.symbol(), resolution: ch.resolution(), studies: ch.getAllStudies().map(function (s) {
    var src = model.dataSourceForId(s.id), mi = src.metaInfo(), types = {}, vals = {};
    (mi.inputs || []).forEach(function (inp) { types[inp.id] = inp.type; });
    var childs = src.properties().childs().inputs.childs();
    Object.keys(childs).forEach(function (k) { if (types[k] !== 'color') { try { vals[k] = childs[k].value(); } catch (e) {} } });
    return {name: s.name, scriptIdPart: mi.scriptIdPart || null, version: (mi.pine || {}).version || null,
            builtin: mi.id, inputs: vals};
  })};
})()"""

# Replace every study on chart 0 with `studies` (scriptIdPart, version, inputs); built-ins by name.
SET_STUDIES_JS = """(async function (studies) {
  var api = window.TradingViewApi, ch = api.chart(0), model = api._chartWidgetCollection.getAll()[0].model().model();
  var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  ch.getAllStudies().forEach(function (s) { ch.removeEntity(s.id); });
  await sleep(2000);
  var log = [];
  for (var n = 0; n < studies.length; n++) {
    var want = studies[n], id = null;
    try {
      var before = ch.getAllStudies().map(function (s) { return s.id; });
      if (want.scriptIdPart) {
        var url = 'https://pine-facade.tradingview.com/pine-facade/translate/' + encodeURIComponent(want.scriptIdPart) + '/' + (want.version || 'last');
        var j = await (await fetch(url, {credentials: 'include'})).json();
        var res = ch.insertStudyWithoutCheck(j.result.metaInfo); if (res && res.then) await res;
      } else {
        await ch.createStudy(want.name, false, false);
      }
      for (var w = 0; w < 30 && !id; w++) {
        await sleep(300);
        id = ch.getAllStudies().map(function (s) { return s.id; }).filter(function (x) { return before.indexOf(x) < 0; })[0];
      }
      var childs = model.dataSourceForId(id).properties().childs().inputs.childs(), set = 0;
      Object.keys(want.inputs || {}).forEach(function (k) {
        if (childs[k] && childs[k].value() !== want.inputs[k]) { childs[k].setValue(want.inputs[k]); set++; }
      });
      log.push(want.name + ': ok (' + set + ' inputs set)');
    } catch (e) { log.push(want.name + ': ERROR ' + String(e).slice(0, 160)); }
  }
  await sleep(2000);
  return log;
})"""

LOAD_JS = """(async function (symbol, res, want) {
  var api = window.TradingViewApi, ch = api.chart(0), cw = api._chartWidgetCollection.getAll()[0];
  var model = cw.model().model(), sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  if (ch.symbol() !== symbol) ch.setSymbol(symbol, {});
  if (ch.resolution() !== res) ch.setResolution(res, {});
  await sleep(5000);
  var started = Date.now(), requests = 0;
  while (Date.now() - started < 900000) {
    var ms = cw.model().mainSeries();
    if (ms._status.value().seriesStatus === 3 && !ms.isLoading()) {
      var bars = ms.bars(), size = bars.size();
      if (size < want && ms.requestMoreDataAvailable() && requests < 80) {
        ms.requestMoreData(want - size + 10); requests++; await sleep(1500); continue;
      }
      var lastTime = bars.valueAt(bars.lastIndex())[0];
      var ready = ch.getAllStudies().every(function (s) {
        var src = model.dataSourceForId(s.id);
        if (!src || src.isLoading() || src.isFailed()) return false;
        var row = src.data().valueAt(bars.lastIndex());
        return src.data().size() >= size && !!row && row[0] === lastTime;
      });
      if (ready) return {ok: true, symbol: ch.symbol(), res: ch.resolution(), bars: size, requests: requests,
                         first: bars.valueAt(bars.firstIndex())[0]};
    }
    await sleep(1000);
  }
  return {ok: false, bars: cw.model().mainSeries().bars().size()};
})"""


def screen_db() -> sqlite3.Connection:
    conn = connect(DB)
    migrate(conn)
    return conn


async def tv_phase(coins: list[str]) -> None:
    cdp = TradingViewCDP(timeout=1000)
    page = next(p for p in await cdp.chart_pages() if p.layout_id == LAYOUT)
    if not ORIGINAL.exists():
        ORIGINAL.write_text(json.dumps(await cdp.evaluate(page, STATE_JS), indent=1), encoding="utf-8")
        print("Market_check state saved to", ORIGINAL)
    agent = json.loads(AGENT_STUDIES.read_text(encoding="utf-8"))
    wanted, seen = [], set()
    for s in agent:  # the AGENT charts' studies once each, without the ones the screen does not read
        if s["scriptIdPart"] not in seen and s["name"] not in SKIP_STUDIES:
            seen.add(s["scriptIdPart"])
            wanted.append({"name": s["name"], "scriptIdPart": s["scriptIdPart"], "version": (s.get("pine") or {}).get("version"),
                           "inputs": s["inputs"]})
    print("studies:", await cdp.evaluate(page, f"({SET_STUDIES_JS})({json.dumps(wanted)})", await_promise=True), flush=True)
    conn = screen_db()
    for coin in coins:
        symbol = f"BINANCE:{coin}USDT.P"
        for res, (tf, template) in TEMPLATES.items():
            have = conn.execute("SELECT count(*) FROM snapshots WHERE symbol = ? AND timeframe = ?", (coin, tf)).fetchone()[0]
            if have > 1000:
                print(f"{coin} {tf}: {have} snapshots already stored")
                continue
            started = time.monotonic()
            loaded = await cdp.evaluate(page, f"({LOAD_JS})({json.dumps(symbol)}, {json.dumps(res)}, {WANT_BARS})", await_promise=True)
            if not loaded.get("ok") or loaded.get("symbol") != symbol:
                print(f"{coin} {tf}: not loaded {loaded}")
                continue
            spec = catalog.js_spec(template)
            stored, from_time = 0, 0
            while from_time is not None:
                raw = await cdp.evaluate(page, js.read_history(spec, 0, from_time, WARMUP, 2000))
                if raw.get("error") or raw.get("problems") or raw.get("symbol") != symbol:
                    print(f"{coin} {tf}: read problem {raw.get('error') or raw.get('problems') or raw.get('symbol')}")
                    break
                snaps = [Snapshot(coin, tf, row[0] * 1000, 1, int(time.time() * 1000), values=row[6], ohlcv=row[1:6],
                                  source="backfill") for row in raw["rows"]]
                store_snapshots(conn, snaps)
                stored += len(snaps)
                from_time = raw.get("next_time")
            print(f"{coin} {tf}: {loaded['bars']} bars, {stored} snapshots stored in {time.monotonic() - started:.0f} s")
            sys.stdout.flush()
    conn.close()


async def restore() -> None:
    if not ORIGINAL.exists():
        print("nothing to restore")
        return
    state = json.loads(ORIGINAL.read_text(encoding="utf-8"))
    cdp = TradingViewCDP(timeout=300)
    page = next(p for p in await cdp.chart_pages() if p.layout_id == LAYOUT)
    studies = [{"name": s["name"], "scriptIdPart": s["scriptIdPart"], "version": s["version"], "inputs": s["inputs"]}
               for s in state["studies"]]
    print("studies:", await cdp.evaluate(page, f"({SET_STUDIES_JS})({json.dumps(studies)})", await_promise=True))
    back = await cdp.evaluate(page, f"({LOAD_JS})({json.dumps(state['symbol'])}, {json.dumps(state['resolution'])}, 300)",
                              await_promise=True)
    print("Market_check restored:", back.get("symbol"), state["resolution"])
    ORIGINAL.replace(ORIGINAL.with_suffix(".restored.json"))


def screen_settings(coins: list[str]):
    s = settings.model_copy(deep=True)
    s.exchange.symbols = {c: SymbolConfig(tradingview=f"BINANCE:{c}USDT.P", markets={"binance-usdm": f"{c}/USDT:USDT"})
                          for c in coins}
    s.journal.path = str(DB)
    s.market_data.history_days = 110
    return s


def candles_phase(coins: list[str]) -> None:
    from tradeagent.market.candles import sync_candles, sync_funding, sync_market_info
    from tradeagent.venues import MarketData

    s = screen_settings(coins)
    conn = screen_db()
    client = MarketData("binance-usdm")
    now = int(time.time() * 1000)
    for coin in coins:
        market = f"{coin}/USDT:USDT"
        for tf in ("1m", "5m", "15m", "1h"):
            added = sync_candles(conn, client, coin, market, tf, now, s.market_data.history_days, None)
            print(f"{coin} {tf}: {added} candles")
            sys.stdout.flush()
        print(f"{coin} funding: {sync_funding(conn, client, coin, market, now, s.market_data.history_days)}")
    sync_market_info(conn, client, {c: f"{c}/USDT:USDT" for c in coins})
    conn.close()


def replay_phase() -> None:
    from tradeagent.setups.config import load_variants, register_variants
    from tradeagent.setups.engine import SetupEngine
    from tradeagent.sim.tracker import Tracker

    conn = screen_db()
    coins = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM snapshots")]
    s = screen_settings(coins)
    baseline = load_variants(settings.resolve(settings.shadow.setups), catalog)[0]
    with conn:
        conn.execute("DELETE FROM trades")
        conn.execute("DELETE FROM setups")
        conn.execute("DELETE FROM engine_state WHERE key LIKE 'engine:%'")
    register_variants(conn, [baseline])
    counts = SetupEngine(s, [baseline], conn).process()
    counts.update(Tracker(s, conn).update())
    print("replayed:", dict(counts), "baseline", baseline.id)
    conn.close()


def _stats(rows: list[tuple]) -> dict:
    rs = [r[1] for r in rows]
    if not rs:
        return {"n": 0}
    wins, losses = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    return {"n": len(rs), "win": sum(r > 0 for r in rs) / len(rs), "exp": st.mean(rs), "pf": wins / losses if losses else None,
            "target": sum(1 for r in rows if r[2] == "target") / len(rs)}


def _fmt(s: dict) -> str:
    if not s["n"]:
        return "no trades"
    pf = f"{s['pf']:.2f}" if s["pf"] is not None else "-"
    return f"n={s['n']:3d} win={s['win']:.0%} exp={s['exp']:+.3f}R PF={pf} target-hit={s['target']:.0%}"


def report() -> None:
    conn = screen_db()
    live = sqlite3.connect(f"file:{settings.resolve(settings.journal.path)}?mode=ro", uri=True)
    windows = {tf: conn.execute("SELECT min(bar_time), max(bar_time) FROM snapshots WHERE timeframe = ?", (tf,)).fetchone()
               for tf in ("5m", "15m")}
    query = ("SELECT t.entry_time, t.r_net, t.exit_reason, t.timeframe FROM trades t JOIN variants v ON v.id = t.variant_id"
             " WHERE v.role = 'baseline' AND t.taken = 1 AND t.status = 'closed' AND t.symbol = ?"
             " AND ((t.timeframe = '5m' AND t.confirm_time BETWEEN ? AND ?) OR (t.timeframe = '15m' AND t.confirm_time BETWEEN ? AND ?))"
             " ORDER BY t.entry_time")
    args = (*windows["5m"], *windows["15m"])
    print(f"windows: 5m {time.strftime('%Y-%m-%d', time.gmtime(windows['5m'][0] / 1000))} .. "
          f"{time.strftime('%Y-%m-%d', time.gmtime(windows['5m'][1] / 1000))}, 15m "
          f"{time.strftime('%Y-%m-%d', time.gmtime(windows['15m'][0] / 1000))} .. "
          f"{time.strftime('%Y-%m-%d', time.gmtime(windows['15m'][1] / 1000))}\n")
    current = {}
    print("current coins (live journal, same windows):")
    for coin in ("XRP", "SOL", "ETH"):
        rows = live.execute(query, (coin, *args)).fetchall()
        current[coin] = _stats(rows)
        print(f"  {coin:8} {_fmt(current[coin])}")
    weakest = min(v["exp"] for v in current.values() if v["n"])
    print(f"  weakest current expectancy: {weakest:+.3f}R\n")
    print("candidates:")
    verdicts = []
    for (coin,) in conn.execute("SELECT DISTINCT symbol FROM trades ORDER BY symbol").fetchall():
        rows = conn.execute(query, (coin, *args)).fetchall()
        s = _stats(rows)
        if not s["n"]:
            print(f"  {coin:8} no trades")
            continue
        mid = rows[len(rows) // 2][0]
        h1, h2 = _stats([r for r in rows if r[0] < mid]), _stats([r for r in rows if r[0] >= mid])
        tf5, tf15 = _stats([r for r in rows if r[3] == "5m"]), _stats([r for r in rows if r[3] == "15m"])
        checks = {"40+ trades": s["n"] >= 40, "both halves > 0": h1["n"] and h2["n"] and h1["exp"] > 0 and h2["exp"] > 0,
                  "PF >= 1.3": (s["pf"] or 0) >= 1.3, "target-hit >= 42%": s["target"] >= 0.42,
                  "beats weakest current": s["exp"] >= weakest}
        ok = all(checks.values())
        verdicts.append((ok, s["exp"], coin))
        print(f"  {coin:8} {_fmt(s)}")
        print(f"           halves {h1['exp']:+.3f} / {h2['exp']:+.3f} | 5m {_fmt(tf5)} | 15m {_fmt(tf15)}")
        print(f"           {'QUALIFIES' if ok else 'no'}: " + ", ".join(f"{k} {'ok' if v else 'FAIL'}" for k, v in checks.items()))
    chosen = [c for ok, _e, c in sorted(verdicts, reverse=True) if ok][:2]
    print(f"\nqualified (best first, at most 2): {chosen or 'none'}")


if __name__ == "__main__":
    action = sys.argv[1]
    coins = sys.argv[2].split(",") if len(sys.argv) > 2 else []
    if action == "tv":
        asyncio.run(tv_phase(coins))
    elif action == "restore":
        asyncio.run(restore())
    elif action == "candles":
        candles_phase(coins)
    elif action == "replay":
        replay_phase()
    elif action == "report":
        report()
