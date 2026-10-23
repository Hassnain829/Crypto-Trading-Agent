"""The 1.5-year test of 2026-10-20: the agent's own engine on Python-computed indicator values (research only).

    .venv\\Scripts\\python -u research\\tools\\long_backtest.py snapshots XRP SOL ...   # indicators -> snapshots
    .venv\\Scripts\\python -u research\\tools\\long_backtest.py engine                  # SetupEngine + Tracker (baseline)
    .venv\\Scripts\\python -u research\\tools\\long_backtest.py check                   # trades vs the TradingView v6 test
    .venv\\Scripts\\python -u research\\tools\\long_backtest.py ideas                   # every idea, main and check coins

Data: data/research/long/journal.db (long_data.py). Indicators: long_indicators.py (Q-Trend, Klinger, Squeeze; no
Trendline, which is closed-source, so quality A comes from open interest only). The live journal is never written.
"""
from __future__ import annotations

import importlib.util
import json
import random
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ld = _load("long_data")
li = _load("long_indicators")
WARMUP_BARS = 1000


def snapshots(coins: list[str]) -> None:
    from tradeagent.tv.snapshots import Snapshot, store_snapshots

    conn = ld.db()
    for coin in coins:
        for tf, step in (("5m", 300_000), ("15m", 900_000)):
            t0 = time.monotonic()
            rows = conn.execute("SELECT open_time, open, high, low, close, volume FROM candles WHERE symbol = ? AND timeframe = ?"
                                " ORDER BY open_time", (coin, tf)).fetchall()
            values = li.compute(rows)
            with conn:
                conn.execute("DELETE FROM snapshots WHERE symbol = ? AND timeframe = ?", (coin, tf))
            batch = []
            for r, v in list(zip(rows, values))[WARMUP_BARS:]:
                batch.append(Snapshot(coin, tf, r[0], 6, r[0] + step + 5_000, values=v, ohlcv=list(r[1:6]), source="backfill"))
                if len(batch) == 20_000:
                    store_snapshots(conn, batch)
                    batch = []
            store_snapshots(conn, batch)
            conn.commit()
            print(f"{coin} {tf}: {len(rows) - WARMUP_BARS} snapshots in {time.monotonic() - t0:.0f} s", flush=True)
        # 1h and 4h charts (AGENT-HTF): Zero Lag only, from 15m candles, for the htf filters and the 15m trend filter
        rows15 = conn.execute("SELECT open_time, open, high, low, close, volume FROM candles WHERE symbol = ? AND timeframe = '15m'"
                              " ORDER BY open_time", (coin,)).fetchall()
        for hours, tf in ((1, "1h"), (4, "4h")):
            bars = li.htf_bars(rows15, hours)
            z = li.zerolag([b[2] for b in bars], [b[3] for b in bars], [b[4] for b in bars])
            with conn:
                conn.execute("DELETE FROM snapshots WHERE symbol = ? AND timeframe = ?", (coin, tf))
            step = hours * 3_600_000
            store_snapshots(conn, [Snapshot(coin, tf, b[0], 6, b[0] + step + 5_000, values={"zerolag": v}, ohlcv=list(b[1:6]),
                                            source="backfill") for b, v in list(zip(bars, z))[300:]])
            conn.commit()
            print(f"{coin} {tf}: {len(bars) - 300} snapshots (Zero Lag)", flush=True)
    conn.close()


