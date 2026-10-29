r"""Replay the CONFIGURED baseline (config/setups.yaml) on the agent's own TradingView data from a date, for the go-live
gate (2026-10-24). Then `tradeagent import-replay <journal>` makes the gate count those trades (goal.count_from).

    .venv\Scripts\python -u research\tools\gate_replay_configured.py [YYYY-MM-DD]   (default 2026-08-01)

Copies the live journal's TradingView snapshots (backfill and live), candles, funding, open interest and Fear & Greed,
plus BTC 5m candles (the research journal before 2026-10-20), into data/replay/journal-gate-v4-<date>.db, and runs the
agent's engine and tracker with the live settings (quality reasons included). The live journal is only read.
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
DAY = 86_400_000


def main() -> None:
    import psutil

    from tradeagent.config import load_settings
    from tradeagent.journal import connect, migrate
    from tradeagent.market.candles import tf_ms
    from tradeagent.setups.config import load_variants, register_variants
    from tradeagent.setups.engine import SetupEngine
    from tradeagent.sim.tracker import Tracker
    from tradeagent.tv.catalog import load_catalog

    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)  # the live agent comes first
    settings = load_settings(ROOT)
    coins = settings.paper_account.symbols or list(settings.exchange.symbols)
    baseline = load_variants(settings.resolve(settings.shadow.setups),
                             load_catalog(settings.resolve(settings.tradingview.catalog)))[0]
    live = settings.resolve(settings.journal.path)
    path = live.parent / "replay" / f"journal-gate-v4-{START_DAY}.db"
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
    s = settings.model_copy(deep=True)
    s.exchange.symbols = {c: settings.exchange.symbols[c] for c in coins}
    register_variants(db, [baseline])
    with db:
        for c in coins:
            for tf in baseline.params.timeframes:
                for suffix in ("", ":dip"):
                    db.execute("INSERT OR REPLACE INTO engine_state (key, value) VALUES (?, ?)",
                               (f"engine:{c}:{tf}{suffix}", str(START - START % tf_ms(tf) - tf_ms(tf))))
    t0 = time.monotonic()
    SetupEngine(s, [baseline], db).process()
    Tracker(s, db).update()
    rs = [r[0] for r in db.execute("SELECT r_net FROM trades WHERE variant_id = ? AND taken = 1 AND status = 'closed'",
                                   (baseline.id,))]
    skipped = db.execute("SELECT count(*) FROM trades WHERE variant_id = ? AND reason LIKE '%btc_against%'", (baseline.id,)).fetchone()[0]
    quality_a = db.execute("SELECT count(*) FROM trades WHERE variant_id = ? AND taken = 1 AND status = 'closed'"
                           " AND json_extract(context_json, '$.quality') = 'A'", (baseline.id,)).fetchone()[0]
    end = db.execute("SELECT max(open_time) FROM candles WHERE timeframe = '1m'").fetchone()[0]
    days = (end - START) / DAY
    wins = [r for r in rs if r > 0]
    losses = [-r for r in rs if r < 0]
    print(f"{baseline.id} from {START_DAY}: {time.monotonic() - t0:.0f} s; {len(rs)} closed trades ({len(rs) / days:.2f} a day),"
          f" won {len(wins) / len(rs):.0%}, {st.mean(rs):+.3f}R, PF {sum(wins) / sum(losses):.2f}; quality A {quality_a};"
          f" skipped against BTC {skipped}")
    print(f"journal: {path}")
    db.close()


if __name__ == "__main__":
    main()
