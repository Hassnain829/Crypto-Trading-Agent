r"""The two news filters with the agent's own engine and account on 4 years (2026-10-21). Research only.

    .venv\Scripts\python -u research\tools\validate_news.py [--resume]

Puts the Fear & Greed history (data/research/fear_greed.json) into the 4-year research journal, then replays on
XRP/SOL/ETH: the planned design (15m, 5m dip entry), the design + "wait 60 min after a BTC 2% 5m move", the design +
"no trade when Fear & Greed is below 20 or above 80", and the design with both; each through the demo account with
the user's rules (max 5 open, the first position per coin always, max 2 a coin, opposite skipped, A 3% / B 2%,
12% budget, 10x).
"""
from __future__ import annotations

import importlib.util
import json
import statistics as st
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("long_data", HERE / "long_data.py")
ld = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ld)
SPLIT = 1727740800000  # 2024-10-01


def main() -> None:
    from tradeagent.account.engine import ACCOUNT, AccountEngine, reset_account
    from tradeagent.journal import connect, migrate
    from tradeagent.learning.long_screen import replay
    from tradeagent.market.fear_greed import parse
    from tradeagent.setups.config import SetupParams, Variant, deep_merge, load_variants
    from tradeagent.tv.catalog import load_catalog

    long4 = connect(ld.DB4)
    migrate(long4)
    rows = parse((ROOT / "data" / "research" / "fear_greed.json").read_text(encoding="utf-8"))
    with long4:
        long4.executemany("INSERT OR REPLACE INTO fear_greed (time, value, classification) VALUES (?, ?, ?)", rows)
    long4.close()
    print(f"Fear & Greed: {len(rows)} days in the research journal", flush=True)

    settings = ld.settings.model_copy(deep=True)
    settings.learning.long_history = str(ld.DB4)
    settings.learning.long_history_years = None
    catalog = load_catalog(settings.resolve(settings.tradingview.catalog))
    base = load_variants(settings.resolve(settings.shadow.setups), catalog)[0].params.model_dump()
    design = {"timeframes": ["15m"], "entry": {"mode": "limit", "dip_5m_minutes": 60}}
    btc = {"filters": {"btc_shock_wait_minutes": 60}}
    fng = {"filters": {"fear_greed_extremes": [20, 80]}}
    both = {"filters": {"btc_shock_wait_minutes": 60, "fear_greed_extremes": [20, 80]}}
    variants = [Variant("v0", SetupParams.model_validate(deep_merge(base, design)), "baseline")] + [
        Variant(name, SetupParams.model_validate(deep_merge(deep_merge(base, design), change)), "challenger")
        for name, change in (("btc", btc), ("fng", fng), ("both", both))]
    t0 = time.monotonic()
    db, coins, s = replay(settings, variants, "news", ["XRP", "SOL", "ETH"], resume="--resume" in sys.argv)
    print(f"engine and tracker: {time.monotonic() - t0:.0f} s", flush=True)
    labels = {"v0": "the design (no news filter)", "btc": "+ wait 60 min after a BTC 2% move",
              "fng": "+ no trade below 20 / above 80 Fear & Greed", "both": "+ both filters"}
    try:
        print("\nShadow trades (taken):")
        for v in variants:
            rs = [r[0] for r in db.execute("SELECT r_net FROM trades WHERE variant_id = ? AND taken = 1 AND status = 'closed'", (v.id,))]
            h1 = [r[0] for r in db.execute("SELECT r_net FROM trades WHERE variant_id = ? AND taken = 1 AND status = 'closed'"
                                           " AND entry_time < ?", (v.id, SPLIT))]
            h2 = [r[0] for r in db.execute("SELECT r_net FROM trades WHERE variant_id = ? AND taken = 1 AND status = 'closed'"
                                           " AND entry_time >= ?", (v.id, SPLIT))]
            print(f"   {labels[v.name]:46} {len(rs):5d} trades {st.mean(rs):+.3f}R | 2022-24 {st.mean(h1):+.3f}R | 2024-26 {st.mean(h2):+.3f}R")
        pa = s.paper_account
        pa.starting_balance, pa.risk_per_trade, pa.risk_tier_a, pa.max_open_risk = 150.0, 0.02, 0.03, 0.12
        pa.max_positions, pa.max_positions_per_coin, pa.allow_opposite, pa.first_position_always = 5, 2, False, True
        pa.daily_loss_stop, pa.leverage_cap, pa.drawdown_brake, pa.symbols = None, 10, None, coins
        print("\nThe demo account with the user's rules ($150):")
        for v in variants:
            with db:
                db.execute("UPDATE variants SET role = CASE id WHEN ? THEN 'baseline' ELSE 'challenger' END", (v.id,))
                db.execute("DELETE FROM engine_state")
            out = []
            for lo, hi in ((0, 2**62), (0, SPLIT), (SPLIT, 2**62)):
                reset_account(db, s)
                with db:
                    db.execute("UPDATE trades SET taken = -taken WHERE variant_id = ? AND taken > 0 AND (entry_time < ? OR entry_time >= ?)",
                               (v.id, lo, hi))
                try:
                    AccountEngine(s, db).process()
                finally:
                    with db:
                        db.execute("UPDATE trades SET taken = -taken WHERE variant_id = ? AND taken < 0", (v.id,))
                bals = [r[0] for r in db.execute("SELECT balance_after FROM account_trades WHERE account = ? AND status = 'closed'"
                                                 " ORDER BY exit_time, id", (ACCOUNT,))]
                bal = peak = 150.0
                dd = 0.0
                for b in bals:
                    bal = b
                    peak = max(peak, bal)
                    dd = max(dd, 1 - bal / peak)
                out.append((len(bals), bal, dd))
            (n, bal, dd), (_, b1, d1), (_, b2, d2) = out
            print(f"   {labels[v.name]:46} {n:5d} trades | $150 -> ${bal:,.0f} ({bal / 150 - 1:+,.0%}) max DD {dd:.1%} |"
                  f" 2022-24 {b1 / 150 - 1:+,.0%} (DD {d1:.0%}) | 2024-26 {b2 / 150 - 1:+,.0%} (DD {d2:.0%})", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