def engine() -> None:
    from tradeagent.setups.config import load_variants, register_variants
    from tradeagent.setups.engine import SetupEngine
    from tradeagent.sim.tracker import Tracker
    from tradeagent.tv.catalog import load_catalog

    conn = ld.db()
    coins = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM snapshots")]
    s = ld.long_settings(coins)
    catalog = load_catalog(ld.settings.resolve(ld.settings.tradingview.catalog))
    baseline = load_variants(ld.settings.resolve(ld.settings.shadow.setups), catalog)[0]
    with conn:
        for table in ("trades", "setups", "account_trades", "account_state"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM engine_state WHERE key LIKE 'engine:%'")
    register_variants(conn, [baseline])
    t0 = time.monotonic()
    counts = SetupEngine(s, [baseline], conn).process()
    print(f"engine: {dict(counts)} in {time.monotonic() - t0:.0f} s", flush=True)
    counts = Tracker(s, conn).update()
    print(f"tracker: {dict(counts)} in {time.monotonic() - t0:.0f} s; baseline {baseline.id}", flush=True)
    conn.close()


def _stats(rs: list[float]) -> str:
    if not rs:
        return "no trades"
    w, l = sum(x for x in rs if x > 0), -sum(x for x in rs if x < 0)
    return f"n={len(rs):4d} win={sum(x > 0 for x in rs) / len(rs):4.0%} {sum(rs) / len(rs):+.3f}R PF={w / l if l else 0:.2f}"


def check() -> None:
    """The same window as the TradingView v6 backtest (2026-07-13 .. 2026-10-18): Python-based trades vs TradingView-based."""
    v6 = sqlite3.connect(f"file:{ROOT / 'data' / 'replay' / 'journal-v6.db'}?mode=ro", uri=True)
    lg = sqlite3.connect(f"file:{ld.DB}?mode=ro", uri=True)
    q = ("SELECT symbol, timeframe, side, entry_time, r_net, context_json FROM trades WHERE book = 'exploration' AND taken = 1"
         " AND status = 'closed' AND symbol = ? AND timeframe = ? AND entry_time BETWEEN ? AND ?")
    all_a, all_b = [], []
    for coin in ld.MAIN:
        for tf in ("5m", "15m"):
            win = v6.execute("SELECT min(entry_time), max(entry_time) FROM trades WHERE taken = 1 AND symbol = ? AND timeframe = ?",
                             (coin, tf)).fetchone()
            a = v6.execute(q, (coin, tf, *win)).fetchall()
            b = lg.execute(q, (coin, tf, *win)).fetchall()
            if not b:
                continue
            all_a += a
            all_b += b
            same = len({(r[2], r[3]) for r in a} & {(r[2], r[3]) for r in b})
            print(f"{coin} {tf}: TradingView {_stats([r[4] for r in a])} | Python {_stats([r[4] for r in b])} | same trades {same}")
    print(f"together: TradingView {_stats([r[4] for r in all_a])} | Python {_stats([r[4] for r in all_b])}")


def baseline() -> None:
    """The current strategy (baseline v0-773ea9) year by year: every coin and chart, the tiers, and the demo account
    at today's rules ($150, A 3% / B 2%, 12% open-risk budget), restarted each year and over the whole period."""
    ct = _load("coordination_test")
    dt = _load("demo_ideas_test")
    conn = sqlite3.connect(f"file:{ld.DB}?mode=ro", uri=True)
    trades = [t for t in ct.load(conn, 1, ld.START_MS, tuple(ld.COINS)) if t["closed"]]
    conn.close()
    end = max(t["entry"] for t in trades)
    years = []
    lo = ld.START_MS
    while lo < end:
        hi = lo + 365 * 86_400_000
        years.append((lo, min(hi, end + 1)))
        lo = hi
    fmt = lambda ms: time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))
    print(f"== Current strategy (baseline), {fmt(ld.START_MS)} .. {fmt(end)}, {len(trades)} closed trades")
    for name, sel in (("all", lambda t: True), *((c, (lambda c: lambda t: t["symbol"] == c)(c)) for c in ld.COINS),
                      ("5m", lambda t: t["tf"] == "5m"), ("15m", lambda t: t["tf"] == "15m"),
                      ("quality A (OI, from 2025-08-29)", lambda t: t["q"] == "A"), ("squeeze fired", lambda t: t["sqz"] is True),
                      ("squeeze not fired", lambda t: t["sqz"] is False)):
        line = f"   {name:32} {_stats([t['r'] for t in trades if sel(t)]):38} |"
        for lo, hi in years:
            rs = [t["r"] for t in trades if sel(t) and lo <= t["entry"] < hi]
            line += f" {fmt(lo)[:7]}: {len(rs):4d} {sum(rs) / len(rs) if rs else 0:+.3f}R |"
        print(line)
    for group, coins in (("main coins (XRP, SOL, ETH)", ld.MAIN), ("every coin", ld.COINS)):
        sel = [t for t in trades if t["symbol"] in coins]
        bal, dd = dt.account(sel)
        line = f"   demo $150, {group}: whole period ${bal:,.0f} ({bal / 150 - 1:+.0%}) max DD {dd:.1%} | each year from $150:"
        for lo, hi in years:
            b, d = dt.account([t for t in sel if lo <= t["entry"] < hi])
            line += f" {fmt(lo)[:7]} {b / 150 - 1:+.0%} (DD {d:.0%}),"
        print(line)


OI_START = 1756425600000 + 5 * 3600_000  # 2025-08-29 05:00 UTC: the first 4-hour OI change (tiers known from here)


def ideas() -> None:
    windows = (("1.5 YEARS (no tiers before 2025-08-29: those trades count as B)", ld.START_MS),
               ("SINCE 2025-08-29, with tiers", OI_START))
    if ld.DB == ld.DB4:
        windows = (("4 YEARS from 2022-10-01 (no tiers before 2025-08-29: those trades count as B)", ld.START_MS),)
    for label, since in windows:
        print(f"\n################ {label}")
        ideas_window(since)


