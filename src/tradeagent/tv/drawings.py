"""Draw the paper account's trades on the TradingView charts (entry, stop, target and the result).

Each paper trade becomes a long/short position tool on the AGENT chart its signal came from (same coin,
same timeframe), locked so it is not moved by accident. Drawings are synced globally, so they also show in
any other layout (for example the user's Market_check) when it displays that coin. A closed trade is redrawn
with its real duration and a result label. Drawing never affects what the reader reads (only studies are read).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from typing import Any

from tradeagent.account.engine import ACCOUNT
from tradeagent.config import Settings
from tradeagent.journal.db import now_ms
from tradeagent.market.candles import tf_ms
from tradeagent.tv.cdp import TradingViewCDP
from tradeagent.tv.js import _call  # one place that formats JS calls
from tradeagent.tv.schedule import TV_INTERVAL

log = logging.getLogger("tradeagent.drawings")

OPEN_WIDTH_CANDLES = 12  # an open trade is drawn this wide until it closes
SHARED_GLOBALLY = 2  # TradingView line-tool sharing mode: NotShared 0, SharedInLayout 1, SharedGlobally 2
EXIT_NAMES = {"target": "TP", "stop": "SL", "breakeven": "BE", "kill switch": "KILL", "timeout": "TIME",
              "time stop": "TIME", "opposite signal": "EXIT", "trail": "TRAIL"}

_DRAW = """async function (p) {
  var api = window.TradingViewApi;
  var charts = api._chartWidgetCollection.getAll();
  var index = -1;
  for (var i = 0; i < charts.length; i++) {
    var series = charts[i].model().mainSeries();
    if (series.interval() === p.interval && series.symbol() === p.symbol) index = i;
  }
  if (index < 0) return { error: 'no ' + p.symbol + ' ' + p.interval + ' chart in this tab' };
  var chart = api.chart(index);
  var info = charts[index].model().mainSeries().symbolInfo();
  var tick = info.minmov / info.pricescale;
  var ids = [];
  ids.push(await chart.createMultipointShape(
    [{ time: p.entry_time, price: p.entry }, { time: p.end_time, price: p.entry }],
    { shape: p.side === 'long' ? 'long_position' : 'short_position', lock: true, disableUndo: true,
      overrides: { stopLevel: Math.max(1, Math.round(Math.abs(p.entry - p.stop) / tick)),
                   profitLevel: Math.max(1, Math.round(Math.abs(p.target - p.entry) / tick)),
                   accountSize: p.account, risk: p.risk_pct, riskDisplayMode: 'percents' } }));
  if (p.label) {
    ids.push(await chart.createShape({ time: p.label_time, price: p.label_price },
      { shape: 'text', lock: true, disableUndo: true, text: p.label,
        overrides: { color: p.label_color, fontsize: 12, bold: true } }));
  }
  chart.shareLineTools(ids, %d);
  return { ids: ids, chart: index };
}""" % SHARED_GLOBALLY

_REMOVE = """function (ids) {
  var api = window.TradingViewApi;
  var removed = {};
  api._chartWidgetCollection.getAll().forEach(function (cw, i) {
    var chart = api.chart(i);
    chart.getAllShapes().forEach(function (shape) {  // a shared drawing has a copy on every chart
      if (ids.indexOf(shape.id) >= 0) {
        try { chart.removeEntity(shape.id); removed[shape.id] = true; } catch (e) {}
      }
    });
  });
  return Object.keys(removed).length;
}"""


def drawing_spec(trade: sqlite3.Row, settings: Settings, now: int) -> dict[str, Any]:
    """What to draw for one paper trade (prices from the paper position, times in TradingView seconds)."""
    step = tf_ms(trade["timeframe"])
    closed = trade["status"] == "closed"
    end = trade["exit_time"] if closed else max(trade["entry_time"] + OPEN_WIDTH_CANDLES * step, now)
    spec: dict[str, Any] = {
        "symbol": settings.exchange.symbols[trade["symbol"]].tradingview,
        "interval": TV_INTERVAL[trade["timeframe"]],
        "side": trade["side"],
        "entry_time": trade["entry_time"] // 1000,
        "end_time": max(end, trade["entry_time"] + step) // 1000,
        "entry": trade["entry_fill"],
        "stop": trade["stop"],
        "target": trade["target"],
        "account": round(trade["balance_before"], 2),
        "risk_pct": settings.paper_account.risk_per_trade * 100,
        "label": None,
    }
    if closed:
        reason = trade["exit_reason"]
        level = {"target": trade["target"], "stop": trade["stop"]}.get(reason, trade["entry_fill"])
        r = trade["r_net"]
        spec.update(
            label=f"{EXIT_NAMES.get(reason, reason)} {r:+.2f}R ({trade['pnl_usd']:+.2f}$)",
            label_color="#089981" if r > 0 else "#f23645",
            label_time=trade["exit_time"] // 1000,
            label_price=level,
        )
    return spec


class TradeDrawer:
    def __init__(self, settings: Settings, conn: sqlite3.Connection, cdp: TradingViewCDP, pages_provider: Any) -> None:
        self.settings = settings
        self.conn = conn
        self.cdp = cdp
        self.pages_provider = pages_provider  # async () -> {layout_id: ChartPage} (the watchdog)

    def _trades(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT a.id, a.symbol, a.timeframe, a.side, a.status, a.entry_time, a.entry_fill, a.stop, a.exit_time,
                   a.exit_reason, a.r_net, a.pnl_usd, a.balance_before, t.target, d.drawn_state, d.shape_ids, d.layout_id
            FROM account_trades a JOIN trades t ON t.id = a.trade_id
            LEFT JOIN trade_drawings d ON d.account_trade_id = a.id
            WHERE a.account = ? AND a.status IN ('open', 'closed')
              AND (d.drawn_state IS NULL OR d.drawn_state != a.status)
            ORDER BY a.entry_time
            """,
            (ACCOUNT,),
        ).fetchall()

    async def sync(self) -> Counter[str]:
        """Draw new paper trades and redraw the ones that closed since they were drawn."""
        counts: Counter[str] = Counter()
        todo = self._trades()
        if not todo:
            return counts
        pages = await self.pages_provider()
        now = now_ms()
        for trade in todo:
            layout = self.settings.layout_for(trade["symbol"])
            page = pages.get(layout)
            if page is None:
                counts["tab not open"] += 1
                continue
            if trade["shape_ids"]:
                await self.cdp.evaluate(pages.get(trade["layout_id"], page), _call(_REMOVE, json.loads(trade["shape_ids"])))
            result = await self.cdp.evaluate(page, _call(_DRAW, drawing_spec(trade, self.settings, now)), await_promise=True)
            if not result or result.get("error"):
                log.warning("paper trade %s not drawn: %s", trade["id"], (result or {}).get("error"))
                counts["failed"] += 1
                continue
            with self.conn:
                self.conn.execute(
                    "INSERT INTO trade_drawings (account_trade_id, layout_id, shape_ids, drawn_state, updated_at)"
                    " VALUES (?, ?, ?, ?, ?) ON CONFLICT (account_trade_id) DO UPDATE SET layout_id = excluded.layout_id,"
                    " shape_ids = excluded.shape_ids, drawn_state = excluded.drawn_state, updated_at = excluded.updated_at",
                    (trade["id"], layout, json.dumps(result["ids"]), trade["status"], now),
                )
            counts["redrawn" if trade["shape_ids"] else "drawn"] += 1
        return counts

    async def clear(self) -> int:
        """Remove every drawing the agent made and forget them."""
        rows = self.conn.execute("SELECT layout_id, shape_ids FROM trade_drawings").fetchall()
        pages = await self.pages_provider()
        removed = 0
        for layout in {r["layout_id"] for r in rows}:
            ids = [i for r in rows if r["layout_id"] == layout for i in json.loads(r["shape_ids"])]
            if layout in pages:
                removed += await self.cdp.evaluate(pages[layout], _call(_REMOVE, ids)) or 0
        with self.conn:
            self.conn.execute("DELETE FROM trade_drawings")
        return removed
