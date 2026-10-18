"""Live recorder for the indicator repaint test (research, not part of the agent).

Every 15 minutes, shortly after the candle close, it reads the signal flags of the candle that just closed on
chart 1 of the Market_check layout (qteGoFhV, XRPUSDT.P 15m) and stores them in data/research/indicator_live.db.
Later the same candles are read again from the chart history: a flag that is in the history but was not there
live (or the other way round) means the indicator repaints or plots with an offset.

Run:  .venv\\Scripts\\python research\\tools\\indicator_recorder.py
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

from tradeagent.tv.cdp import CDPError, TradingViewCDP

LAYOUT = "qteGoFhV"
STEP_S = 900  # 15m candles
DELAY_S = 20  # read this long after the close, when TradingView has the closed candle
DB = Path(__file__).resolve().parents[2] / "data" / "research" / "indicator_live.db"

READ_JS = """(function (barTime) {
  var api = window.TradingViewApi, ch = api.chart(0);
  var model = api._chartWidgetCollection.getAll()[0].model().model();
  var out = {symbol: ch.symbol(), interval: ch.resolution(), rows: []};
  ch.getAllStudies().forEach(function (s) {
    var src = model.dataSourceForId(s.id), mi = src.metaInfo(), styles = mi.styles || {};
    var data = src.data();
    if (!data || !data.size()) return;
    for (var k = data.lastIndex(); k >= Math.max(data.firstIndex(), data.lastIndex() - 5); k--) {
      var row = data.valueAt(k);
      if (!row || row[0] !== barTime) continue;
      (mi.plots || []).forEach(function (p, i) {
        if (p.type !== 'alertcondition' && p.type !== 'shapes') return;
        var title = (styles[p.id] && styles[p.id].title) || p.id;
        out.rows.push([s.name, i + ':' + p.type + ':' + title, row[i + 1]]);  // titles repeat (Q-Trend)
      });
    }
  });
  return out;
})"""


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS live (bar_time INTEGER, symbol TEXT, interval TEXT, study TEXT, plot TEXT,"
                 " value REAL, read_at INTEGER, PRIMARY KEY (bar_time, symbol, interval, study, plot))")
    conn.execute("CREATE TABLE IF NOT EXISTS runs (read_at INTEGER, bar_time INTEGER, rows INTEGER, note TEXT)")
    return conn


async def read_once(cdp: TradingViewCDP, conn: sqlite3.Connection, bar_time_s: int) -> str:
    pages = [p for p in await cdp.chart_pages() if p.layout_id == LAYOUT]
    if not pages:
        return "Market_check tab is not open"
    out = await cdp.evaluate(pages[0], f"({READ_JS})({bar_time_s})")
    now = int(time.time() * 1000)
    with conn:
        conn.executemany("INSERT OR IGNORE INTO live VALUES (?, ?, ?, ?, ?, ?, ?)",
                         [(bar_time_s * 1000, out["symbol"], out["interval"], study, plot, value, now)
                          for study, plot, value in out["rows"]])
    return f"{out['symbol']} {out['interval']}: {len(out['rows'])} values"


async def main() -> None:
    conn = connect()
    cdp = TradingViewCDP("127.0.0.1", 9222, timeout=30)
    while True:
        now = time.time()
        next_close = (int(now) // STEP_S + 1) * STEP_S
        await asyncio.sleep(next_close + DELAY_S - now)
        bar = next_close - STEP_S  # open time of the candle that just closed (TradingView uses seconds)
        try:
            note = await read_once(cdp, conn, bar)
        except (CDPError, OSError, KeyError, TypeError) as exc:
            note = f"failed: {exc}"[:200]
        with conn:
            conn.execute("INSERT INTO runs VALUES (?, ?, ?, ?)", (int(time.time() * 1000), bar * 1000,
                         conn.execute("SELECT count(*) FROM live WHERE bar_time = ?", (bar * 1000,)).fetchone()[0], note))
        print(time.strftime("%H:%M:%S"), note, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
