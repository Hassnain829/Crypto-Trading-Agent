"""Replay the stored TradingView signals with another venue's prices, to see whether the edge survives there.

The journal is copied to data/replay/journal-<venue>.db; the copy gets that venue's market data and every
shadow trade is simulated again from the same snapshots. The real journal is only read. Results of both
venues are compared over the same period: R per trade per variant, and the money a demo account would have
made with the venue's contract sizes.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from tradeagent.account.preview import live_preview
from tradeagent.config import Settings, load_settings
from tradeagent.journal import connect, migrate
from tradeagent.journal.db import now_ms
from tradeagent.logging_setup import setup_logging
from tradeagent.market.candles import ensure_venue
from tradeagent.market.sync import sync_all
from tradeagent.setups.config import load_variants, register_variants
from tradeagent.setups.engine import SetupEngine
from tradeagent.setups.report import summarize
from tradeagent.sim.tracker import Tracker
from tradeagent.tv.catalog import load_catalog
from tradeagent.venues import MarketData, get_venue

COMPARE = ("v0", "tf_15m", "session_13_21", "video_original")  # variant name prefixes shown (v0 = the baseline)


def _utc(ms: int | None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000)) if ms else "-"


def copy_journal(settings: Settings, venue: str) -> sqlite3.Connection:
    src_path = settings.resolve(settings.journal.path)
    out = src_path.parent / "replay" / f"journal-{venue}.db"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    dst = sqlite3.connect(out)
    src.backup(dst)
    src.close()
    dst.close()
    conn = connect(out)
    migrate(conn)
    return conn


def reset_shadow(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute("DELETE FROM trades WHERE book = 'exploration'")
        conn.execute("DELETE FROM setups")
        conn.execute("DELETE FROM engine_state WHERE key LIKE 'engine:%'")
        conn.execute("DELETE FROM account_trades WHERE account = 'paper'")
        conn.execute("DELETE FROM account_state WHERE account = 'paper'")


def variant_stats(conn: sqlite3.Connection, ids: list[str], since: int) -> dict[str, dict[str, Any]]:
    out = {}
    for vid in ids:
        r = [row[0] for row in conn.execute(
            "SELECT r_net FROM trades WHERE book = 'exploration' AND variant_id = ? AND taken = 1 AND status = 'closed'"
            " AND entry_time >= ? ORDER BY exit_time", (vid, since))]
        stats = summarize(r)
        stats["missed"] = conn.execute(
            "SELECT count(*) FROM trades WHERE book = 'exploration' AND variant_id = ? AND taken = 1 AND status = 'missed'"
            " AND entry_time >= ?", (vid, since)).fetchone()[0]
        out[vid] = stats
    return out


def first_candle(conn: sqlite3.Connection) -> int:
    """The newest of the coins' first 1m candles: the period every coin has data for."""
    return max(row[0] for row in conn.execute("SELECT min(open_time) FROM candles WHERE timeframe = '1m' GROUP BY symbol"))


def _fmt(s: dict[str, Any]) -> str:
    if not s["trades"]:
        return "no closed trades"
    pf = f"{s['profit_factor']:.2f}" if s["profit_factor"] else "-"
    return (f"{s['trades']:4} trades  win {s['win_rate']:.0%}  {s['expectancy_r']:+.3f}R/trade  total {s['total_r']:+7.1f}R"
            f"  PF {pf}  missed {s['missed']}")


def _money(p: dict[str, Any]) -> str:
    skipped = ", ".join(f"{n} {why[:60]}" for why, n in list(p["skipped"].items())[:2]) or "none"
    return (f"${p['start_balance']:,.0f} -> ${p['balance']:,.0f} ({p['return_pct']:+.1f}%), {p['taken']} trades, "
            f"max drawdown {p['max_drawdown']:.1%}; skipped: {skipped}")


def venue_replay(venue_id: str, balances: list[float]) -> int:
    settings = load_settings()
    setup_logging(settings, console=False)
    venue = get_venue(venue_id)
    replay_settings = settings.model_copy(deep=True)
    replay_settings.exchange.venue = venue_id
    missing = [coin for coin, cfg in settings.exchange.symbols.items() if venue_id not in cfg.markets]
    if missing:
        print(f"config/settings.yaml has no {venue_id} market for {missing}")
        return 2
    print(f"Replay on {venue.label}: {venue.who}")
    print(f"Fees: {venue.fee_note or 'see the exchange'}; the simulation uses costs maker {settings.costs.maker_fee:.3%},"
          f" taker {settings.costs.taker_fee:.3%}, slippage {settings.costs.slippage:.3%}.")

    original = connect(settings.resolve(settings.journal.path))
    conn = copy_journal(settings, venue_id)
    try:
        started = time.monotonic()
        print(f"Downloading {settings.market_data.history_days} days of {venue_id} candles (a few minutes)...", flush=True)
        ensure_venue(conn, venue_id)
        sync_all(replay_settings, conn, MarketData(venue), now_ms(), with_info=True)
        info = conn.execute("SELECT symbol, contract_size, step_size, min_qty FROM market_info ORDER BY symbol").fetchall()
        print(f"  done in {time.monotonic() - started:.0f} s; contracts: "
              + ", ".join(f"{r['symbol']} {r['contract_size']:g} coins (min {r['min_qty'] or r['step_size']:g})" for r in info))

        print("Replaying every stored signal with these prices...", flush=True)
        started = time.monotonic()
        reset_shadow(conn)
        catalog = load_catalog(settings.resolve(settings.tradingview.catalog))
        variants = load_variants(settings.resolve(settings.shadow.setups), catalog)
        register_variants(conn, variants)
        counts = SetupEngine(replay_settings, variants, conn).process()
        counts.update(Tracker(replay_settings, conn).update())
        print(f"  done in {time.monotonic() - started:.0f} s: {counts['trades_taken']} taken, "
              f"{counts['trades_counterfactual']} filtered, {counts['no_entry_candle']} without an entry candle")

        since = max(first_candle(conn), first_candle(original))
        ids = [v.id for v in variants if v.id.split("-")[0] in COMPARE]
        before, after = variant_stats(original, ids, since), variant_stats(conn, ids, since)
        print(f"\nSame signals, same period (entries from {_utc(since)}):")
        for vid in ids:
            name = "v2 baseline" if vid == variants[0].id else vid.rsplit("-", 1)[0]
            print(f"  {name}")
            print(f"    binance-usdm  {_fmt(before[vid])}")
            print(f"    {venue_id:<13} {_fmt(after[vid])}")
        print("\nDemo account with every baseline signal (no limits), 2% risk, the venue's contract sizes:")
        for balance in balances:
            rules = settings.paper_account.model_copy(update={"starting_balance": balance})
            print(f"  binance-usdm  {_money(live_preview(original, settings, rules, since))}")
            print(f"  {venue_id:<13} {_money(live_preview(conn, replay_settings, rules, since))}")
        print(f"\nThe replay journal is kept at data/replay/journal-{venue_id}.db")
    finally:
        conn.close()
        original.close()
    return 0
