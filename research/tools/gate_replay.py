r"""The planned design on the agent's own TradingView data since 2026-09-15 (2026-10-23). Research only.

    .venv\Scripts\python -u research\tools\gate_replay.py

Copies into data/replay/journal-gate.db (the live journal is only read):
- the agent's TradingView snapshots of XRP/SOL/ETH (backfill and live) and their Binance candles and funding
- BTC 5m candles and open interest (research journal before 2026-10-20, the live journal after)
- the Fear & Greed Index

Then the agent's engine, tracker and demo account replay from 2026-09-15:
- v0, the current demo strategy, as a check: its replayed trades since the live start against the live ones
- the design (15m, 5m dip entry), and the design with both news filters (the planned new strategy)
Each goes through the demo account at the user's rules ($150, max 5 open, the first position a coin always, max 2 a
coin, opposite skipped, A 3% / B 2%, 12% budget). Prints the go-live gate of the new strategy and compares its trades
with the Python-indicator replay (data/replay/journal-news.db) on the common window.
"""
from __future__ import annotations

import calendar
import statistics as st
import sys
import time
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
START_DAY = sys.argv[1] if len(sys.argv) > 1 else "2026-09-15"  # the first day replayed (YYYY-MM-DD)
START = calendar.timegm(time.strptime(START_DAY, "%Y-%m-%d")) * 1000
CUT = calendar.timegm((2026, 10, 20, 0, 0, 0)) * 1000  # research journal before, live journal from here
COINS = ["XRP", "SOL", "ETH"]
DAY = 86_400_000


def day(ms: int) -> str:
    return time.strftime("%m-%d", time.gmtime(ms / 1000))


def copy(db, live: Path, research: Path) -> None:
    db.execute("ATTACH DATABASE ? AS live", (str(live),))
    db.execute("ATTACH DATABASE ? AS research", (str(research),))
    coins = ",".join(f"'{c}'" for c in COINS)
    with db:
        db.execute(f"INSERT INTO snapshots SELECT * FROM live.snapshots WHERE symbol IN ({coins}) AND bar_time >= ?", (START - 3 * DAY,))
        db.execute(f"INSERT INTO candles SELECT * FROM live.candles WHERE symbol IN ({coins}) AND open_time >= ?", (START - 10 * DAY,))
        db.execute("INSERT OR IGNORE INTO candles SELECT * FROM research.candles WHERE symbol = 'BTC' AND timeframe = '5m'"
                   " AND open_time >= ? AND open_time < ?", (START - 2 * DAY, CUT))
        db.execute("INSERT OR IGNORE INTO candles SELECT * FROM live.candles WHERE symbol = 'BTC' AND timeframe = '5m'"
                   " AND open_time >= ?", (CUT,))
        db.execute(f"INSERT INTO funding SELECT * FROM live.funding WHERE symbol IN ({coins})")
        db.execute("INSERT INTO market_info SELECT * FROM live.market_info")
        db.execute("INSERT INTO fear_greed SELECT * FROM live.fear_greed")
        db.execute(f"INSERT OR IGNORE INTO open_interest SELECT * FROM research.open_interest WHERE symbol IN ({coins})"
                   " AND time >= ? AND time < ?", (START - 2 * DAY, CUT))
        db.execute(f"INSERT OR IGNORE INTO open_interest SELECT * FROM live.open_interest WHERE symbol IN ({coins}) AND time >= ?", (CUT,))
    for table in ("snapshots", "candles", "open_interest", "fear_greed"):
        print(f"   {table}: {db.execute(f'SELECT count(*) FROM main.{table}').fetchone()[0]} rows", flush=True)


def shadow_line(rs: list[float], days: float) -> str:
    if not rs:
        return "no trades"
    wins, losses = [r for r in rs if r > 0], [-r for r in rs if r < 0]
    pf = sum(wins) / sum(losses) if losses else float("inf")
    return (f"{len(rs):3d} trades ({len(rs) / days:.1f} a day), won {len(wins) / len(rs):.0%}, {st.mean(rs):+.3f}R a trade,"
            f" PF {pf:.2f}, total {sum(rs):+.1f}R")


