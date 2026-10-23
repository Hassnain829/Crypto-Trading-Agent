r"""Would the current strategy work on 1m or 3m charts? (the user, 2026-10-21). Research only.

The newest year of XRP/SOL/ETH from the 4-year research journal: 1m candles (3m built from them), Python copies of
Q-Trend, Klinger and Squeeze on both charts, then the agent's own engine with the baseline rules on 1m and on 3m.
Signals the 1.5% minimum stop skips are still simulated as counterfactuals, so their result is shown too. The same
year's 5m and 15m baseline trades of the 4-year journal are the comparison.

    .venv\Scripts\python -u research\tools\lowtf_test.py data
    .venv\Scripts\python -u research\tools\lowtf_test.py run
"""
from __future__ import annotations

import importlib.util
import sqlite3
import statistics as st
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))
import long_indicators as li  # noqa: E402

from tradeagent.config import SymbolConfig, load_settings  # noqa: E402
from tradeagent.journal import connect, migrate  # noqa: E402
from tradeagent.tv.snapshots import Snapshot, store_snapshots  # noqa: E402

LONG4 = ROOT / "data" / "research" / "long4" / "journal.db"
DB = ROOT / "data" / "research" / "lowtf" / "journal.db"
COINS = ["XRP", "SOL", "ETH"]
YEAR = 365 * 86_400_000
WARM = 3 * 86_400_000  # extra days before the year for indicator warm-up and the stop lookback
M1, M3 = 60_000, 180_000
settings = load_settings(ROOT)


def window() -> tuple[int, int]:
    src = sqlite3.connect(f"file:{LONG4}?mode=ro", uri=True)
    end = src.execute("SELECT max(open_time) FROM candles WHERE symbol = 'XRP' AND timeframe = '1m'").fetchone()[0]
    src.close()
    end = end // 86_400_000 * 86_400_000
    return end - YEAR, end


def data() -> None:
    start, end = window()
    DB.parent.mkdir(parents=True, exist_ok=True)
    DB.unlink(missing_ok=True)
    conn = connect(DB)
    migrate(conn)
    conn.execute("ATTACH DATABASE ? AS src", (str(LONG4),))
    with conn:
        conn.execute("INSERT INTO candles SELECT * FROM src.candles WHERE symbol IN ('XRP', 'SOL', 'ETH') AND timeframe = '1m'"
                     " AND open_time >= ? AND open_time < ?", (start - WARM, end))
        conn.execute("INSERT INTO funding SELECT * FROM src.funding WHERE symbol IN ('XRP', 'SOL', 'ETH')")
        conn.execute("INSERT INTO market_info SELECT * FROM src.market_info WHERE symbol IN ('XRP', 'SOL', 'ETH')")
    conn.commit()
    conn.execute("DETACH DATABASE src")
    for coin in COINS:
        rows1 = conn.execute("SELECT open_time, open, high, low, close, volume FROM candles WHERE symbol = ? AND timeframe = '1m'"
                             " ORDER BY open_time", (coin,)).fetchall()
        groups: dict[int, list] = {}
        for t, o, h, l, c, v in rows1:
            k = t // M3 * M3
            g = groups.get(k)
            if g is None:
                groups[k] = [k, o, h, l, c, v, 1]
            else:
                g[2], g[3], g[4], g[5], g[6] = max(g[2], h), min(g[3], l), c, g[5] + v, g[6] + 1
        rows3 = [tuple(g[:6]) for _, g in sorted(groups.items()) if g[6] == 3]
        with conn:
            conn.executemany("INSERT OR REPLACE INTO candles VALUES (?, '3m', ?, ?, ?, ?, ?, ?)", [(coin, *r) for r in rows3])
        for tf, rows, step in (("1m", rows1, M1), ("3m", rows3, M3)):
            t0 = time.monotonic()
            values = li.compute(rows, with_zerolag=False)
            batch = []
            for r, v in list(zip(rows, values))[1000:]:
                batch.append(Snapshot(coin, tf, r[0], 6, r[0] + step + 5_000, values=v, ohlcv=list(r[1:6]), source="backfill"))
                if len(batch) == 20_000:
                    store_snapshots(conn, batch)
                    batch = []
            store_snapshots(conn, batch)
            conn.commit()
            print(f"{coin} {tf}: {len(rows) - 1000} snapshots in {time.monotonic() - t0:.0f} s", flush=True)
    conn.close()


