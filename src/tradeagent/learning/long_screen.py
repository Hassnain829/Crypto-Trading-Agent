"""Long-history screen and backtest: rules replayed on years of research data with the agent's own engine.

The research journal (settings `learning.long_history`, built by research/tools/long_data.py and long_backtest.py)
holds Binance candles, funding, open interest and indicator snapshots since 2022-10. Its indicator values were
computed in Python from the open Pine code of the AGENT charts' studies (Q-Trend, Klinger, Squeeze, Zero Lag) for
research only (approved by the user on 2026-10-20), and checked against TradingView's own history: Klinger, Squeeze
and Zero Lag match; Q-Trend gives about 80% of its signals on the same bar, as two TradingView charts with different
history lengths do. The closed-source Trendline is missing there, so quality A comes from open interest only.
These values only judge rules; the agent never trades on them.

The research journal is only read: every run writes into a small overlay journal (data/replay/journal-<name>.db)
whose candles, snapshots, funding, market info and open interest are temporary views on it.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from tradeagent.config import Settings, SymbolConfig
from tradeagent.journal import connect, migrate
from tradeagent.journal.db import now_ms
from tradeagent.market.candles import tf_ms
from tradeagent.learning import experiments as ex
from tradeagent.setups.config import BASELINE_NAME, SetupParams, Variant, register_variants
from tradeagent.setups.engine import SetupEngine
from tradeagent.setups.report import summarize
from tradeagent.sim.tracker import Tracker

log = logging.getLogger("tradeagent.learning")

SHARED = ("candles", "snapshots", "funding", "market_info", "open_interest", "fear_greed")


def source(settings: Settings) -> Path | None:
    """The long research journal, or None when it is not configured or not on this machine."""
    if not settings.learning.long_history:
        return None
    path = settings.resolve(settings.learning.long_history)
    return path if path.exists() else None


def overlay(settings: Settings, name: str, resume: bool = False) -> sqlite3.Connection:
    """A fresh journal whose market data are views on the long research journal (which is never written); with
    `resume`, the existing one is kept, so an interrupted replay continues where it stopped."""
    src = source(settings)
    if src is None:
        raise RuntimeError(f"no long research history at {settings.learning.long_history}")
    path = settings.resolve(settings.journal.path).parent / "replay" / f"journal-{name}.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    for p in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if not resume:
            p.unlink(missing_ok=True)
    conn = connect(path)
    migrate(conn)
    conn.execute("ATTACH DATABASE ? AS long", (str(src),))
    for table in SHARED:
        conn.execute(f"CREATE TEMP VIEW {table} AS SELECT * FROM long.{table}")
    return conn


def start_time(conn: sqlite3.Connection, settings: Settings, coin: str) -> int | None:
    """Where the replay starts: the newest `long_history_years` of the research history (None = from its start)."""
    years = settings.learning.long_history_years
    if not years:
        return None
    end = conn.execute("SELECT max(open_time) FROM long.candles WHERE symbol = ? AND timeframe = '15m'", (coin,)).fetchone()[0]
    return None if end is None else (end - years * 365 * 86_400_000) // 3_600_000 * 3_600_000


def replay(settings: Settings, variants: list[Variant], name: str, coins: list[str] | None = None,
           resume: bool = False) -> tuple[sqlite3.Connection, list[str], Settings]:
    """Run the setup engine and the tracker over the long history (its newest `long_history_years`) for these
    variants, on these coins (default: the demo's coins). With `resume`, an interrupted replay of the same variants
    continues from its saved engine state (the engine and the tracker save every candle); other variants start over."""
    conn = overlay(settings, name, resume)
    if resume:
        known = {r[0] for r in conn.execute("SELECT id FROM variants")}
        if not {v.id for v in variants} <= known:
            log.info("replay %s: not the same variants; starting over", name)
            conn.close()
            conn = overlay(settings, name)
    wanted = coins or ex.coins(settings)
    coins = [c for c in wanted if conn.execute("SELECT 1 FROM long.candles WHERE symbol = ? LIMIT 1", (c,)).fetchone()]
    if not coins:
        conn.close()
        raise RuntimeError(f"the long history has none of the coins {wanted}")
    s = settings.model_copy(deep=True)
    s.exchange.symbols = {c: settings.exchange.symbols.get(c) or SymbolConfig(
        tradingview=f"BINANCE:{c}USDT.P", markets={"binance-usdm": f"{c}/USDT:USDT"}) for c in coins}
    s.paper_account.symbols = coins
    register_variants(conn, variants)
    start = start_time(conn, settings, coins[0])
    if start is not None:  # the engine starts at the window: older candles only warm up the indicators
        timeframes = {tf for v in variants for tf in v.params.timeframes}
        with conn:
            for c in coins:
                for tf in timeframes:
                    for suffix in ("", ":dip"):
                        conn.execute("INSERT OR IGNORE INTO engine_state (key, value) VALUES (?, ?)",
                                     (f"engine:{c}:{tf}{suffix}", str(start - start % tf_ms(tf) - tf_ms(tf))))
    SetupEngine(s, variants, conn).process()
    Tracker(s, conn).update()
    return conn, coins, s


def _stats(conn: sqlite3.Connection, variant_id: str, coins: list[str], start: int, end: int) -> dict[str, Any]:
    return ex.window_stats(conn, variant_id, start, coins, end)


def compare(settings: Settings, conn: sqlite3.Connection, changes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The long-history counterpart of screen.history_compare: the baseline and every challenger {name: override},
    judged by the same rules (overall, and not worse in either half of the baseline's trades)."""
    from tradeagent.learning.screen import MIN_HALF_TRADES, judge

    base = ex.effective_baseline(settings, conn)
    baseline = Variant(BASELINE_NAME, SetupParams.model_validate(base), "baseline")
    variants = [baseline] + [ex.challenger(name, base, change) for name, change in changes.items()]
    started = time.monotonic()
    db, coins, _ = replay(settings, variants, "long-screen")
    try:
        times = [r[0] for r in db.execute(
            f"SELECT entry_time FROM trades WHERE variant_id = ? AND taken = 1 AND status = 'closed'"
            f" AND symbol IN ({','.join('?' * len(coins))}) ORDER BY entry_time", (baseline.id, *coins))]
        if len(times) < 2 * MIN_HALF_TRADES:
            raise RuntimeError(f"the long history has only {len(times)} baseline trades on {coins}")
        start, end, mid = times[0], times[-1] + 1, times[len(times) // 2]
        out = {}
        for v in variants[1:]:
            stats = {
                "all": {"challenger": _stats(db, v.id, coins, start, end), "baseline": _stats(db, baseline.id, coins, start, end)},
                "halves": [{"challenger": _stats(db, v.id, coins, a, b), "baseline": _stats(db, baseline.id, coins, a, b)}
                           for a, b in ((start, mid), (mid, end))],
            }
            passed, why = judge(stats, settings)
            out[v.name] = {"passed": passed, "why": why or "beat the baseline over the long history and in both halves",
                           "period": [start, end], "split": mid, "coins": coins, "variant_id": v.id, **stats,
                           "seconds": round(time.monotonic() - started)}
        return out
    finally:
        db.close()


def _account(db: sqlite3.Connection, s: Settings, variant_id: str, start: int, mid: int) -> dict[str, Any]:
    """The demo account (today's demo rules, its starting balance) on this variant's trades: the whole long history
    and each half on its own."""
    from tradeagent.account.engine import ACCOUNT, AccountEngine, reset_account

    with db:
        db.execute("UPDATE variants SET role = CASE id WHEN ? THEN 'baseline' ELSE 'challenger' END", (variant_id,))
        db.execute("DELETE FROM engine_state")  # every signal is already known: no live horizon in a replay
    out = {}
    for label, lo, hi in (("all", 0, 2**62), ("half1", 0, mid), ("half2", mid, 2**62)):
        reset_account(db, s)
        with db:  # outside the window: hidden from the account for this run
            db.execute("UPDATE trades SET taken = -taken WHERE variant_id = ? AND taken > 0 AND (entry_time < ? OR entry_time >= ?)",
                       (variant_id, lo, hi))
        try:
            AccountEngine(s, db).process()
        finally:
            with db:
                db.execute("UPDATE trades SET taken = -taken WHERE variant_id = ? AND taken < 0", (variant_id,))
        rows = [r[0] for r in db.execute("SELECT balance_after FROM account_trades WHERE account = ? AND status = 'closed'"
                                         " ORDER BY exit_time, id", (ACCOUNT,))]
        start_balance = s.paper_account.starting_balance
        bal = peak = start_balance
        dd = 0.0
        for b in rows:
            bal = b
            peak = max(peak, bal)
            dd = max(dd, 1 - bal / peak)
        out[label] = {"trades": len(rows), "balance": bal, "return_pct": (bal / start_balance - 1) * 100, "max_drawdown": dd}
    return out


def backtest(settings: Settings, conn: sqlite3.Connection, variants: list[Variant], resume: bool = False) -> list[str]:
    """Replay these variants on the long history and store each one's result (trades in R, both time halves, and the
    demo account at the demo rules) in long_results, for the leaderboard. `resume`: see replay."""
    started = time.monotonic()
    db, coins, s = replay(settings, variants, "long-board", settings.learning.long_backtest_coins, resume)
    lines = []
    try:
        span = db.execute(f"SELECT min(entry_time), max(entry_time) FROM trades WHERE taken = 1 AND status = 'closed'"
                          f" AND symbol IN ({','.join('?' * len(coins))})", coins).fetchone()
        if span[0] is None:
            return ["no closed trades on the long history"]
        start, end = span[0], span[1] + 1
        mid = start + (end - start) // 2
        rules = s.paper_account.model_dump()
        for v in variants:
            result = {
                "name": v.name, "coins": coins, "period": [start, end], "split": mid,
                "all": _stats(db, v.id, coins, start, end),
                "halves": [_stats(db, v.id, coins, start, mid), _stats(db, v.id, coins, mid, end)],
                "account": _account(db, s, v.id, start, mid), "rules": rules,
                "seconds": round(time.monotonic() - started),
            }
            with conn:
                conn.execute("INSERT OR REPLACE INTO long_results (variant_id, params_hash, period_from, period_to, result_json,"
                             " created_at) VALUES (?, ?, ?, ?, ?, ?)",
                             (v.id, v.params_hash, start, end, json.dumps(result), now_ms()))
            a = result["all"]
            lines.append(f"{v.id}: {a['trades']} trades, {a['expectancy_r'] or 0:+.3f}R a trade; demo"
                         f" {result['account']['all']['return_pct']:+.0f}% (max DD {result['account']['all']['max_drawdown']:.0%})")
    finally:
        db.close()
    return lines


def missing(conn: sqlite3.Connection, variants: list[Variant]) -> list[Variant]:
    """Active variants without a stored long-history result."""
    have = {r[0] for r in conn.execute("SELECT variant_id FROM long_results")}
    return [v for v in variants if v.id not in have]
