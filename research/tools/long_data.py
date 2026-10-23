"""Data for the 1.5-year test of 2026-10-20 (research only; the agent's journal is not touched).

    .venv\\Scripts\\python -u research\\tools\\long_data.py candles     # Binance USDT-M candles, funding, market info
    .venv\\Scripts\\python -u research\\tools\\long_data.py oi          # TradingView 1h open interest (Market_check)

Everything goes into data/research/long/journal.db (the agent's journal schema), so the agent's own SetupEngine,
Tracker and account rules can replay it.
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
from tradeagent.config import SymbolConfig, load_settings  # noqa: E402
from tradeagent.journal import connect, migrate  # noqa: E402

DB = ROOT / "data" / "research" / "long" / "journal.db"
MAIN = ["XRP", "SOL", "ETH"]
CHECK = ["BTC", "BNB", "DOGE", "LTC", "ADA", "LINK", "AVAX", "NEAR", "SUI", "ZEC"]
COINS = MAIN + CHECK
DAYS = 560          # 2025-04-08 onwards: 1.5 years of trades from 2025-04-20 plus warm-up
START_MS = 1745107200000  # 2025-04-20 00:00 UTC: trades are counted from here
settings = load_settings(ROOT)

# The 4-year set (the user, 2026-10-20): XRP, SOL, ETH and BTC from 2022-10-01, in its own journal.
DB4 = ROOT / "data" / "research" / "long4" / "journal.db"
DAYS4 = 1493                # 2022-09-19 onwards: trades from 2022-10-01 plus warm-up
START4_MS = 1664582400000   # 2022-10-01 00:00 UTC


def use_4y() -> None:
    """Point this module (and the tools that use it) at the 4-year set."""
    global DB, MAIN, CHECK, COINS, DAYS, START_MS
    DB, MAIN, CHECK, DAYS, START_MS = DB4, ["XRP", "SOL", "ETH"], ["BTC"], DAYS4, START4_MS
    COINS = MAIN + CHECK


class Throttled:
    """A market-data client that waits between requests (two downloads run at once; Binance allows 2,400 weight a minute)."""

    def __init__(self, inner, pause: float) -> None:
        self._inner, self._pause = inner, pause

    def fetch_ohlcv(self, *args, **kwargs):
        time.sleep(self._pause)
        return self._inner.fetch_ohlcv(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def long_settings(coins: list[str] = COINS):
    s = settings.model_copy(deep=True)
    s.exchange.symbols = {c: SymbolConfig(tradingview=f"BINANCE:{c}USDT.P", markets={"binance-usdm": f"{c}/USDT:USDT"})
                          for c in coins}
    s.journal.path = str(DB)
    s.market_data.history_days = DAYS
    return s


def db() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(DB)
    migrate(conn)
    return conn


def copy_from_long() -> None:
    """Start the 4-year journal with what the 1.5-year download already has (complete coins only)."""
    src = ROOT / "data" / "research" / "long" / "journal.db"
    conn = db()
    conn.execute("ATTACH DATABASE ? AS src", (str(src),))
    for coin in COINS:
        for tf in ("15m", "5m", "1m"):
            if conn.execute("SELECT count(*) FROM candles WHERE symbol = ? AND timeframe = ?", (coin, tf)).fetchone()[0]:
                continue
            n = conn.execute("SELECT count(*) FROM src.candles WHERE symbol = ? AND timeframe = ?", (coin, tf)).fetchone()[0]
            if n >= {"15m": 53000, "5m": 160000, "1m": 800000}[tf]:
                with conn:
                    conn.execute("INSERT OR IGNORE INTO candles SELECT * FROM src.candles WHERE symbol = ? AND timeframe = ?", (coin, tf))
                print(f"{coin} {tf}: {n} candles copied from the 1.5-year journal", flush=True)
        with conn:
            conn.execute("INSERT OR IGNORE INTO open_interest SELECT * FROM src.open_interest WHERE symbol = ?", (coin,))
    conn.commit()
    conn.execute("DETACH DATABASE src")
    conn.close()


def candles(pause: float = 0.0) -> None:
    from tradeagent.market.candles import sync_candles, sync_funding, sync_market_info
    from tradeagent.venues import MarketData

    conn = db()
    client = Throttled(MarketData("binance-usdm"), pause) if pause else MarketData("binance-usdm")
    now = int(time.time() * 1000)
    for coin in COINS:
        market = f"{coin}/USDT:USDT"
        for tf in ("15m", "5m", "1m"):
            t0 = time.monotonic()
            for attempt in range(5):
                try:
                    added = sync_candles(conn, client, coin, market, tf, now, DAYS, None)
                    break
                except Exception as exc:  # network hiccups: wait and retry (the sync continues where it stopped)
                    print(f"  {coin} {tf} retry {attempt + 1}: {exc}"[:160], flush=True)
                    time.sleep(10 * (attempt + 1))
            else:
                raise SystemExit(f"{coin} {tf}: giving up")
            print(f"{coin} {tf}: +{added} candles in {time.monotonic() - t0:.0f} s", flush=True)
        print(f"{coin} funding: {sync_funding(conn, client, coin, market, now, DAYS)}", flush=True)
    sync_market_info(conn, client, {c: f"{c}/USDT:USDT" for c in COINS})
    conn.close()


OI_LOAD_JS = """(async function (symbol, res, want) {
  var api = window.TradingViewApi, ch = api.chart(0), cw = api._chartWidgetCollection.getAll()[0];
  var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  if (ch.symbol() !== symbol) ch.setSymbol(symbol, {});
  if (ch.resolution() !== res) ch.setResolution(res, {});
  await sleep(6000);
  var started = Date.now(), requests = 0, last = -1, still = 0;
  while (Date.now() - started < 300000) {
    var ms = cw.model().mainSeries(), size = ms.bars().size();
    if (ch.symbol() === symbol && size > 0 && !ms.isLoading()) {
      if (size >= want || !ms.requestMoreDataAvailable() || still > 15) break;
      if (size === last) still++; else { still = 0; last = size; }
      ms.requestMoreData(want - size + 10); requests++;
    }
    await sleep(1500);
  }
  var b = cw.model().mainSeries().bars(), rows = [];
  for (var i = b.firstIndex(); i <= b.lastIndex(); i++) { var v = b.valueAt(i); if (v) rows.push([v[0], v[4]]); }
  return {symbol: ch.symbol(), bars: rows.length, rows: rows};
})"""


async def oi() -> None:
    """1h open interest closes from TradingView (BINANCE:<coin>USDT.P_OI), stored at every 15m slot of the next hour
    (the engine compares the newest value with the one 4 h earlier)."""
    from tradeagent.tv.cdp import TradingViewCDP

    cdp = TradingViewCDP(timeout=600)
    page = next(p for p in await cdp.chart_pages() if p.layout_id == "qteGoFhV")
    conn = db()
    for coin in COINS:
        out = await cdp.evaluate(page, f"({OI_LOAD_JS})({json.dumps(f'BINANCE:{coin}USDT.P_OI')}, '60', 10000)", await_promise=True)
        if out.get("symbol") != f"BINANCE:{coin}USDT.P_OI" or not out.get("rows"):
            print(f"{coin}: no OI ({out.get('symbol')}, {out.get('bars')} bars)", flush=True)
            continue
        rows = []
        for t, c in out["rows"]:
            closed = (t + 3600) * 1000  # the hour's value is known when it closes
            for k in range(4):
                rows.append((coin, closed + k * 900_000, c))
        with conn:
            conn.execute("DELETE FROM open_interest WHERE symbol = ?", (coin,))
            conn.executemany("INSERT OR REPLACE INTO open_interest (symbol, time, amount, value) VALUES (?, ?, ?, NULL)", rows)
        first = time.strftime("%Y-%m-%d", time.gmtime(out["rows"][0][0]))
        print(f"{coin}: {out['bars']} hours of OI from {first}", flush=True)
    conn.close()


if __name__ == "__main__":
    if "--4y" in sys.argv:
        use_4y()
    if sys.argv[1] == "candles":
        if DB == DB4:
            copy_from_long()
        candles(0.6 if DB == DB4 else 0.0)
    elif sys.argv[1] == "oi":
        asyncio.run(oi())
