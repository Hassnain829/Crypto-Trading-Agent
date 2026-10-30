r"""The user's questions of 2026-10-29: would a wider stop (the price often hit the stop and then the target) or entering
without the 5m dip have done better since 1 Aug? One replay of baseline v4 and its one-change versions on the agent's
own TradingView data, with the agent's engine and tracker, then the demo account (paper_account rules) for each.

    .venv\Scripts\python -u research\tools\stop_dip_replay.py [YYYY-MM-DD]   (default 2026-08-01)

Data as in gate_replay_configured.py (the live journal is only read); the journal is data/replay/journal-stopdip-<date>.db.
Versions (each changes one thing; a stop multiplier keeps the target at the planned price, as stop.multiplier does):
  no_dip       entry.dip_5m_minutes 0 (enter at the open after the signal candle)
  sl_x125/150/200  stop 1.25x / 1.5x / 2x as far, same target price
  sl_x150_tp   stop 1.5x as far and the target 1.5R of the wider stop (take_profit_r 2.25 of the swing)
"""
from __future__ import annotations

import calendar
import statistics as st
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
START_DAY = sys.argv[1] if len(sys.argv) > 1 else "2026-08-01"
START = calendar.timegm(time.strptime(START_DAY, "%Y-%m-%d")) * 1000
CUT = calendar.timegm((2026, 10, 20, 0, 0, 0)) * 1000
SWITCH = calendar.timegm((2026, 10, 24, 1, 30, 0)) * 1000  # the demo trades v4 since then
DAY = 86_400_000
CHANGES = {
    "no_dip": {"entry": {"dip_5m_minutes": 0}},
    "sl_x125": {"stop": {"multiplier": 1.25}},
    "sl_x150": {"stop": {"multiplier": 1.5}},
    "sl_x200": {"stop": {"multiplier": 2.0}},
    "sl_x150_tp": {"stop": {"multiplier": 1.5}, "exit": {"take_profit_r": 2.25}},
}


def stats(rs: list[float]) -> str:
    if not rs:
        return "0 trades"
    wins, losses = [r for r in rs if r > 0], [-r for r in rs if r < 0]
    peak = run = dd = 0.0
    for r in rs:
        run += r
        peak = max(peak, run)
        dd = max(dd, peak - run)
    pf = f"{sum(wins) / sum(losses):.2f}" if losses else "inf"
    return (f"{len(rs)} trades, won {len(wins) / len(rs):.0%}, {st.mean(rs):+.3f}R, total {sum(rs):+.1f}R, PF {pf},"
            f" DD {dd:.1f}R")