def ideas_window(since: int) -> None:
    ct = _load("coordination_test")
    op = _load("one_position_test")
    dt = _load("demo_ideas_test")
    conn = sqlite3.connect(f"file:{ld.DB}?mode=ro", uri=True)
    every = ct.load(conn, 1, since, tuple(ld.COINS))
    ct.trend15(conn, every)
    for t in every:
        if not t["closed"]:
            t["skip"] = True
    every = [t for t in every if not t.get("skip")]
    end = max(t["entry"] for t in every)
    thirds = [since + k * (end - since) // 3 for k in range(4)]
    groups = {"MAIN coins (XRP, SOL, ETH)": ld.MAIN, "CHECK coins (" + ", ".join(ld.CHECK) + ")": ld.CHECK}
    for gname, coins in groups.items():
        trades = [t for t in every if t["symbol"] in coins]
        if not trades:
            continue
        print(f"\n== {gname}: {len(trades)} trades {time.strftime('%Y-%m-%d', time.gmtime(trades[0]['entry'] / 1000))} .."
              f" {time.strftime('%Y-%m-%d', time.gmtime(trades[-1]['entry'] / 1000))}; thirds split at"
              f" {time.strftime('%Y-%m-%d', time.gmtime(thirds[1] / 1000))} and {time.strftime('%Y-%m-%d', time.gmtime(thirds[2] / 1000))}")
        print(f"   quality A (open interest up > 1% in 4 h): {sum(t['q'] == 'A' for t in trades)};"
              f" squeeze fired: {sum(t['sqz'] is True for t in trades)}")
        for name, sel in (("all", lambda t: True), ("quality A", lambda t: t["q"] == "A"), ("quality B", lambda t: t["q"] == "B"),
                          ("squeeze fired", lambda t: t["sqz"] is True), ("B without squeeze", lambda t: t["q"] == "B" and t["sqz"] is not True)):
            print(f"   {name:22} {_stats([t['r'] for t in trades if sel(t)])}")
        base_run = op.run(conn, trades, None)
        dup, by_coin = [], {}
        for t in sorted(base_run, key=lambda x: x["entry"]):
            live = [o for o in by_coin.get(t["symbol"], []) if o["exit"] > t["entry"]]
            if any(o["side"] == t["side"] and o["entry"] < t["entry"] for o in live):
                dup.append(t)
            by_coin[t["symbol"]] = live + [t]
        print(f"   {'duplicates':22} {_stats([t['r'] for t in dup])}")
        rules = {r: ("ct", r) for r in ct.RULES if not r.startswith("B3")}
        rules.update({p: ("op", pol) for p, pol in op.POLICIES.items() if pol is not None})
        base = {t["id"]: t["r"] for t in trades}
        print(f"   {'rule':48} {'trades':>6} {'R/trade':>8} {'third 1':>8} {'third 2':>8} {'third 3':>8} {'total':>8} {'DD R':>6}"
              f" {'both SL':>7} | {'$150 at today’s rules (A 3% / B 2%, 12%)':>40} | P(beats now)")
        for name, (kind, key) in rules.items():
            taken = ct.apply(conn, trades, key) if kind == "ct" else op.run(conn, trades, key)
            taken = [t for t in taken if t["closed"]]
            parts = [sum(t["r"] for t in taken if thirds[k] <= t["entry"] < thirds[k + 1] + (1 if k == 2 else 0)) for k in range(3)]
            cum = peak = dd = 0.0
            for t in sorted(taken, key=lambda x: x["exit"]):
                cum += t["r"]
                peak = max(peak, cum)
                dd = max(dd, peak - cum)
            bal, add = dt.account(taken)
            p = dt.beats(base, {t["id"]: t["r"] for t in taken}, trades, n=3000)
            print(f"   {name:48} {len(taken):6d} {sum(parts) / max(len(taken), 1):+8.3f} {parts[0]:+8.1f} {parts[1]:+8.1f} {parts[2]:+8.1f}"
                  f" {sum(parts):+8.1f} {dd:6.1f} {op.both_stopped(taken):7d} | ${bal:12,.0f} ({bal / 150 - 1:+8.0%}) DD {add:5.1%} | "
                  + ("-" if p != p else f"{p:4.0%}"), flush=True)
        if coins == ld.MAIN:
            print("   risk rules (every signal):")
            for label, ra, rb, bud in [("A 3% / B 2%, 12% budget (now)", .03, .02, .12), ("A 3% / B 2%, 20% budget", .03, .02, .20),
                                       ("flat 5%, 20% budget", .05, .05, .20), ("A 5% / B 3%, 20% budget", .05, .03, .20)]:
                bal, add = dt.account(trades, ra, rb, bud)
                print(f"   {label:36} ${bal:12,.0f} ({bal / 150 - 1:+8.0%}) max DD {add:5.1%}")
    conn.close()


if __name__ == "__main__":
    if "--4y" in sys.argv:
        sys.argv.remove("--4y")
        ld.use_4y()
    cmd = sys.argv[1]
    if cmd == "snapshots":
        snapshots(sys.argv[2:] or ld.COINS)
    elif cmd == "engine":
        engine()
    elif cmd == "check":
        check()
    elif cmd == "ideas":
        ideas()
    elif cmd == "baseline":
        baseline()
