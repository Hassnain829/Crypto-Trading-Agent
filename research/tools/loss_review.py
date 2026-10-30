r"""The user's questions of 2026-10-29: why did v4's losing trades lose, what did the price do after the stop, and how
often did it reach the target after stopping the trade out? Reads the gate's trades since goal.count_from (the replay
import plus the live baseline, one per signal, as the gate counts them) and the 1m candles, from the live journal
(read only).

    .venv\Scripts\python -u research\tools\loss_review.py

For each trade, from its entry on 1m candles (the target and stop are the trade's own planned prices):
- the first touch of the stop and of the target, ignoring the other; a target after the stop is "stop, then target"
- the worst price before the target (the stop room the trade needed, in R of its own risk)
- the best price before the stop (how far it went right first)
The window is the agent's max hold (72 h from the entry), and 6 days for "later".
Writes data/research/loss_review.txt and data/research/loss_review.json (per trade, for charts).
"""
from __future__ import annotations

import calendar
import json
import sqlite3
import statistics as st
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
HOUR = 3_600_000
HOLD = 72 * HOUR
LATER = 144 * HOUR
SWITCH = calendar.timegm((2026, 10, 24, 1, 30, 0)) * 1000


def fmt(ms: int | None) -> str:
    return time.strftime("%m-%d %H:%M", time.gmtime(ms / 1000)) if ms else "-"


