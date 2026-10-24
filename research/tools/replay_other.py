r"""The planned design (15m + 5m dip 60) on all 13 coins of the 1.5-year research journal (2026-10-24). Research only.

    .venv\Scripts\python -u research\tools\replay_other.py [--resume]

The 13-coin journal (data/research/long/journal.db, 2025-04 to 2026-10, Python-copy indicators) has no Fear & Greed
table, so that one view points at the 4-year research journal. Output journal: data/replay/journal-other.db.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
COINS = ["XRP", "SOL", "ETH", "BTC", "ADA", "AVAX", "BNB", "DOGE", "LINK", "LTC", "NEAR", "SUI", "ZEC"]
OTHER = ROOT / "data" / "research" / "long" / "journal.db"
LONG4 = ROOT / "data" / "research" / "long4" / "journal.db"


def main() -> None:
    from tradeagent.config import load_settings
    from tradeagent.learning import long_screen
    from tradeagent.setups.config import SetupParams, Variant, deep_merge, load_variants
    from tradeagent.tv.catalog import load_catalog

    original = long_screen.overlay

    def overlay(settings, name, resume=False):
        conn = original(settings, name, resume)
        conn.execute("ATTACH DATABASE ? AS aux", (str(LONG4),))
        conn.execute("DROP VIEW IF EXISTS temp.fear_greed")
        conn.execute("CREATE TEMP VIEW fear_greed AS SELECT * FROM aux.fear_greed")
        return conn

    long_screen.overlay = overlay
    settings = load_settings(ROOT)
    settings.learning.long_history, settings.learning.long_history_years = str(OTHER), None
    catalog = load_catalog(settings.resolve(settings.tradingview.catalog))
    base = load_variants(settings.resolve(settings.shadow.setups), catalog)[0].params.model_dump()
    design = Variant("design", SetupParams.model_validate(
        deep_merge(base, {"timeframes": ["15m"], "entry": {"mode": "limit", "dip_5m_minutes": 60}})), "baseline")
    t0 = time.monotonic()
    db, coins, _ = long_screen.replay(settings, [design], "other", COINS, resume="--resume" in sys.argv)
    n = db.execute("SELECT count(*) FROM trades WHERE taken = 1 AND status = 'closed'").fetchone()[0]
    print(f"done in {time.monotonic() - t0:.0f} s: {len(coins)} coins, {n} closed taken trades (variant {design.id})", flush=True)
    db.close()


if __name__ == "__main__":
    main()
