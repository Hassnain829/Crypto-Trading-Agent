"""Test 1 of research/notes/2026-10-20-three-tests-plan.md: the baseline rules on 1h charts (about 14 months of
TradingView history read on Market_check), with a 1.5R and a 1.0R target. Reuses coin_screen.py's TradingView and
replay code with its own database (data/research/h1_engine.db). Nothing touches the live journal or AGENT layouts.

    .venv\\Scripts\\python -u research\\tools\\h1_engine.py tv        # 1h snapshots (then Market_check is restored)
    .venv\\Scripts\\python -u research\\tools\\h1_engine.py candles   # Binance 1m and 1h candles, funding
    .venv\\Scripts\\python -u research\\tools\\h1_engine.py replay    # both variants with the agent's engine
    .venv\\Scripts\\python -u research\\tools\\h1_engine.py report
"""
from __future__ import annotations

import asyncio
import importlib.util
import statistics as st
import sys
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("coin_screen", HERE / "coin_screen.py")
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

COINS = ["XRP", "SOL", "ETH"]
cs.DB = cs.ROOT / "data" / "research" / "h1_engine.db"
cs.TEMPLATES = {"60": ("1h", "scalp")}
HISTORY_DAYS = 430


def candles() -> None:
    from tradeagent.market.candles import sync_candles, sync_funding, sync_market_info
    from tradeagent.venues import MarketData

    conn, client, now = cs.screen_db(), MarketData("binance-usdm"), int(time.time() * 1000)
    for coin in COINS:
        market = f"{coin}/USDT:USDT"
        for tf in ("1m", "1h"):
            print(f"{coin} {tf}: {sync_candles(conn, client, coin, market, tf, now, HISTORY_DAYS, None)} candles", flush=True)
        print(f"{coin} funding: {sync_funding(conn, client, coin, market, now, HISTORY_DAYS)}", flush=True)
    sync_market_info(conn, client, {c: f"{c}/USDT:USDT" for c in COINS})


def variants():
    from tradeagent.learning.experiments import challenger

    base = (yaml.safe_load(cs.settings.resolve(cs.settings.shadow.setups).read_text(encoding="utf-8")) or {})["baseline"]
    return [challenger("h1", base, {"timeframes": ["1h"]}),
            challenger("h1_1r", base, {"timeframes": ["1h"], "exit": {"take_profit_r": 1.0}})]


def replay() -> None:
    from tradeagent.setups.config import register_variants
    from tradeagent.setups.engine import SetupEngine
    from tradeagent.sim.tracker import Tracker

    conn = cs.screen_db()
    s = cs.screen_settings(COINS)
    s.market_data.history_days = HISTORY_DAYS
    vs = variants()
    with conn:
        for table in ("trades", "setups"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM engine_state WHERE key LIKE 'engine:%'")
    register_variants(conn, vs)
    counts = SetupEngine(s, vs, conn).process()
    counts.update(Tracker(s, conn).update())
    print("replayed:", dict(counts), [v.id for v in vs])


def report() -> None:
    conn = cs.screen_db()
    first, last = conn.execute("SELECT min(bar_time), max(bar_time) FROM snapshots WHERE timeframe = '1h'").fetchone()
    days = (last - first) / 86_400_000
    print(f"1h snapshots {time.strftime('%Y-%m-%d', time.gmtime(first / 1000))} .. {time.strftime('%Y-%m-%d', time.gmtime(last / 1000))}"
          f" ({days:.0f} days)\n")
    for v in variants():
        rows = conn.execute("SELECT symbol, entry_time, r_net, exit_reason, exit_time FROM trades WHERE variant_id = ?"
                            " AND taken = 1 AND status = 'closed' ORDER BY entry_time", (v.id,)).fetchall()
        s = cs._stats([(r[0], r[2], r[3]) for r in rows])
        print(f"== {v.name} ({v.id})")
        if not s["n"]:
            print("   no trades\n")
            continue
        mid = rows[len(rows) // 2][1]
        h1 = cs._stats([(r[0], r[2], r[3]) for r in rows if r[1] < mid])
        h2 = cs._stats([(r[0], r[2], r[3]) for r in rows if r[1] >= mid])
        print(f"   all    {cs._fmt(s)}  ({s['n'] / days:.2f} trades a day)")
        print(f"   halves {h1['exp']:+.3f} / {h2['exp']:+.3f}")
        quarter = len(rows) // 4
        print("   quarters " + " / ".join(f"{st.mean(r[2] for r in rows[i * quarter:(i + 1) * quarter]):+.3f}" for i in range(4)))
        positive = 0
        for coin in COINS:
            cs_ = cs._stats([(r[0], r[2], r[3]) for r in rows if r[0] == coin])
            positive += cs_["n"] > 0 and cs_["exp"] > 0
            print(f"   {coin:4} {cs._fmt(cs_)}")
        hold = [(r[4] - r[1]) / 3_600_000 for r in rows if r[4]]
        print(f"   median time in trade {st.median(hold):.0f} h")
        checks = {"100+ trades": s["n"] >= 100, "exp >= +0.15R": s["exp"] >= 0.15, "PF >= 1.3": (s["pf"] or 0) >= 1.3,
                  "both halves > 0": h1["exp"] > 0 and h2["exp"] > 0, "2 of 3 coins > 0": positive >= 2}
        print(f"   {'PASS' if all(checks.values()) else 'no'}: " + ", ".join(f"{k} {'ok' if ok else 'FAIL'}" for k, ok in checks.items()) + "\n")


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "tv":
        asyncio.run(cs.tv_phase(COINS))
        asyncio.run(cs.restore())
    elif action == "candles":
        candles()
    elif action == "replay":
        replay()
    elif action == "report":
        report()
