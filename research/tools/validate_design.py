r"""Check the implemented design with the agent's own code on 4 years (2026-10-21): the SetupEngine with the new entry
option (15m only, limit entry after a 5m dip, at most 60 minutes) and the AccountEngine with the new rules
(max 5 open, the first position per coin always allowed, max 2 per coin, opposite signals skipped, A 3% / B 2%,
12% open-risk budget), on a copy of the 4-year research journal. Expected from the research: about +1,357%
over 4 years with a max drawdown near 62%.

    .venv\Scripts\python -u research\tools\validate_design.py
"""
from __future__ import annotations

import importlib.util
import shutil
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("long_data", HERE / "long_data.py")
ld = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ld)
ld.use_4y()

from tradeagent.account.engine import AccountEngine, reset_account  # noqa: E402
from tradeagent.journal import connect, migrate  # noqa: E402
from tradeagent.setups.config import SetupParams, Variant, deep_merge, load_variants, register_variants  # noqa: E402
from tradeagent.setups.engine import SetupEngine  # noqa: E402
from tradeagent.sim.tracker import Tracker  # noqa: E402
from tradeagent.tv.catalog import load_catalog  # noqa: E402

COPY = ROOT / "data" / "research" / "long4" / "validate.db"
COINS = ["XRP", "SOL", "ETH"]


def main() -> None:
    if not COPY.exists():
        src = sqlite3.connect(f"file:{ld.DB}?mode=ro", uri=True)
        dst = sqlite3.connect(COPY)
        src.backup(dst)
        src.close()
        dst.close()
        print("copied the 4-year journal", flush=True)
    conn = connect(COPY)
    migrate(conn)
    with conn:
        for table in ("trades", "setups", "account_trades", "account_state", "variants"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM engine_state")
        conn.execute("DELETE FROM snapshots WHERE timeframe != '15m' OR symbol NOT IN ('XRP', 'SOL', 'ETH')")
    s = ld.long_settings(COINS)
    catalog = load_catalog(ld.settings.resolve(ld.settings.tradingview.catalog))
    base = load_variants(ld.settings.resolve(ld.settings.shadow.setups), catalog)[0]
    params = SetupParams.model_validate(deep_merge(base.params.model_dump(),
                                                   {"timeframes": ["15m"], "entry": {"mode": "limit", "dip_5m_minutes": 60}}))
    design = Variant("v0", params, "baseline")
    register_variants(conn, [design])
    t0 = time.monotonic()
    print("engine:", dict(SetupEngine(s, [design], conn).process()), f"{time.monotonic() - t0:.0f} s", flush=True)
    print("tracker:", dict(Tracker(s, conn).update()), f"{time.monotonic() - t0:.0f} s", flush=True)

    pa = s.paper_account
    pa.starting_balance, pa.risk_per_trade, pa.risk_tier_a, pa.max_open_risk = 150.0, 0.02, 0.03, 0.12
    pa.max_positions, pa.max_positions_per_coin, pa.allow_opposite, pa.first_position_always = 5, 2, False, True
    pa.daily_loss_stop, pa.symbols, pa.leverage_cap = None, COINS, 20
    for brake in (None, 0.10):
        pa.drawdown_brake = brake
        reset_account(conn, s)
        with conn:  # the account follows the trades from the first one (no forward start)
            conn.execute("DELETE FROM engine_state")  # no live horizon in a replay: every signal is already known
        AccountEngine(s, conn).process()
        rows = conn.execute("SELECT entry_time, balance_after FROM account_trades WHERE account = 'paper' AND status = 'closed'"
                            " ORDER BY exit_time, id").fetchall()
        rejected = conn.execute("SELECT reject_reason, count(*) FROM account_trades WHERE account = 'paper'"
                                " AND status = 'rejected' GROUP BY 1 ORDER BY 2 DESC").fetchall()
        bal = peak = 150.0
        dd = 0.0
        for r in rows:
            bal = r[1]
            peak = max(peak, bal)
            dd = max(dd, 1 - bal / peak)
        print(f"\nbrake {brake}: {len(rows)} closed | $150 -> ${bal:,.0f} ({bal / 150 - 1:+.0%}) max DD {dd:.1%}")
        for reason, n in rejected[:6]:
            print(f"   skipped {n:5d}: {reason}")
    conn.close()


if __name__ == "__main__":
    main()
