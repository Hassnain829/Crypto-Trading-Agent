"""Command implementations for the TradingView signal reader (called from cli.py)."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager

from tradeagent.config import Settings, load_settings
from tradeagent.journal import connect, migrate
from tradeagent.logging_setup import setup_logging
from tradeagent.tv import js
from tradeagent.tv.catalog import load_catalog
from tradeagent.tv.coverage import coverage
from tradeagent.tv.reader import SignalReader
from tradeagent.tv.repaint import repaint_audit
from tradeagent.tv.snapshots import Snapshot

log = logging.getLogger("tradeagent.commands")


@contextmanager
def _reader(*, console_log: bool) -> Iterator[SignalReader]:
    settings = load_settings()
    setup_logging(settings, console=console_log)
    conn = connect(settings.resolve(settings.journal.path))
    try:
        migrate(conn)
        catalog = load_catalog(settings.resolve(settings.tradingview.catalog))
        yield SignalReader(settings, catalog, conn)
    finally:
        conn.close()


def _utc(ms: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ms / 1000))


def _summary(snap: Snapshot) -> str:
    """A short human-readable reading of the indicator values."""
    v = snap.values
    parts = []
    zl = v.get("zerolag", {})
    if zl:
        parts.append("ZeroLag bull" if zl.get("lower_band") is not None else "ZeroLag bear")
    kv = v.get("klinger", {})
    if kv.get("hist") is not None:
        parts.append("KVO green" if kv["hist"] >= 0 else "KVO red")
    vw = v.get("vwap", {})
    if vw.get("vwap") is not None and snap.ohlcv:
        parts.append("above VWAP" if snap.ohlcv[3] >= vw["vwap"] else "below VWAP")
    signals = [f"{key}.{name}" for key, fields in v.items() for name, value in fields.items() if value == 1]
    if signals:
        parts.append("SIGNALS: " + ", ".join(signals))
    return "; ".join(parts)


def tv_status() -> int:
    with _reader(console_log=False) as reader:
        async def run() -> int:
            pages = await reader.watchdog.pages()
            status = 0
            for name, layout_id in reader.settings.tradingview.layouts.items():
                page = pages.get(layout_id)
                if page is None:
                    print(f"{name:<11} NOT OPEN")
                    status = 1
                    continue
                state = await reader.cdp.evaluate(page, js.tab_state())
                charts = ", ".join(
                    f"{c['symbol']} {c['interval']} ({c['bars']} bars, {'ready' if c['series_status'] == 3 and not c['is_loading'] else 'loading'})"
                    for c in state["charts"]
                )
                print(f"{name:<11} {charts}")
            return status

        return asyncio.run(run())


def snapshot_once() -> int:
    """Read the last closed candle of every timeframe now, store the snapshots and print them."""
    with _reader(console_log=False) as reader:
        async def run() -> list[Snapshot]:
            await reader.start()
            return await reader.read(reader.settings.all_timeframes)

        snaps = asyncio.run(run())
        print(f"signal version {reader.signal_version}; clock offset {reader.clock.offset_ms:+d} ms")
        for s in snaps:
            status = "OK  " if s.ok else "FAIL"
            print(f"{status} {s.symbol:<4} {s.timeframe:<3} {_utc(s.bar_time_ms)}  latency {s.latency_ms / 1000:6.1f}s  {_summary(s)}")
            for problem in s.problems:
                print(f"       - {problem}")
        return 0 if all(s.ok for s in snaps) else 1


def run_reader() -> int:
    with _reader(console_log=True) as reader:
        print("Signal reader running. Press Ctrl+C to stop.")
        try:
            asyncio.run(reader.run())
        except KeyboardInterrupt:
            print("Stopped.")
        return 0


def coverage_report(hours: float) -> int:
    settings: Settings = load_settings()
    conn: sqlite3.Connection = connect(settings.resolve(settings.journal.path))
    try:
        migrate(conn)
        end = int(time.time() * 1000)
        rows = coverage(conn, settings.exchange.symbols, settings.all_timeframes, end - int(hours * 3600 * 1000), end)
    finally:
        conn.close()
    print(f"Snapshot coverage, last {hours:g} hours (Phase 1 target: >= 99% and latency <= 30 s)")
    print(f"{'symbol':<6} {'tf':<4} {'expected':>8} {'ok':>6} {'failed':>6} {'missing':>7} {'coverage':>9} {'p50 s':>6} {'p95 s':>6} {'max s':>6}")
    total_expected = total_ok = 0
    for r in rows:
        total_expected += r["expected"]
        total_ok += r["ok"]
        fmt = lambda x: f"{x:6.1f}" if x is not None else "     -"  # noqa: E731
        print(
            f"{r['symbol']:<6} {r['timeframe']:<4} {r['expected']:>8} {r['ok']:>6} {r['failed']:>6} {r['missing']:>7} "
            f"{r['coverage']:>8.1%} {fmt(r['latency_p50_s'])} {fmt(r['latency_p95_s'])} {fmt(r['latency_max_s'])}"
        )
    overall = total_ok / total_expected if total_expected else 1.0
    print(f"\nOverall: {total_ok}/{total_expected} = {overall:.2%}")
    return 0 if overall >= 0.99 else 1


def show_snapshots(symbol: str | None, timeframe: str | None, last: int) -> int:
    """Print the newest snapshots with every value, to compare by hand with TradingView's data window."""
    settings = load_settings()
    conn = connect(settings.resolve(settings.journal.path))
    try:
        migrate(conn)
        query = "SELECT symbol, timeframe, bar_time, open, high, low, close, values_json, problems_json FROM snapshots"
        clauses, params = [], []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if timeframe:
            clauses.append("timeframe = ?")
            params.append(timeframe)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        rows = conn.execute(query + " ORDER BY bar_time DESC, symbol, timeframe LIMIT ?", (*params, last)).fetchall()
    finally:
        conn.close()
    for sym, tf, bar_time, o, h, l, c, values_json, problems_json in rows:
        print(f"{sym} {tf} candle {_utc(bar_time)} UTC  O {o}  H {h}  L {l}  C {c}")
        for key, fields in json.loads(values_json).items():
            print(f"  {key:<9} " + ", ".join(f"{name}={value}" for name, value in fields.items()))
        if problems_json:
            print("  problems:", ", ".join(json.loads(problems_json)))
    return 0


