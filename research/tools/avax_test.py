r"""Should AVAX become the 4th coin? (the user, 2026-10-21). Research only.

    .venv\Scripts\python -u research\tools\avax_test.py data    # AVAX candles 2022-09 .. today into the 4-year journal
    .venv\Scripts\python -u research\tools\long_backtest.py snapshots AVAX --4y
    .venv\Scripts\python -u research\tools\avax_test.py run     # the planned design on XRP/SOL/ETH/AVAX, 4 years

The planned design (15m signals, limit entry after a 5m dip, at most 60 minutes) runs in the agent's own engine on
an overlay of the 4-year research journal (learning/long_screen.py); then the demo account with the user's rules
(max 5 open, the first position per coin always, max 2 a coin, opposite signals skipped, A 3% / B 2%, 12% budget,
10x) on AVAX alone, on XRP/SOL/ETH, and on all four.
"""
from __future__ import annotations

import importlib.util
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
ld.use_4y()
ld.COINS, ld.MAIN, ld.CHECK = ["AVAX"], ["AVAX"], []
DAY = 86_400_000


def data() -> None:
    ld.copy_from_long()
    ld.candles(0.6)


def run() -> None:
    from tradeagent.account.engine import ACCOUNT, AccountEngine, reset_account
    from tradeagent.learning.long_screen import replay
    from tradeagent.setups.config import SetupParams, Variant, deep_merge, load_variants
    from tradeagent.tv.catalog import load_catalog

    settings = ld.settings.model_copy(deep=True)
    settings.learning.long_history_years = None  # the whole 4 years
    catalog = load_catalog(settings.resolve(settings.tradingview.catalog))
    base = load_variants(settings.resolve(settings.shadow.setups), catalog)[0].params.model_dump()
    design = Variant("v0", SetupParams.model_validate(deep_merge(
        base, {"timeframes": ["15m"], "entry": {"mode": "limit", "dip_5m_minutes": 60}})), "baseline")
    t0 = time.monotonic()
    db, coins, s = replay(settings, [design], "avax", ["XRP", "SOL", "ETH", "AVAX"])
    print(f"engine and tracker on {coins}: {time.monotonic() - t0:.0f} s", flush=True)
    try:
        start = db.execute("SELECT min(entry_time) FROM trades WHERE taken = 1 AND status = 'closed'").fetchone()[0]
        end = db.execute("SELECT max(entry_time) FROM trades WHERE taken = 1 AND status = 'closed'").fetchone()[0] + 1
        mid = start + (end - start) // 2
        print(f"\nShadow trades of the planned design, {time.strftime('%Y-%m-%d', time.gmtime(start / 1000))} .."
              f" {time.strftime('%Y-%m-%d', time.gmtime(end / 1000))}:")
        for coin in coins:
            rs = [r[0] for r in db.execute("SELECT r_net FROM trades WHERE symbol = ? AND taken = 1 AND status = 'closed'"
                                           " ORDER BY entry_time", (coin,))]
            h1 = [r[0] for r in db.execute("SELECT r_net FROM trades WHERE symbol = ? AND taken = 1 AND status = 'closed'"
                                           " AND entry_time < ?", (coin, mid))]
            h2 = [r[0] for r in db.execute("SELECT r_net FROM trades WHERE symbol = ? AND taken = 1 AND status = 'closed'"
                                           " AND entry_time >= ?", (coin, mid))]
            years = []
            for k in range(4):
                y = [r[0] for r in db.execute("SELECT r_net FROM trades WHERE symbol = ? AND taken = 1 AND status = 'closed'"
                                              " AND entry_time >= ? AND entry_time < ?", (coin, start + k * 365 * DAY,
                                                                                            start + (k + 1) * 365 * DAY))]
                years.append(f"{st.mean(y):+.3f}" if y else "  -  ")
            print(f"   {coin:5} {len(rs):5d} trades ({len(rs) / ((end - start) / DAY):.2f} a day) won"
                  f" {sum(r > 0 for r in rs) / len(rs):4.0%} {st.mean(rs):+.3f}R | half 1 {st.mean(h1):+.3f} half 2"
                  f" {st.mean(h2):+.3f} | by year {' '.join(years)}")

        pa = s.paper_account
        pa.starting_balance, pa.risk_per_trade, pa.risk_tier_a, pa.max_open_risk = 150.0, 0.02, 0.03, 0.12
        pa.max_positions, pa.max_positions_per_coin, pa.allow_opposite, pa.first_position_always = 5, 2, False, True
        pa.daily_loss_stop, pa.leverage_cap, pa.drawdown_brake = None, 10, None
        with db:
            db.execute("DELETE FROM engine_state")
        print("\nThe demo account with the user's rules ($150, max 5 open, max 2 a coin, opposite skipped, A 3% / B 2%,"
              " 12% budget, 10x):")
        for label, group in (("AVAX alone", ["AVAX"]), ("XRP + SOL + ETH (today)", ["XRP", "SOL", "ETH"]),
                             ("XRP + SOL + ETH + AVAX", ["XRP", "SOL", "ETH", "AVAX"])):
            out = []
            for lo, hi in ((0, 2**62), (0, mid), (mid, 2**62)):
                pa.symbols = group
                reset_account(db, s)
                with db:
                    db.execute("UPDATE trades SET taken = -taken WHERE taken > 0 AND (entry_time < ? OR entry_time >= ?)", (lo, hi))
                try:
                    AccountEngine(s, db).process()
                finally:
                    with db:
                        db.execute("UPDATE trades SET taken = -taken WHERE taken < 0")
                rows = [r[0] for r in db.execute("SELECT balance_after FROM account_trades WHERE account = ? AND status = 'closed'"
                                                 " ORDER BY exit_time, id", (ACCOUNT,))]
                bal = peak = 150.0
                dd = 0.0
                for b in rows:
                    bal = b
                    peak = max(peak, bal)
                    dd = max(dd, 1 - bal / peak)
                out.append((len(rows), bal, dd))
            (n, bal, dd), (_, b1, d1), (_, b2, d2) = out
            print(f"   {label:26} {n:5d} trades ({n / ((end - start) / DAY):.1f} a day) | $150 -> ${bal:9,.0f} ({bal / 150 - 1:+6.0%})"
                  f" max DD {dd:5.1%} | half 1 {b1 / 150 - 1:+6.0%} (DD {d1:.0%}) | half 2 {b2 / 150 - 1:+6.0%} (DD {d2:.0%})",
                  flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    {"data": data, "run": run}[sys.argv[1]]()
