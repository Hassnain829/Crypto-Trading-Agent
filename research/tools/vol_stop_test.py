"""Volatility-scaled minimum stop (research/notes/2026-10-19-vol-stop-plan.md), on trades already simulated by the
coin screen and by the live journal. Read-only.

    .venv\\Scripts\\python -I research\\tools\\vol_stop_test.py
"""
from __future__ import annotations

import bisect
import sqlite3
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tradeagent.config import load_settings  # noqa: E402

Q = 900_000
TF = {"5m": 300_000, "15m": 900_000}
REF_RANGE = 0.0053  # XRP's median 15m range (30-day pre-screen, 2026-10-19), where the 1.5% minimum is tuned
BASE_MIN = 0.015
WEAKEST = 0.231  # XRP's expectancy with the 1.5% rule over the screen windows
settings = load_settings(ROOT)
screen = sqlite3.connect(f"file:{ROOT / 'data' / 'research' / 'coin_screen.db'}?mode=ro", uri=True)
live = sqlite3.connect(f"file:{settings.resolve(settings.journal.path)}?mode=ro", uri=True)
windows = {tf: screen.execute("SELECT min(bar_time), max(bar_time) FROM snapshots WHERE timeframe = ? AND symbol != 'XRP'",
                              (tf,)).fetchone() for tf in TF}


class Vol:
    """Rolling median 15m range over the 672 closed candles before a time."""

    def __init__(self, conn: sqlite3.Connection, symbol: str) -> None:
        rows = conn.execute("SELECT open_time, high, low, close FROM candles WHERE symbol = ? AND timeframe = '15m'"
                            " ORDER BY open_time", (symbol,)).fetchall()
        self.times = [r[0] for r in rows]
        self.ranges = [(r[1] - r[2]) / r[3] for r in rows]

    def at(self, t: int) -> float | None:
        end = bisect.bisect_right(self.times, t - Q)  # candles closed at or before t
        if end < 672:
            return None
        return st.median(self.ranges[end - 672:end])


def trades(conn: sqlite3.Connection, symbol: str) -> list[tuple]:
    q = ("SELECT t.confirm_time, t.timeframe, t.entry_time, t.entry_ref, t.stop_initial, t.r_net, t.exit_reason, t.taken"
         " FROM trades t JOIN variants v ON v.id = t.variant_id WHERE v.role = 'baseline' AND t.status = 'closed'"
         " AND t.symbol = ? AND (t.taken = 1 OR t.reason = 'min_stop_pct')"
         " AND ((t.timeframe = '5m' AND t.confirm_time BETWEEN ? AND ?) OR (t.timeframe = '15m' AND t.confirm_time BETWEEN ? AND ?))"
         " ORDER BY t.entry_time")
    return conn.execute(q, (symbol, *windows["5m"], *windows["15m"])).fetchall()


def stats(rows: list[tuple]) -> dict:
    rs = [r[5] for r in rows]
    if not rs:
        return {"n": 0}
    wins, losses = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    return {"n": len(rs), "win": sum(r > 0 for r in rs) / len(rs), "exp": st.mean(rs),
            "pf": wins / losses if losses else None, "target": sum(1 for r in rows if r[6] == "target") / len(rs)}


def fmt(s: dict) -> str:
    if not s["n"]:
        return "no trades"
    pf = f"{s['pf']:.2f}" if s["pf"] is not None else "-"
    return f"n={s['n']:3d} win={s['win']:.0%} exp={s['exp']:+.3f}R PF={pf} target={s['target']:.0%}"


def run(conn: sqlite3.Connection, symbol: str, candidate: bool) -> None:
    vol = Vol(conn, symbol)
    rows = trades(conn, symbol)
    fixed = [r for r in rows if r[7] == 1]
    scaled, mins = [], []
    for r in rows:
        v = vol.at(r[0] + TF[r[1]])
        if v is None:
            continue
        minimum = BASE_MIN * v / REF_RANGE
        mins.append(minimum)
        if abs(r[3] - r[4]) / r[3] >= minimum:
            scaled.append(r)
    s_fixed, s_scaled = stats(fixed), stats(scaled)
    print(f"  {symbol:8} 1.5% rule:   {fmt(s_fixed)}")
    print(f"  {'':8} scaled rule: {fmt(s_scaled)}  (minimum stop median {st.median(mins):.2%})")
    if candidate and s_scaled["n"]:
        mid = scaled[len(scaled) // 2][2]
        h1, h2 = stats([r for r in scaled if r[2] < mid]), stats([r for r in scaled if r[2] >= mid])
        checks = {"40+": s_scaled["n"] >= 40, "halves>0": bool(h1["n"] and h2["n"] and h1["exp"] > 0 and h2["exp"] > 0),
                  "PF>=1.3": (s_scaled["pf"] or 0) >= 1.3, "target>=42%": s_scaled["target"] >= 0.42,
                  f">= +{WEAKEST}R": s_scaled["exp"] >= WEAKEST}
        verdict = "QUALIFIES" if all(checks.values()) else "no"
        print(f"  {'':8} halves {h1.get('exp', 0):+.3f} / {h2.get('exp', 0):+.3f} -> {verdict}: "
              + ", ".join(f"{k} {'ok' if v else 'FAIL'}" for k, v in checks.items()))


print("current coins (live journal; comparison only):")
for coin in ("XRP", "SOL", "ETH"):
    run(live, coin, candidate=False)
print("\ncandidates (coin screen):")
for (coin,) in screen.execute("SELECT DISTINCT symbol FROM trades WHERE symbol != 'XRP' ORDER BY symbol").fetchall():
    run(screen, coin, candidate=True)
