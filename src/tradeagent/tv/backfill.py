"""Backfill snapshots from the history already loaded in TradingView (source = 'backfill').

Lets the shadow engine work on days of past candles immediately instead of waiting for live reads.
The first loaded candles are skipped while the indicators warm up. Live snapshots always win.
"""

from __future__ import annotations

import logging
from collections import Counter

from tradeagent.tv import js
from tradeagent.tv.reader import SignalReader
from tradeagent.tv.schedule import TV_INTERVAL
from tradeagent.tv.snapshots import Snapshot, store_snapshots

log = logging.getLogger("tradeagent.backfill")

WARMUP_CANDLES = 300  # Zero Lag needs ~280 candles before its bands are valid


async def backfill_snapshots(reader: SignalReader) -> Counter[str]:
    settings = reader.settings
    pages = await reader.watchdog.pages()
    counts: Counter[str] = Counter()
    jobs = [(coin, False, settings.timeframes.trade) for coin in settings.exchange.symbols]
    jobs += [(coin, True, settings.timeframes.overview) for coin in settings.exchange.symbols]
    for coin, overview, timeframes in jobs:
        layout = settings.htf_layout if overview else settings.layout_for(coin)
        page = pages.get(layout)
        if page is None:
            counts["tab not open"] += 1
            continue
        tv_symbol = settings.exchange.symbols[coin].tradingview
        prep = await reader.cdp.evaluate(
            page, js.prepare(tv_symbol if overview else None, settings.tradingview.min_bars, reader._timeout_ms),
            await_promise=True,
        )
        if not prep.get("ok"):
            log.warning("%s %s: chart not prepared, skipping backfill", coin, layout)
            counts["not prepared"] += 1
            continue
        index_by_interval = {c["interval"]: c["index"] for c in prep["charts"]}
        for tf in timeframes:
            index = index_by_interval.get(TV_INTERVAL[tf])
            if index is None:
                counts[f"no {tf} chart"] += 1
                continue
            spec = reader.catalog.js_spec(reader.template_for(tf))
            raw = await reader.cdp.evaluate(page, js.read_history(spec, index, 0, WARMUP_CANDLES))
            if raw.get("error") or raw.get("problems") or raw.get("symbol") != tv_symbol:
                log.warning("%s %s backfill problem: %s", coin, tf, raw.get("error") or raw.get("problems") or raw.get("symbol"))
                counts["problems"] += 1
                continue
            read_at = reader.clock.now_ms()
            snaps = [
                Snapshot(coin, tf, row[0] * 1000, reader.signal_version, read_at, values=row[6], ohlcv=row[1:6],
                         source="backfill")
                for row in raw["rows"]
            ]
            store_snapshots(reader.conn, snaps)
            counts[f"{coin} {tf}"] = len(snaps)
    return counts
