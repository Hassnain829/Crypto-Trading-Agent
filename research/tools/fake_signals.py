"""Fake-signal features (research/notes/2026-10-19-fake-signals-plan.md) on the baseline's simulated trades.
Read-only on the live journal.

    .venv\\Scripts\\python -I research\\tools\\fake_signals.py
"""
from __future__ import annotations

import json
import sqlite3
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tradeagent.config import load_settings  # noqa: E402

TF = {"5m": 300_000, "15m": 900_000}
settings = load_settings(ROOT)
conn = sqlite3.connect(f"file:{settings.resolve(settings.journal.path)}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

_cache: dict[tuple[str, str], list[tuple]] = {}


def chart(symbol: str, tf: str) -> list[tuple]:
    """Every good snapshot of a chart, newest signal version per candle: (bar_time, values, open, high, low, close, volume)."""
    if (symbol, tf) not in _cache:
        rows = conn.execute(
            "SELECT bar_time, values_json, open, high, low, close, volume, signal_version FROM snapshots"
            " WHERE symbol = ? AND timeframe = ? AND problems_json IS NULL ORDER BY bar_time, signal_version", (symbol, tf))
        by_time = {}
        for r in rows:
            by_time[r[0]] = (r[0], json.loads(r[1]), r[2], r[3], r[4], r[5], r[6])
        _cache[(symbol, tf)] = sorted(by_time.values())
    return _cache[(symbol, tf)]


def index_of(bars: list[tuple], t: int) -> int | None:
    lo, hi = 0, len(bars) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if bars[mid][0] == t:
            return mid
        lo, hi = (mid + 1, hi) if bars[mid][0] < t else (lo, mid - 1)
    return None


def features(t: sqlite3.Row) -> dict | None:
    bars = chart(t["symbol"], t["timeframe"])
    i, k = index_of(bars, t["confirm_time"]), index_of(bars, t["trigger_time"])
    if i is None or k is None or k < 100:
        return None
    sign = 1 if t["side"] == "long" else -1
    _bt, values, o, h, lo, c, vol = bars[i]
    q = values.get("qtrend") or {}
    flips = sum(1 for b in bars[k - 48:k] if (b[1].get("qtrend") or {}).get("buy") == 1 or (b[1].get("qtrend") or {}).get("sell") == 1)
    trend_line = q.get("trend_line")
    late = sign * (c - trend_line) / c if trend_line else None
    body = abs(c - o) / (h - lo) if h and lo and h > lo else None
    vols = [b[6] for b in bars[i - 20:i] if b[6]]
    vol_ratio = vol / st.mean(vols) if vol and vols else None
    hist = (values.get("klinger") or {}).get("hist")
    past = [abs((b[1].get("klinger") or {}).get("hist")) for b in bars[i - 100:i] if (b[1].get("klinger") or {}).get("hist") is not None]
    return {"F1": flips >= 3, "late": late, "F3": body is not None and body < 0.5,
            "F4": vol_ratio is not None and vol_ratio < 1.0,
            "F5": hist is not None and bool(past) and abs(hist) < st.median(past)}


def describe(name: str, rs: list[float]) -> str:
    return f"{name}: n={len(rs):3d} win={sum(r > 0 for r in rs) / len(rs):.0%} exp={st.mean(rs):+.3f}R" if rs else f"{name}: none"


def analyse(taken: int) -> dict:
    trades = conn.execute("""
        SELECT t.symbol, t.timeframe, t.side, t.trigger_time, t.confirm_time, t.entry_time, t.r_net
        FROM trades t JOIN variants v ON v.id = t.variant_id
        WHERE v.role = 'baseline' AND t.taken = ? AND t.status = 'closed' AND t.symbol IN ('XRP', 'SOL', 'ETH')
        ORDER BY t.entry_time""", (taken,)).fetchall()
    rows = []
    for t in trades:
        f = features(t)
        if f:
            rows.append((t, f))
    lates = sorted(f["late"] for _t, f in rows if f["late"] is not None)
    median_late = lates[len(lates) // 2]
    for _t, f in rows:
        f["F2"] = f["late"] is not None and f["late"] > median_late
    mid = rows[len(rows) // 2][0]["entry_time"]
    print(f"== {'taken trades' if taken else 'skipped signals'}: {len(rows)} with features "
          f"(of {len(trades)}), median late distance {median_late:.2%}")
    out = {}
    for flag, label in (("F1", "chop: 3+ Q-Trend signals in the 48 candles before"), ("F2", "late: far from the trend line"),
                        ("F3", "weak candle: body < 50% of range"), ("F4", "low volume: below the 20-candle average"),
                        ("F5", "weak Klinger: |hist| below its 100-candle median")):
        diffs = []
        print(f"  -- {flag} {label}")
        for name, part in (("all", rows), ("half 1", [r for r in rows if r[0]["entry_time"] < mid]),
                           ("half 2", [r for r in rows if r[0]["entry_time"] >= mid])):
            yes = [t["r_net"] for t, f in part if f[flag]]
            no = [t["r_net"] for t, f in part if not f[flag]]
            print(f"     {name:6} {describe('flag', yes)} | {describe('other', no)}")
            if name != "all" and yes and no:
                diffs.append((st.mean(yes) - st.mean(no), len(yes), len(no)))
        for side in ("long", "short"):
            yes = [t["r_net"] for t, f in rows if f[flag] and t["side"] == side]
            no = [t["r_net"] for t, f in rows if not f[flag] and t["side"] == side]
            print(f"     {side:6} {describe('flag', yes)} | {describe('other', no)}")
        same = len(diffs) == 2 and (diffs[0][0] > 0) == (diffs[1][0] > 0)
        full = same and all(abs(d) >= 0.15 and ny >= 25 and nn >= 25 for d, ny, nn in diffs)
        size_only = same and all(abs(d) >= 0.15 for d, _ny, _nn in diffs)
        out[flag] = (full, size_only, [round(d, 3) for d, _, _ in diffs])
        print(f"     half differences (flag - other): {out[flag][2]} -> {'PASS' if full else 'size-only' if size_only else 'no'}")
    return out


taken = analyse(1)
print()
skipped = analyse(0)
print("\n== verdict (taken: full pass, or effect-size pass with the skipped signals passing fully the same way)")
for flag in taken:
    t_full, t_size, t_d = taken[flag]
    s_full, _s_size, s_d = skipped[flag]
    same_way = t_d and s_d and all((a > 0) == (t_d[0] > 0) for a in t_d + s_d)
    verdict = "PASS" if t_full and same_way else "PROMISING" if t_size and s_full and same_way else "no"
    print(f"  {flag}: taken {t_d}, skipped {s_d} -> {verdict}")
