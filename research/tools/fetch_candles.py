"""Download Binance USDT-M candles into data/research/indicators_history.db (table candles), for the
indicator study. Research only; the agent's journal is not touched.

Run:  .venv\\Scripts\\python research\\tools\\fetch_candles.py 15m 2025-08-20
"""

from __future__ import annotations

import calendar
import sqlite3
import sys
import time
from pathlib import Path

from tradeagent.venues import MarketData

DB = Path(__file__).resolve().parents[2] / "data" / "research" / "indicators_history.db"
MARKETS = {"XRP": "XRP/USDT:USDT", "SOL": "SOL/USDT:USDT", "ETH": "ETH/USDT:USDT"}
STEP = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}


def main() -> None:
    tf = sys.argv[1] if len(sys.argv) > 1 else "15m"
    since = calendar.timegm(time.strptime(sys.argv[2] if len(sys.argv) > 2 else "2025-08-20", "%Y-%m-%d")) * 1000
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS candles (symbol TEXT, tf TEXT, time INTEGER, open REAL, high REAL, low REAL,"
                 " close REAL, PRIMARY KEY (symbol, tf, time))")
    md = MarketData("binance-usdm", timeout_ms=30_000)
    for coin, market in MARKETS.items():
        start = (conn.execute("SELECT max(time) FROM candles WHERE symbol = ? AND tf = ?", (coin, tf)).fetchone()[0]
                 or since - STEP[tf]) + STEP[tf]
        total = 0
        while start < time.time() * 1000 - STEP[tf]:
            for attempt in range(5):
                try:
                    rows = md.fetch_ohlcv(market, tf, since=start, limit=1500)
                    break
                except Exception as exc:  # network hiccups: wait and retry
                    print(f"  {coin} retry {attempt + 1}: {exc}"[:120], flush=True)
                    time.sleep(5 * (attempt + 1))
            else:
                raise SystemExit(f"{coin}: giving up at {start}")
            if not rows:
                break
            with conn:
                conn.executemany("INSERT OR REPLACE INTO candles VALUES (?, ?, ?, ?, ?, ?, ?)",
                                 [(coin, tf, int(r[0]), r[1], r[2], r[3], r[4]) for r in rows])
            total += len(rows)
            start = int(rows[-1][0]) + STEP[tf]
        print(f"{coin} {tf}: +{total} candles", flush=True)


if __name__ == "__main__":
    main()