def main() -> None:
    from tradeagent.config import load_settings

    settings = load_settings(ROOT)
    since = calendar.timegm(time.strptime(settings.goal.count_from, "%Y-%m-%d")) * 1000
    conn = sqlite3.connect(f"file:{settings.resolve(settings.journal.path).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    base = conn.execute("SELECT id, params_hash FROM variants WHERE role = 'baseline'").fetchone()
    rows = conn.execute(
        "SELECT * FROM (SELECT t.*, ROW_NUMBER() OVER (PARTITION BY symbol, timeframe, side, confirm_time"
        " ORDER BY variant_id = ? DESC, id) AS n FROM trades t WHERE book = 'exploration' AND taken = 1"
        " AND status = 'closed' AND entry_time >= ? AND variant_id IN (SELECT id FROM variants WHERE params_hash = ?))"
        " WHERE n = 1 ORDER BY entry_time", (base["id"], since, base["params_hash"])).fetchall()
    demo = {r["trade_id"]: r for r in conn.execute(
        "SELECT trade_id, status, pnl_usd, reject_reason FROM account_trades WHERE account = 'paper' AND entry_time >= ?",
        (SWITCH - HOUR,))}
    trades = []
    for t in rows:
        sign = 1 if t["side"] == "long" else -1
        ctx = json.loads(t["context_json"])
        entry, stop, target = t["entry_ref"], t["stop_initial"], t["target"]
        risk = abs(entry - stop)
        reference = abs(target - stop) / 2.5  # the planned swing risk (target 1.5R + stop 1R from the order price)
        order = stop + sign * reference
        candles = conn.execute(
            "SELECT open_time, high, low, close FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time >= ?"
            " AND open_time < ? ORDER BY open_time", (t["symbol"], t["entry_time"], t["entry_time"] + LATER)).fetchall()
        t_stop = t_target = None
        worst_before_target = best_before_stop = 0.0  # in R of the trade's risk, from the entry
        best_after_stop = beyond_stop = 0.0
        for c in candles:
            fav = sign * ((c["high"] if sign > 0 else c["low"]) - entry) / risk
            adv = sign * ((c["low"] if sign > 0 else c["high"]) - entry) / risk
            if t_stop is None:
                best_before_stop = max(best_before_stop, fav)
                if adv <= -1:
                    t_stop = c["open_time"]
            elif c["open_time"] < t_stop + 24 * HOUR:
                best_after_stop = max(best_after_stop, fav)
            if t_target is None:
                worst_before_target = min(worst_before_target, adv)
                if (c["high"] >= target if sign > 0 else c["low"] <= target):
                    t_target = c["open_time"]
            if t_stop is not None and t_target is not None and c["open_time"] > t_stop + 24 * HOUR:
                break
        if t_stop is not None and t_target is not None and t_target > t_stop:
            beyond_stop = -worst_before_target - 1
        hour = time.gmtime(t["entry_time"] / 1000).tm_hour
        trend = "bull" if sign > 0 else "bear"
        btc = ctx.get("btc_change")
        trades.append({
            "id": t["id"], "live": t["variant_id"] == base["id"], "symbol": t["symbol"], "side": t["side"],
            "signal": t["confirm_time"] + 900_000, "entry_time": t["entry_time"], "entry": entry, "stop": stop,
            "target": target, "order": order, "exit_time": t["exit_time"], "exit": t["exit_reason"], "r": t["r_net"],
            "risk_pct": risk / entry * 100, "planned_pct": reference / order * 100, "target_r": abs(target - entry) / risk,
            "t_stop": t_stop, "t_target": t_target, "need_r": -worst_before_target if t_target else None,
            "best_before_stop": best_before_stop, "best_after_stop_24h": best_after_stop, "beyond_stop": beyond_stop,
            "quality": ctx.get("quality"), "reason": ctx.get("quality_reason"),
            "h4": None if ctx["htf"].get("4h") is None else ctx["htf"]["4h"] == trend,
            "h1": None if ctx["htf"].get("1h") is None else ctx["htf"]["1h"] == trend,
            "btc_with": None if btc is None else sign * btc > 0, "btc_change": btc,
            "dip_found": (ctx.get("dip_entry") or {}).get("dip_found"), "dip_min": (ctx.get("dip_entry") or {}).get("minutes"),
            "session": "00-08" if hour < 8 else "08-13" if hour < 13 else "13-21" if hour < 21 else "21-24",
            "demo": dict(demo[t["id"]]) if t["id"] in demo else None,
        })
    out: list[str] = []
    rs = [t["r"] for t in trades]
    losers = [t for t in trades if t["exit"] == "stop"]
    out.append(f"{len(trades)} trades since {settings.goal.count_from} ({sum(t['live'] for t in trades)} live since the"
               f" switch): won {sum(r > 0 for r in rs) / len(rs):.0%}, {st.mean(rs):+.3f}R, total {sum(rs):+.1f}R")
    out.append(f"exits: " + ", ".join(f"{k} {sum(t['exit'] == k for t in trades)}" for k in ("target", "stop", "timeout")))
    real_stop = [t["risk_pct"] for t in trades]
    out.append(f"stop distance from the fill: median {st.median(real_stop):.2f}%, under 1.5%: "
               f"{sum(x < 1.5 for x in real_stop)} of {len(trades)} (the planned swing is at least 1.5% from the signal"
               f" price; the dip fill sits closer to the stop)")
    out.append("")
    out.append(f"== {len(losers)} stopped trades: what came after the stop ==")
    later72 = [t for t in losers if t["t_target"] and t["t_target"] - t["entry_time"] < HOLD]
    later6d = [t for t in losers if t["t_target"]]
    out.append(f"target reached after the stop within the 72 h hold: {len(later72)} of {len(losers)}"
               f" ({len(later72) / len(losers):.0%}); within 6 days: {len(later6d)}")
    if later72:
        gaps = sorted((t["t_target"] - t["t_stop"]) / HOUR for t in later72)
        need = sorted(t["need_r"] for t in later72)
        out.append(f"  hours from the stop to the target: median {st.median(gaps):.1f} (min {gaps[0]:.1f}, max {gaps[-1]:.1f})")
        out.append(f"  stop room they needed (R of their own stop): median {st.median(need):.2f}; "
                   + ", ".join(f"<= {k}x: {sum(n < k for n in need)}" for k in (1.25, 1.5, 2.0, 3.0)))
    never = [t for t in losers if not (t["t_target"] and t["t_target"] - t["entry_time"] < HOLD)]
    out.append(f"never reached the target in 72 h: {len(never)}; their best move in the 24 h after the stop:"
               f" median {st.median([t['best_after_stop_24h'] for t in never]):+.2f}R" if never else "")
    first = [t["best_before_stop"] for t in losers]
    out.append(f"went right first: >= +0.5R {sum(x >= 0.5 for x in first)}, >= +1R {sum(x >= 1 for x in first)}"
               f" of {len(losers)} (break-even at 1R and partial exits were tested before and lost)")
    out.append("")
    winners = [t for t in trades if t["exit"] == "target"]
    if winners:
        need_w = [t["need_r"] for t in winners if t["need_r"] is not None]
        out.append(f"winners: {len(winners)}; how close they came to the stop first (R): median {st.median(need_w):.2f},"
                   f" >= 0.75R {sum(x >= 0.75 for x in need_w)}, >= 0.9R {sum(x >= 0.9 for x in need_w)}")
    out.append("")
    out.append("== groups (descriptive; small samples, earlier research found the 4h trend and the side flip between periods) ==")
    for name, key in (("side", "side"), ("quality", "quality"), ("4h trend with", "h4"), ("1h trend with", "h1"),
                      ("BTC 12h with", "btc_with"), ("dip found", "dip_found"), ("session UTC", "session")):
        groups: dict[object, list[float]] = defaultdict(list)
        for t in trades:
            groups[t[key]].append(t["r"])
        out.append(f"{name}: " + "; ".join(
            f"{k}: {len(v)} trades, won {sum(r > 0 for r in v) / len(v):.0%}, {st.mean(v):+.2f}R"
            for k, v in sorted(groups.items(), key=lambda kv: str(kv[0]))))
    buckets: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        b = "<1.5%" if t["risk_pct"] < 1.5 else "1.5-2%" if t["risk_pct"] < 2 else "2-3%" if t["risk_pct"] < 3 else ">=3%"
        buckets[b].append(t["r"])
    out.append("stop from the fill: " + "; ".join(
        f"{k}: {len(v)} trades, won {sum(r > 0 for r in v) / len(v):.0%}, {st.mean(v):+.2f}R" for k, v in sorted(buckets.items())))
    by_month: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        by_month[time.strftime("%Y-%m", time.gmtime(t["entry_time"] / 1000))].append(t["r"])
    out.append("by month: " + "; ".join(f"{k}: {len(v)} trades, {sum(v):+.1f}R" for k, v in sorted(by_month.items())))
    out.append("")
    out.append("== the last 20 stopped trades ==")
    out.append("coin side   entry (UTC)  stop%  went right  stop hit     after the stop (24 h)  target later")
    for t in losers[-20:]:
        later = (f"yes, {(t['t_target'] - t['t_stop']) / HOUR:.1f} h after, {t['beyond_stop']:.2f}R past the stop"
                 if t["t_target"] and t["t_target"] > (t["t_stop"] or 0) else "no")
        demo_note = ""
        if t["demo"]:
            demo_note = f"  demo {t['demo']['status']} {t['demo']['pnl_usd'] or 0:+.2f}$" if t["demo"]["status"] != "rejected" \
                else f"  demo skipped ({t['demo']['reject_reason']})"
        out.append(f"{t['symbol']:4} {t['side']:5}  {fmt(t['entry_time'])}  {t['risk_pct']:.2f}  {t['best_before_stop']:+.2f}R"
                   f"      {fmt(t['t_stop'])}  best {t['best_after_stop_24h']:+.2f}R            {later}{demo_note}")
    text = "\n".join(out)
    print(text)
    (ROOT / "data" / "research" / "loss_review.txt").write_text(text + "\n", encoding="utf-8")
    (ROOT / "data" / "research" / "loss_review.json").write_text(json.dumps(trades), encoding="utf-8")


if __name__ == "__main__":
    main()