def main() -> None:
    from tradeagent.account.engine import ACCOUNT, AccountEngine, reset_account
    from tradeagent.account.report import account_report
    from tradeagent.config import load_settings
    from tradeagent.journal import connect, migrate
    from tradeagent.market.candles import tf_ms
    from tradeagent.setups.config import SetupParams, Variant, deep_merge, load_variants, register_variants
    from tradeagent.setups.engine import SetupEngine
    from tradeagent.sim.tracker import Tracker
    from tradeagent.tv.catalog import load_catalog

    settings = load_settings(ROOT)
    live = settings.resolve(settings.journal.path)
    path = live.parent / "replay" / ("journal-gate.db" if START_DAY == "2026-09-15" else f"journal-gate-{START_DAY}.db")
    for p in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        p.unlink(missing_ok=True)
    db = connect(path)
    migrate(db)
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)  # the live agent comes first
    print(f"Copying the agent's data since {START_DAY}:", flush=True)
    copy(db, live, ROOT / "data" / "research" / "long4" / "journal.db")

    catalog = load_catalog(settings.resolve(settings.tradingview.catalog))
    current = load_variants(settings.resolve(settings.shadow.setups), catalog)[0]
    base = current.params.model_dump()
    design = deep_merge(base, {"timeframes": ["15m"], "entry": {"mode": "limit", "dip_5m_minutes": 60}})
    new = deep_merge(design, {"filters": {"btc_shock_wait_minutes": 60, "fear_greed_extremes": [20, 80]}})
    variants = [Variant("v0", current.params, "challenger"),
                Variant("design", SetupParams.model_validate(design), "challenger"),
                Variant("new", SetupParams.model_validate(new), "baseline")]
    labels = {"v0": "current demo strategy (v0)", "design": "new design, no news filter", "new": "NEW STRATEGY + both filters"}
    s = settings.model_copy(deep=True)
    s.exchange.symbols = {c: settings.exchange.symbols[c] for c in COINS}
    s.paper_account.symbols = COINS
    register_variants(db, variants)
    with db:
        for c in COINS:
            for tf in ("5m", "15m"):
                for suffix in ("", ":dip"):
                    db.execute("INSERT OR REPLACE INTO engine_state (key, value) VALUES (?, ?)",
                               (f"engine:{c}:{tf}{suffix}", str(START - START % tf_ms(tf) - tf_ms(tf))))
    t0 = time.monotonic()
    SetupEngine(s, variants, db).process()
    Tracker(s, db).update()
    end = db.execute("SELECT max(open_time) FROM candles WHERE timeframe = '1m'").fetchone()[0]
    days = (end - START) / DAY
    print(f"engine and tracker: {time.monotonic() - t0:.0f} s; {days:.1f} days ({day(START)} to {day(end)})\n", flush=True)

    # Check: the replayed v0 against what the live agent recorded since its live snapshots began.
    live_db = connect(live)
    live_from = live_db.execute("SELECT min(bar_time) FROM snapshots WHERE source = 'live'").fetchone()[0]
    key = "SELECT symbol, timeframe, side, trigger_time, taken, status, r_net FROM trades WHERE variant_id = ? AND trigger_time >= ?"
    a = {r[:4]: r[4:] for r in live_db.execute(key, (variants[0].id, live_from))}
    b = {r[:4]: r[4:] for r in db.execute(key, (variants[0].id, live_from))}
    both_keys = a.keys() & b.keys()
    same_taken = sum(a[k][0] == b[k][0] for k in both_keys)
    closed = [k for k in both_keys if a[k][1] == b[k][1] == "closed"]
    same_r = sum(abs((a[k][2] or 0) - (b[k][2] or 0)) < 0.02 for k in closed)
    print(f"CHECK, v0 since {day(live_from)}: live {len(a)} signals, replay {len(b)}, same signal {len(both_keys)};"
          f" same taken/skipped {same_taken}/{len(both_keys)}; same result {same_r}/{len(closed)} closed\n")
    live_db.close()

    print(f"SHADOW (every signal the rules take, since {day(START)}):")
    for v in variants:
        rs = [r[0] for r in db.execute("SELECT r_net FROM trades WHERE variant_id = ? AND taken = 1 AND status = 'closed'"
                                       " ORDER BY exit_time", (v.id,))]
        print(f"   {labels[v.name]:30} {shadow_line(rs, days)}")
        for c in COINS:
            rc = [r[0] for r in db.execute("SELECT r_net FROM trades WHERE variant_id = ? AND symbol = ? AND taken = 1"
                                           " AND status = 'closed'", (v.id, c))]
            print(f"      {c}: {shadow_line(rc, days)}")
    print()

    pa = s.paper_account
    pa.starting_balance, pa.risk_per_trade, pa.risk_tier_a, pa.max_open_risk = 150.0, 0.02, 0.03, 0.12
    pa.max_positions, pa.max_positions_per_coin, pa.allow_opposite, pa.first_position_always = 5, 2, False, True
    pa.daily_loss_stop, pa.leverage_cap, pa.drawdown_brake = None, 10, None
    print(f"DEMO ACCOUNT at the user's rules, $150 from {day(START)}:")
    for v in variants:  # the new strategy last, so its account stays for the gate report
        with db:
            db.execute("UPDATE variants SET role = CASE id WHEN ? THEN 'baseline' ELSE 'challenger' END", (v.id,))
        reset_account(db, s)
        AccountEngine(s, db).process()
        rows = db.execute("SELECT balance_after, entry_time, side FROM account_trades WHERE account = ? AND status = 'closed'"
                          " ORDER BY exit_time, id", (ACCOUNT,)).fetchall()
        bal = peak = 150.0
        dd = 0.0
        for r in rows:
            bal = r[0]
            peak = max(peak, bal)
            dd = max(dd, 1 - bal / peak)
        shorts = sum(r[2] == "short" for r in rows)
        opened = db.execute("SELECT count(*) FROM account_trades WHERE account = ? AND status = 'open'", (ACCOUNT,)).fetchone()[0]
        print(f"   {labels[v.name]:30} {len(rows):3d} closed ({len(rows) / days:.1f} a day; {shorts} shorts), {opened} open |"
              f" $150 -> ${bal:,.2f} ({bal / 150 - 1:+.1%}) | max DD {dd:.1%}")
        for c in COINS:
            pnl = db.execute("SELECT count(*), coalesce(sum(pnl_usd), 0) FROM account_trades WHERE account = ? AND status = 'closed'"
                             " AND symbol = ?", (ACCOUNT, c)).fetchone()
            print(f"      {c}: {pnl[0]} trades, {pnl[1]:+,.2f} USDT")
        if v.name == "new":
            for week in range(int(days // 7) + 1):
                lo, hi = START + week * 7 * DAY, START + (week + 1) * 7 * DAY
                wk = [r for r in rows if lo <= r[1] < hi]
                print(f"      week of {day(lo)}: {len(wk)} trades")
    print()

    with db:
        db.execute("UPDATE account_state SET started_at = ? WHERE account = ?", (START, ACCOUNT))
    report = account_report(db, s)
    print(f"GO-LIVE GATE of the new strategy, counted from {day(START)}:")
    for check in report["gate"]:
        print(f"   [{'x' if check['ok'] else ' '}] {check['name']:48} {check['value']}")
    print()

    # The same strategy on the Python copies of the indicators (the 4-year replay), on the common window.
    news = connect(live.parent / "replay" / "journal-news.db")
    py_id = news.execute("SELECT id FROM variants WHERE params_hash = ?", (variants[2].params_hash,)).fetchone()
    if py_id:
        q = ("SELECT symbol, side, trigger_time, r_net FROM trades WHERE variant_id = ? AND taken = 1 AND status = 'closed'"
             " AND trigger_time >= ? AND trigger_time < ?")
        py = {r[:3]: r[3] for r in news.execute(q, (py_id[0], START, CUT - DAY))}
        tv = {r[:3]: r[3] for r in db.execute(q, (variants[2].id, START, CUT - DAY))}
        common = py.keys() & tv.keys()
        w = (CUT - DAY - START) / DAY
        print(f"PYTHON vs TRADINGVIEW indicators, new strategy, {day(START)} to {day(CUT - DAY)}:")
        print(f"   Python copies: {shadow_line(list(py.values()), w)}")
        print(f"   TradingView:   {shadow_line(list(tv.values()), w)}")
        print(f"   the same trade in both: {len(common)}")
    news.close()
    db.close()


if __name__ == "__main__":
    main()
