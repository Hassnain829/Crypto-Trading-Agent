"""Backfill snapshots from the history loaded in TradingView (source = 'backfill').

Lets the shadow engine work on past candles immediately instead of waiting for live reads. With `bars`,
each chart first loads that much history (TradingView Essential allows 10,000 bars). The first loaded
candles are skipped while the indicators warm up. Live snapshots always win.
"""

from __future__ import annotations

import logging
import time
from collections import Counter

from tradeagent.tv import js
from tradeagent.tv.cdp import TradingViewCDP
from tradeagent.tv.reader import SignalReader
from tradeagent.tv.schedule import TV_INTERVAL
from tradeagent.tv.snapshots import Snapshot, store_snapshots

log = logging.getLogger("tradeagent.backfill")

WARMUP_CANDLES = 300  # Zero Lag needs ~280 candles before its bands are valid
CHUNK_ROWS = 2000  # rows per read, so one answer stays a few MB
LONG_TIMEOUT_S = 600  # loading 10,000 bars and recomputing every study can take minutes


async def backfill_snapshots(reader: SignalReader, bars: int | None = None, *, reload_after: bool = False) -> Counter[str]:
    settings = reader.settings
    tv = settings.tradingview
    pages = await reader.watchdog.pages()
    cdp = TradingViewCDP(tv.cdp_host, tv.cdp_port, timeout=LONG_TIMEOUT_S) if bars else reader.cdp
    min_bars = bars or tv.min_bars
    timeout_ms = LONG_TIMEOUT_S * 1000 - 30_000 if bars else reader._timeout_ms
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
        started = time.monotonic()
        prep = await cdp.evaluate(
            page,
            js.prepare(tv_symbol, min_bars, timeout_ms,
                       max_requests=100 if bars else 5, accept_less=bool(bars)),
            await_promise=True,
        )
        if not prep.get("ok"):
            log.warning("%s %s: chart not prepared, skipping backfill (%s)", coin, layout, prep.get("charts"))
            counts["not prepared"] += 1
            continue
        log.info("%s %s prepared in %.0f s: %s", coin, layout, time.monotonic() - started,
                 [(c["interval"], c["bars"]) for c in prep["charts"]])
        index_by_interval = {c["interval"]: c["index"] for c in prep["charts"]}
        for tf in timeframes:
            index = index_by_interval.get(TV_INTERVAL[tf])
            if index is None:
                counts[f"no {tf} chart"] += 1
                continue
            spec = reader.catalog.js_spec(reader.template_for(tf))
            stored, from_time = 0, 0
            while from_time is not None:
                raw = await cdp.evaluate(page, js.read_history(spec, index, from_time, WARMUP_CANDLES, CHUNK_ROWS))
                if raw.get("error") or raw.get("problems") or raw.get("symbol") != tv_symbol:
                    log.warning("%s %s backfill problem: %s", coin, tf, raw.get("error") or raw.get("problems") or raw.get("symbol"))
                    counts["problems"] += 1
                    break
                read_at = reader.clock.now_ms()
                snaps = [
                    Snapshot(coin, tf, row[0] * 1000, reader.signal_version, read_at, values=row[6], ohlcv=row[1:6],
                             source="backfill")
                    for row in raw["rows"]
                ]
                store_snapshots(reader.conn, snaps)
                stored += len(snaps)
                from_time = raw.get("next_time")
            counts[f"{coin} {tf}"] = stored
    if reload_after:
        # Ten thousand bars per chart cost memory; the reader loads its normal history again by itself.
        for layout in {settings.htf_layout, *(settings.layout_for(coin) for coin in settings.exchange.symbols)}:
            if layout in pages:
                await cdp.evaluate(pages[layout], js.reload_tab())
    return counts