def verify_candles(count: int) -> int:
    """Compare the candle stored with random good snapshots against Binance's candle (independent source)."""
    from tradeagent.market.binance import public_client

    settings = load_settings()
    conn = connect(settings.resolve(settings.journal.path))
    try:
        migrate(conn)
        rows = conn.execute(
            """
            SELECT symbol, timeframe, bar_time, open, high, low, close FROM snapshots
            WHERE problems_json IS NULL AND open IS NOT NULL ORDER BY random() LIMIT ?
            """,
            (count,),
        ).fetchall()
    finally:
        conn.close()
    client = public_client()
    mismatches = 0
    for symbol, tf, bar_time, *ohlc in rows:
        candle = client.fetch_ohlcv(settings.exchange.symbols[symbol].ccxt, tf, since=bar_time, limit=1)
        same = bool(candle) and candle[0][0] == bar_time and all(
            abs(a - b) <= 1e-9 * max(abs(b), 1) for a, b in zip(ohlc, candle[0][1:5])
        )
        mismatches += not same
        print(f"{'OK  ' if same else 'DIFF'} {symbol:<4} {tf:<3} {_utc(bar_time)}  TradingView {ohlc}  Binance {candle[0][1:5] if candle else None}")
    print(f"\n{len(rows) - mismatches}/{len(rows)} candles match Binance exactly.")
    return 0 if mismatches == 0 else 1


def repaint_report(hours: float, limit: int) -> int:
    with _reader(console_log=False) as reader:
        report = asyncio.run(repaint_audit(reader, hours, limit))
    print(f"Repaint audit, last {hours:g} hours (up to {limit} snapshots per symbol and timeframe)")
    print(f"compared {report['compared']}, changed {report['changed']}, not re-readable {report['unavailable']}")
    if report["fields"]:
        print("Fields that changed after the candle closed:")
        for name, count in report["fields"].items():
            print(f"  {name:<32} {count}")
        print("Examples:", json.dumps(report["examples"], indent=1))
    else:
        print("No value changed: no repainting found.")
    return 0
