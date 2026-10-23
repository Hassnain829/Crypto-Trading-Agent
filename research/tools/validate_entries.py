r"""Which entry is really best with the agent's own code (2026-10-21)? On the 4-year validation copy
(data/research/long4/validate.db, built by validate_design.py), three 15m-only variants side by side:

- dip + limit   (entry.dip_5m_minutes 60, limit order that must trade through: some entries are missed)
- dip + market  (the same wait, then a market order: always filled, taker fee and slippage)
- now + limit   (no wait: the limit order right after the signal, as the baseline does today)

each through the account with the user's rules: max 5 open, the first position per coin always allowed, max 2 per
coin, opposite signals skipped, A 3% / B 2%, 12% budget, leverage cap 10 (the demo's), without and with the brake.

    .venv\Scripts\python -u research\tools\validate_entries.py
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
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

from tradeagent.account.engine import AccountEngine, reset_account  # noqa: E402
from tradeagent.journal import connect, migrate  # noqa: E402
from tradeagent.setups.config import SetupParams, Variant, deep_merge, load_variants, register_variants  # noqa: E402
from tradeagent.setups.engine import SetupEngine  # noqa: E402
from tradeagent.sim.tracker import Tracker  # noqa: E402
from tradeagent.tv.catalog import load_catalog  # noqa: E402

COPY = ROOT / "data" / "research" / "long4" / "validate.db"
COINS = ["XRP", "SOL", "ETH"]
SPLIT = 1727740800000  # 2024-10-01


def main() -> None:
    conn = connect(COPY)
    migrate(conn)
    s = ld.long_settings(COINS)
    catalog = load_catalog(ld.settings.resolve(ld.settings.tradingview.catalog))
    base = load_variants(ld.settings.resolve(ld.settings.shadow.setups), catalog)[0].params.model_dump()

    def variant(name: str, override: dict) -> Variant:
        return Variant(name, SetupParams.model_validate(deep_merge(base, {"timeframes": ["15m"], **override})), "challenger")

    new = [variant("dipmkt", {"entry": {"mode": "market", "dip_5m_minutes": 60}}),
           variant("now15", {"entry": {"mode": "limit"}})]
    have = {r[0] for r in conn.execute("SELECT DISTINCT variant_id FROM trades")}
    todo = [v for v in new if v.id not in have]
    if todo:
        with conn:
            conn.execute("DELETE FROM engine_state")
        register_variants(conn, todo + [Variant("v0", SetupParams.model_validate(deep_merge(
            base, {"timeframes": ["15m"], "entry": {"mode": "limit", "dip_5m_minutes": 60}})), "baseline")])
        t0 = time.monotonic()
        print("engine:", dict(SetupEngine(s, todo, conn).process()), f"{time.monotonic() - t0:.0f} s", flush=True)
        print("tracker:", dict(Tracker(s, conn).update()), f"{time.monotonic() - t0:.0f} s", flush=True)

    ids = {r[0].split("-")[0]: r[0] for r in conn.execute("SELECT DISTINCT variant_id FROM trades")}
    labels = {"v0": "dip + limit", "dipmkt": "dip + market", "now15": "now + limit (no dip)"}
    print("\nShadow trades of each variant (15m signals, XRP/SOL/ETH, 2022-10 .. 2026-10):")
    for name, vid in ids.items():
        rows = conn.execute("SELECT status, r_net, reason, entry_time FROM trades WHERE variant_id = ? AND taken = 1",
                            (vid,)).fetchall()
        closed = [r[1] for r in rows if r[0] == "closed"]
        missed = [r[2] for r in rows if r[0] == "missed"]
        h1 = [r[1] for r in rows if r[0] == "closed" and r[3] < SPLIT]
        h2 = [r[1] for r in rows if r[0] == "closed" and r[3] >= SPLIT]
        print(f"   {labels.get(name, name):22} {len(closed):5d} entered, {len(missed):4d} not entered | {st.mean(closed):+.3f}R a trade"
              f" (2022-24 {st.mean(h1):+.3f}, 2024-26 {st.mean(h2):+.3f}) | why not entered:"
              f" {', '.join(f'{k} {v}' for k, v in sorted(_count(missed).items(), key=lambda x: -x[1])[:3])}")

    pa = s.paper_account
    pa.starting_balance, pa.risk_per_trade, pa.risk_tier_a, pa.max_open_risk = 150.0, 0.02, 0.03, 0.12
    pa.max_positions, pa.max_positions_per_coin, pa.allow_opposite, pa.first_position_always = 5, 2, False, True
    pa.daily_loss_stop, pa.symbols, pa.leverage_cap = None, COINS, 10
    print("\nThe demo account with the user's rules (max 5, first per coin always, max 2 per coin, no opposite, "
          "A 3% / B 2%, 12% budget, 10x):")
    for name, vid in ids.items():
        for brake in (None, 0.10):
            pa.drawdown_brake = brake
            with conn:
                conn.execute("UPDATE variants SET role = CASE id WHEN ? THEN 'baseline' ELSE 'challenger' END", (vid,))
                conn.execute("DELETE FROM engine_state")
            out = []
            for lo, hi in ((0, 2**62), (0, SPLIT), (SPLIT, 2**62)):
                reset_account(conn, s)
                with conn:
                    conn.execute("UPDATE trades SET taken = -taken WHERE variant_id = ? AND (entry_time < ? OR entry_time >= ?)",
                                  (vid, lo, hi))
                AccountEngine(s, conn).process()
                with conn:
                    conn.execute("UPDATE trades SET taken = -taken WHERE variant_id = ? AND taken < 0", (vid,))
                rows = conn.execute("SELECT balance_after FROM account_trades WHERE account = 'paper' AND status = 'closed'"
                                    " ORDER BY exit_time, id").fetchall()
                bal = peak = 150.0
                dd = 0.0
                for (b,) in rows:
                    bal = b
                    peak = max(peak, bal)
                    dd = max(dd, 1 - bal / peak)
                out.append((len(rows), bal, dd))
            (n, bal, dd), (_, b1, d1), (_, b2, d2) = out
            print(f"   {labels.get(name, name):22} brake {'on ' if brake else 'off'} | {n:5d} trades | $150 -> ${bal:9,.0f}"
                  f" ({bal / 150 - 1:+6.0%}) max DD {dd:5.1%} | 2022-24 {b1 / 150 - 1:+6.0%} (DD {d1:.0%})"
                  f" | 2024-26 {b2 / 150 - 1:+6.0%} (DD {d2:.0%})", flush=True)
    conn.close()


def _count(items: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        key = (item or "").split(", ")[-1]
        out[key] = out.get(key, 0) + 1
    return out


if __name__ == "__main__":
    main()
