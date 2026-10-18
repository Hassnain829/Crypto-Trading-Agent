"""Which indicator states separate the agent's good trades from its bad ones, and what would that do to ROI?
(research, read-only)

Context = the last closed 15m bar of the coin when the trade's confirming candle closed.
"""

from __future__ import annotations

import bisect
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RDB = sqlite3.connect(ROOT / "data" / "research" / "indicators_history.db")
JDB = sqlite3.connect(f"file:{ROOT / 'data' / 'journal.db'}?mode=ro", uri=True)
JDB.row_factory = sqlite3.Row
M15 = 900_000


def series(study: str, plot_like: str) -> dict[str, tuple[list[int], list[float]]]:
    out = {}
    for coin in ("XRP", "SOL", "ETH"):
        rows = RDB.execute("SELECT time, value FROM ind_values WHERE symbol=? AND tf='15m' AND study=? AND plot LIKE ? ORDER BY time",
                           (coin, study, plot_like)).fetchall()
        out[coin] = ([r[0] for r in rows], [r[1] for r in rows])
    return out


def flag_times(study: str, title_like: str, table: str = "flags") -> dict[str, list[int]]:
    out = {}
    for coin in ("XRP", "SOL", "ETH"):
        col, cond = ("time", "") if table == "flags" else ("time", " AND value != 0")
        out[coin] = [r[0] for r in RDB.execute(f"SELECT {col} FROM {table} WHERE symbol=? AND tf='15m' AND study=? AND plot LIKE ?{cond}"
                                               " ORDER BY time", (coin, study, title_like))]
    return out


def at(s, coin, close):
    times, vals = s[coin]
    i = bisect.bisect_right(times, close - M15) - 1
    return vals[i] if i >= 0 and close - M15 - times[i] < 4 * M15 else None


def recent(ft, coin, close, bars=8):
    times = ft[coin]
    i = bisect.bisect_left(times, close - bars * M15)
    return i < len(times) and times[i] + M15 <= close


def stats(r):
    if not r:
        return "   0"
    w = sum(1 for x in r if x > 0)
    return f"{len(r):3} tr {w / len(r):4.0%} {sum(r) / len(r):+.3f}R"


def account(trades, risk_of, start=150.0):
    """Compounded demo account: each trade risks risk_of(trade) of the balance; R already includes costs."""
    bal, peak, dd = start, start, 0.0
    for t in sorted(trades, key=lambda t: t["exit_time"]):
        risk = risk_of(t)
        if risk:
            bal += bal * risk * t["r_net"]
            peak = max(peak, bal)
            dd = max(dd, (peak - bal) / peak)
    return bal, dd


