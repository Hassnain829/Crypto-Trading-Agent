"""Before the OI flag becomes a size tier: does it overlap with the Trendline tier (quality A)? Cross-tab of the two
flags on the baseline's taken trades and on its skipped signals. Read-only.

    .venv\\Scripts\\python -I research\\tools\\oi_trendline_overlap.py
"""
from __future__ import annotations

import sqlite3
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tradeagent.config import load_settings  # noqa: E402

M, H = 60_000, 3_600_000
Q = 15 * M
TF = {"5m": 5 * M, "15m": 15 * M}
settings = load_settings(ROOT)
conn = sqlite3.connect(f"file:{settings.resolve(settings.journal.path)}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
oi_db = sqlite3.connect(ROOT / "data" / "research" / "oi_history.db")
OI = {coin: {t * 1000 + Q: c for t, c in oi_db.execute("SELECT time, c FROM oi WHERE symbol = ?", (coin,))}
      for coin in ("XRP", "SOL", "ETH")}
tl_db = sqlite3.connect(ROOT / "data" / "research" / "indicators_history.db")
TL = {}
for coin, t, plot in tl_db.execute("SELECT symbol, time, plot FROM flags WHERE tf = '15m' AND study LIKE 'Dynamic Trendline%'"
                                   " AND plot LIKE '%alertcondition%'"):
    TL.setdefault((coin, "long" if "LONG" in plot else "short"), set()).add(t)
TL_END = max(t for times in TL.values() for t in times)


def describe(rs: list[float]) -> str:
    return f"n={len(rs):3d} win={sum(r > 0 for r in rs) / len(rs):.0%} exp={st.mean(rs):+.3f}R" if rs else "n=  0"


for taken, label in ((1, "taken trades"), (0, "skipped signals")):
    cells: dict[tuple[bool, bool], list[float]] = {}
    for t in conn.execute("""SELECT t.symbol, t.timeframe, t.side, t.confirm_time, t.r_net FROM trades t
            JOIN variants v ON v.id = t.variant_id WHERE v.role = 'baseline' AND t.taken = ? AND t.status = 'closed'
            AND t.symbol IN ('XRP', 'SOL', 'ETH')""", (taken,)):
        decision = t["confirm_time"] + TF[t["timeframe"]]
        if decision > TL_END + Q:
            continue  # after the Trendline history ends
        last = decision - decision % Q
        now, before = OI[t["symbol"]].get(last), OI[t["symbol"]].get(last - 4 * H)
        if now is None or before is None:
            continue
        oi_up = now / before - 1 > 0.01
        times = TL.get((t["symbol"], t["side"]), set())
        tl = any(decision - 8 * Q <= bt and bt + Q <= decision for bt in times)
        cells.setdefault((oi_up, tl), []).append(t["r_net"])
    total = sum(len(v) for v in cells.values())
    print(f"== {label} ({total} with both histories)")
    for oi_up in (True, False):
        for tl in (True, False):
            print(f"  OI rising {'yes' if oi_up else 'no '} | Trendline {'yes' if tl else 'no '}: {describe(cells.get((oi_up, tl), []))}")
    both = len(cells.get((True, True), []))
    oi_all = both + len(cells.get((True, False), []))
    tl_all = both + len(cells.get((False, True), []))
    print(f"  overlap: {both} trades have both; OI flag {oi_all}, Trendline flag {tl_all}"
          f" -> {both / oi_all:.0%} of OI trades are also Trendline trades\n" if oi_all else "")