def run() -> None:
    from tradeagent.setups.config import SetupParams, Variant, deep_merge, load_variants, register_variants
    from tradeagent.setups.engine import SetupEngine
    from tradeagent.sim.tracker import Tracker
    from tradeagent.tv.catalog import load_catalog

    start, end = window()
    conn = connect(DB)
    migrate(conn)
    catalog = load_catalog(settings.resolve(settings.tradingview.catalog))
    base = load_variants(settings.resolve(settings.shadow.setups), catalog)[0].params.model_dump()
    variants = [Variant("tf1m", SetupParams.model_validate(deep_merge(base, {"timeframes": ["1m"]})), "baseline"),
                Variant("tf3m", SetupParams.model_validate(deep_merge(base, {"timeframes": ["3m"]})), "challenger")]
    s = settings.model_copy(deep=True)
    s.exchange.symbols = {c: SymbolConfig(tradingview=f"BINANCE:{c}USDT.P", markets={"binance-usdm": f"{c}/USDT:USDT"})
                          for c in COINS}
    s.journal.path = str(DB)
    with conn:
        for table in ("trades", "setups", "engine_state"):
            conn.execute(f"DELETE FROM {table}")
        for c in COINS:  # start at the year (older candles only warm up the indicators and the stop)
            for tf, step in (("1m", M1), ("3m", M3)):
                conn.execute("INSERT INTO engine_state (key, value) VALUES (?, ?)", (f"engine:{c}:{tf}", str(start - step)))
    register_variants(conn, variants)
    t0 = time.monotonic()
    print("engine:", dict(SetupEngine(s, variants, conn).process()), f"{time.monotonic() - t0:.0f} s", flush=True)
    print("tracker:", dict(Tracker(s, conn).update()), f"{time.monotonic() - t0:.0f} s", flush=True)

    def line(name: str, rs: list[float]) -> str:
        if not rs:
            return f"   {name:48} no trades"
        w, l = sum(x for x in rs if x > 0), -sum(x for x in rs if x < 0)
        return (f"   {name:48} {len(rs):6d} trades ({len(rs) / 365:5.1f} a day) won {sum(x > 0 for x in rs) / len(rs):4.0%}"
                f" {st.mean(rs):+.3f}R a trade PF {w / l if l else 0:.2f} total {sum(rs):+8.1f}R")

    print(f"\n== {time.strftime('%Y-%m-%d', time.gmtime(start / 1000))} .. {time.strftime('%Y-%m-%d', time.gmtime(end / 1000))},"
          " XRP SOL ETH, the baseline rules (stop at least 1.5%, limit entry, 1.5R)")
    for v in variants:
        q = ("SELECT r_net, fees_r + slippage_r FROM trades WHERE variant_id = ? AND status = 'closed' AND taken = ?"
             " AND entry_time >= ? AND entry_time < ?")
        taken = conn.execute(q, (v.id, 1, start, end)).fetchall()
        skipped = conn.execute(q, (v.id, 0, start, end)).fetchall()
        print(line(f"{v.name[2:]} taken (stop >= 1.5%)", [r[0] for r in taken]))
        print(line(f"{v.name[2:]} skipped by the 1.5% minimum stop, if taken", [r[0] for r in skipped]))
        costs = [r[1] for r in taken + skipped if r[1] is not None]
        if costs:
            print(f"   {'':48} fees and slippage: {st.mean(costs):.3f}R a trade on average")
    ref = sqlite3.connect(f"file:{LONG4}?mode=ro", uri=True)
    vid = ref.execute("SELECT id FROM variants WHERE role = 'baseline'").fetchone()[0]
    for tf in ("5m", "15m"):
        taken = [r[0] for r in ref.execute(
            "SELECT r_net FROM trades WHERE variant_id = ? AND timeframe = ? AND status = 'closed' AND taken = 1 AND entry_time >= ?"
            " AND entry_time < ? AND symbol IN ('XRP', 'SOL', 'ETH')", (vid, tf, start, end))]
        print(line(f"{tf} taken (same year, for comparison)", taken))
    conn.close()


if __name__ == "__main__":
    {"data": data, "run": run}[sys.argv[1]]()