def main() -> None:
    start = RDB.execute("SELECT min(time) FROM bars WHERE tf='15m'").fetchone()[0] + 210 * M15  # EMA200 warm-up
    base = JDB.execute("SELECT id FROM variants WHERE role='baseline'").fetchone()[0]
    trades = [dict(t) for t in JDB.execute(
        "SELECT * FROM trades WHERE book='exploration' AND variant_id=? AND taken=1 AND status='closed' AND entry_time>=?"
        " AND symbol IN ('XRP','SOL','ETH') ORDER BY entry_time", (base, start))]
    adx = series("Average directional index", "%ADX%")
    rsi = series("Relative strength index", "%RSI%")
    pctb = series("Bollinger Bands %B", "%Bollinger%")
    ema = series("Exponential moving average", "%EMA%")
    st_up = series("Supertrend", "%Up Trend%")
    close_px = {}
    for coin in ("XRP", "SOL", "ETH"):
        rows = RDB.execute("SELECT time, close FROM bars WHERE symbol=? AND tf='15m' ORDER BY time", (coin,)).fetchall()
        close_px[coin] = ([r[0] for r in rows], [r[1] for r in rows])
    ut_long = flag_times("UT Bot Alerts", "%alertcondition:UT Long%", "ind_values")
    ut_short = flag_times("UT Bot Alerts", "%alertcondition:UT Short%", "ind_values")
    tl_long = flag_times("Dynamic Trendline Breakout [RFX]", "%alertcondition:LONG%")
    tl_short = flag_times("Dynamic Trendline Breakout [RFX]", "%alertcondition:SHORT%")
    for t in trades:
        coin, long = t["symbol"], t["side"] == "long"
        close = t["confirm_time"] + (300_000 if t["timeframe"] == "5m" else M15)
        px = at(close_px, coin, close)
        e = at(ema, coin, close)
        r = at(rsi, coin, close)
        b = at(pctb, coin, close)
        t["adx"] = at(adx, coin, close)
        t["rsi_side"] = None if r is None else (r if long else 100 - r)
        t["pctb_side"] = None if b is None else (b if long else 1 - b)
        t["ema_with"] = None if px is None or e is None else ((px > e) == long)
        up = at(st_up, coin, close)  # the Up Trend line exists only while Supertrend is up
        t["st_with"] = (up is not None) == long
        t["ut_with"] = recent(ut_long if long else ut_short, coin, close)
        t["tl_with"] = recent(tl_long if long else tl_short, coin, close)
    mid = trades[len(trades) // 2]["entry_time"]

    def show(name, groups):
        print(f"\n{name}")
        for label, pick in groups:
            part = [t for t in trades if pick(t)]
            h1 = [t["r_net"] for t in part if t["entry_time"] < mid]
            h2 = [t["r_net"] for t in part if t["entry_time"] >= mid]
            print(f"  {label:<34} {stats([t['r_net'] for t in part])}   halves {stats(h1)} | {stats(h2)}")

    print(f"Agent's baseline trades with full indicator context: {stats([t['r_net'] for t in trades])}")
    show("ADX (trend strength)", [("ADX < 20 (chop)", lambda t: t["adx"] is not None and t["adx"] < 20),
                                  ("ADX 20-30", lambda t: t["adx"] is not None and 20 <= t["adx"] < 30),
                                  ("ADX >= 30 (strong trend)", lambda t: t["adx"] is not None and t["adx"] >= 30)])
    show("RSI in the trade's direction", [("< 45 (pullback)", lambda t: t["rsi_side"] is not None and t["rsi_side"] < 45),
                                          ("45-60", lambda t: t["rsi_side"] is not None and 45 <= t["rsi_side"] < 60),
                                          ("60-70", lambda t: t["rsi_side"] is not None and 60 <= t["rsi_side"] < 70),
                                          (">= 70 (stretched)", lambda t: t["rsi_side"] is not None and t["rsi_side"] >= 70)])
    show("Bollinger %B in the trade's direction", [("< 0.5 (cheap side)", lambda t: t["pctb_side"] is not None and t["pctb_side"] < 0.5),
                                                   ("0.5-1.0", lambda t: t["pctb_side"] is not None and 0.5 <= t["pctb_side"] < 1),
                                                   (">= 1.0 (outside the band)", lambda t: t["pctb_side"] is not None and t["pctb_side"] >= 1)])
    show("Trend filters", [("with EMA 200", lambda t: t["ema_with"] is True), ("against EMA 200", lambda t: t["ema_with"] is False),
                           ("with Supertrend", lambda t: t["st_with"]), ("against Supertrend", lambda t: not t["st_with"])])
    show("Recent same-direction signal (2 h)", [("UT Bot", lambda t: t["ut_with"]), ("no UT Bot", lambda t: not t["ut_with"]),
                                                ("Trendline", lambda t: t["tl_with"]), ("no Trendline", lambda t: not t["tl_with"])])

    print("\nROI on $150, compounding, every signal (same trades as above):")
    plans = {
        "now: 2% on every trade": lambda t: 0.02,
        "3% with a Trendline confirmation, else 2%": lambda t: 0.03 if t["tl_with"] else 0.02,
        "3% Trendline or UT Bot, else 2%": lambda t: 0.03 if (t["tl_with"] or t["ut_with"]) else 0.02,
        "2%, skip RSI >= 70 entries": lambda t: 0.0 if (t["rsi_side"] or 0) >= 70 else 0.02,
        "2%, skip when ADX < 20": lambda t: 0.0 if (t["adx"] or 99) < 20 else 0.02,
    }
    for name, plan in plans.items():
        bal, dd = account(trades, plan)
        taken = [t for t in trades if plan(t)]
        print(f"  {name:<44} ${bal:8.2f} ({(bal / 150 - 1) * 100:+6.1f}%)  max drawdown {dd:5.1%}  "
              f"trades {len(taken)}  win {sum(1 for t in taken if t['r_net'] > 0) / max(1, len(taken)):.0%}")


if __name__ == "__main__":
    main()