def main() -> None:
    import psutil

    from tradeagent.account.preview import live_preview
    from tradeagent.config import load_settings
    from tradeagent.journal import connect, migrate
    from tradeagent.market.candles import tf_ms
    from tradeagent.setups.config import SetupParams, Variant, deep_merge, load_variants, register_variants
    from tradeagent.setups.engine import SetupEngine
    from tradeagent.sim.tracker import Tracker
    from tradeagent.tv.catalog import load_catalog

    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)  # the live agent comes first
    settings = load_settings(ROOT)
    coins = settings.paper_account.symbols or list(settings.exchange.symbols)
    baseline = load_variants(settings.resolve(settings.shadow.setups),
                             load_catalog(settings.resolve(settings.tradingview.catalog)))[0]
    base = baseline.params.model_dump()
    variants = [baseline] + [Variant(name, SetupParams.model_validate(deep_merge(base, change)), "challenger")
                             for name, change in CHANGES.items()]
    live = settings.resolve(settings.journal.path)
    path = live.parent / "replay" / f"journal-stopdip-{START_DAY}.db"
    for p in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        p.unlink(missing_ok=True)
    db = connect(path)
    migrate(db)
    db.execute("ATTACH DATABASE ? AS live", (str(live),))
    db.execute("ATTACH DATABASE ? AS research", (str(ROOT / "data" / "research" / "long4" / "journal.db"),))
    names = ",".join(f"'{c}'" for c in coins)
    with db:
        db.execute(f"INSERT INTO snapshots SELECT * FROM live.snapshots WHERE symbol IN ({names}) AND bar_time >= ?", (START - 3 * DAY,))
        db.execute(f"INSERT INTO candles SELECT * FROM live.candles WHERE symbol IN ({names}) AND open_time >= ?", (START - 45 * DAY,))
        db.execute("INSERT OR IGNORE INTO candles SELECT * FROM research.candles WHERE symbol = 'BTC' AND timeframe = '5m'"
                   " AND open_time >= ? AND open_time < ?", (START - 2 * DAY, CUT))
        db.execute("INSERT OR IGNORE INTO candles SELECT * FROM live.candles WHERE symbol = 'BTC' AND timeframe = '5m'"
                   " AND open_time >= ?", (CUT,))
        db.execute(f"INSERT INTO funding SELECT * FROM live.funding WHERE symbol IN ({names})")
        db.execute("INSERT INTO market_info SELECT * FROM live.market_info")
        db.execute("INSERT INTO fear_greed SELECT * FROM live.fear_greed")
        db.execute(f"INSERT OR IGNORE INTO open_interest SELECT * FROM research.open_interest WHERE symbol IN ({names})"
                   " AND time >= ? AND time < ?", (START - 2 * DAY, CUT))
        db.execute(f"INSERT OR IGNORE INTO open_interest SELECT * FROM live.open_interest WHERE symbol IN ({names}) AND time >= ?", (CUT,))
    db.execute("DETACH DATABASE live")
    db.execute("DETACH DATABASE research")
    s = settings.model_copy(deep=True)
    s.exchange.symbols = {c: settings.exchange.symbols[c] for c in coins}
    register_variants(db, variants)
    with db:
        for c in coins:
            for tf in baseline.params.timeframes:
                for suffix in ("", ":dip"):
                    db.execute("INSERT OR REPLACE INTO engine_state (key, value) VALUES (?, ?)",
                               (f"engine:{c}:{tf}{suffix}", str(START - START % tf_ms(tf) - tf_ms(tf))))
    t0 = time.monotonic()
    SetupEngine(s, variants, db).process()
    Tracker(s, db).update()
    end = db.execute("SELECT max(open_time) FROM candles WHERE timeframe = '1m'").fetchone()[0]
    days = (end - START) / DAY
    mid = START + (end - START) // 2
    out = [f"stop_dip_replay from {START_DAY}: {time.monotonic() - t0:.0f} s; {days:.1f} days to"
           f" {time.strftime('%Y-%m-%d %H:%M', time.gmtime(end / 1000))} UTC; journal {path}", ""]
    for v in variants:
        rows = db.execute("SELECT entry_time, r_net FROM trades WHERE variant_id = ? AND taken = 1 AND status = 'closed'"
                          " ORDER BY exit_time, id", (v.id,)).fetchall()
        rs = [r[1] for r in rows]
        missed = db.execute("SELECT count(*) FROM trades WHERE variant_id = ? AND taken = 1 AND status = 'missed'",
                            (v.id,)).fetchone()[0]
        demo = live_preview(db, settings, rules=settings.paper_account, since=START, variant_id=v.id)
        after = live_preview(db, settings, rules=settings.paper_account, since=SWITCH, variant_id=v.id)
        out.append(f"{v.name} ({v.id})")
        out.append(f"  shadow: {stats(rs)}; {len(rs) / days:.2f} a day; missed {missed}")
        out.append(f"  halves: {stats([r for t, r in rows if t < mid])} | {stats([r for t, r in rows if t >= mid])}")
        out.append(f"  demo from $150: {demo['taken']} trades, ${demo['balance']:.2f} ({demo['return_pct']:+.1f}%),"
                   f" DD {demo['max_drawdown']:.1%}, {demo['expectancy_r'] or 0:+.3f}R; since the switch:"
                   f" {after['taken']} trades, ${after['net_pnl']:+.2f} on $150")
        out.append("")
    text = "\n".join(out)
    print(text)
    (ROOT / "data" / "research" / f"stop_dip_replay_{START_DAY}.txt").write_text(text + "\n", encoding="utf-8")
    db.close()


if __name__ == "__main__":
    main()
