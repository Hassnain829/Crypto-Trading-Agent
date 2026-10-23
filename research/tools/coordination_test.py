"""Linking the 5m and 15m signals of a coin, and skipping weak B trades (research/notes/2026-10-20-coordination-plan.md).

    .venv\\Scripts\\python -u research\\tools\\coordination_test.py

Samples: past (v6 backtest journal), forward (live journal, read only), replication (the v6 signals skipped by the
1.5% minimum stop, treated as if taken). Every rule changes which trades are taken and when they close; the result
is shown in R and as the demo account at today's rules (A 3% / B 2% of the balance, 12% open-risk budget).
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAST = ROOT / "data" / "replay" / "journal-v6.db"
LIVE = ROOT / "data" / "journal.db"
BASELINE = "v0-773ea9"
COINS = ("XRP", "SOL", "ETH")
FAR = 2**62


def load(conn: sqlite3.Connection, taken: int, since: int = 0, coins: tuple[str, ...] = COINS) -> list[dict]:
    rows = conn.execute(
        "SELECT id, symbol, timeframe, side, entry_time, exit_time, r_net, r_gross, context_json, status, entry_ref,"
        " stop_initial FROM trades WHERE book = 'exploration' AND variant_id = ? AND taken = ? AND status IN ('open', 'closed')"
        f" AND entry_time >= ? AND symbol IN ({', '.join('?' * len(coins))}) ORDER BY entry_time, id",
        (BASELINE, taken, since, *coins)).fetchall()
    out = []
    for r in rows:
        ctx = json.loads(r[8] or "{}")
        out.append({"id": r[0], "symbol": r[1], "tf": r[2], "side": r[3], "entry": r[4], "exit": r[5] or FAR,
                    "r": r[6], "cost": (r[7] - r[6]) if r[7] is not None and r[6] is not None else 0.05,
                    "q": ctx.get("quality") or "B", "sqz": ctx.get("sqz_fire"), "h1": (ctx.get("htf") or {}).get("1h"),
                    "closed": r[9] == "closed", "entry_ref": r[10], "stop": r[11]})
    return out


def trend15(conn: sqlite3.Connection, trades: list[dict]) -> None:
    """The 15m Q-Trend direction at each trade's entry: its last trigger on a closed 15m candle."""
    flips: dict[str, list[tuple[int, str]]] = {}
    for sym, side, t in conn.execute("SELECT symbol, side, trigger_time FROM setups WHERE variant_id = ? AND timeframe = '15m'"
                                     " ORDER BY trigger_time", (BASELINE,)):
        flips.setdefault(sym, []).append((t + 900_000, side))
    for tr in trades:
        last = None
        for known, side in flips.get(tr["symbol"], []):
            if known > tr["entry"]:
                break
            last = side
        tr["t15"] = last


def price_r(conn: sqlite3.Connection, t: dict, at: int) -> float | None:
    row = conn.execute("SELECT open FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time >= ?"
                       " ORDER BY open_time LIMIT 1", (t["symbol"], at)).fetchone()
    if row is None:
        return None
    sign = 1 if t["side"] == "long" else -1
    return sign * (row[0] - t["entry_ref"]) / abs(t["entry_ref"] - t["stop"]) - t["cost"]


def against_h1(t: dict) -> bool:
    return (t["side"] == "long" and t["h1"] == "bear") or (t["side"] == "short" and t["h1"] == "bull")


def against_15(t: dict) -> bool:
    return t["tf"] == "5m" and t["t15"] is not None and t["t15"] != t["side"]


SKIP = {  # entry filters: True = the trade is not taken
    "S1 15m decides (5m only with the 15m trend)": against_15,
    "B1 only A trades": lambda t: t["q"] == "B",
    "B2 skip B without a squeeze release": lambda t: t["q"] == "B" and t["sqz"] is not True,
    "B3 skip B against the 1h trend": lambda t: t["q"] == "B" and against_h1(t),
    "B4 skip B 5m against the 15m trend": lambda t: t["q"] == "B" and against_15(t),
}


def apply(conn: sqlite3.Connection, trades: list[dict], rule: str) -> list[dict]:
    """The trades as the rule takes them: a list of {entry, exit, r, q, ...} (closed trades only in the result)."""
    if rule in SKIP:
        return [dict(t) for t in trades if not SKIP[rule](t)]
    out: list[dict] = []
    active: dict[str, list[dict]] = {}  # per coin, positions that may still be open (sorted input: prune by exit)
    for t in trades:
        cur = dict(t)
        live = [o for o in active.get(t["symbol"], []) if o["exit"] > t["entry"]]
        active[t["symbol"]] = live
        open_opp = [o for o in live if o["side"] != t["side"] and o["entry"] < t["entry"] < o["exit"]]
        if rule == "S4 S3 + no new B against an open A" and t["q"] == "B" and any(o["q"] == "A" for o in open_opp):
            continue
        for o in open_opp:
            if rule == "S2 newest wins (one direction per coin)" or (rule.startswith(("S3", "S4")) and o["q"] == "B"):
                r = price_r(conn, o, t["entry"])
                if r is not None:
                    o["r"], o["exit"], o["closed"] = r, t["entry"], True
        out.append(cur)
        active[t["symbol"]].append(cur)
    return out


RULES = ["S0 now (every signal)", "S1 15m decides (5m only with the 15m trend)", "S2 newest wins (one direction per coin)",
         "S3 close the older B on an opposite signal", "S4 S3 + no new B against an open A",
         "B1 only A trades", "B2 skip B without a squeeze release", "B3 skip B against the 1h trend",
         "B4 skip B 5m against the 15m trend"]


def account(taken: list[dict]) -> tuple[float, float]:
    """Today's demo rules on these trades: A 3% / B 2% of the balance, open risk at most 12% (a trade is made smaller,
    or skipped below 0.1%). Returns the final balance of $150 and the max drawdown."""
    events = []
    for i, t in enumerate(taken):
        if t["closed"]:
            events.append((t["entry"], 1, i))
            events.append((t["exit"], 0, i))
    events.sort()
    bal, peak, dd, open_risk = 150.0, 150.0, 0.0, {}
    for _, kind, i in events:
        t = taken[i]
        if kind == 1:
            room = 0.12 * bal - sum(open_risk.values())
            risk = min(bal * (0.03 if t["q"] == "A" else 0.02), room)
            if risk > 0.001 * bal:
                open_risk[i] = risk
        elif i in open_risk:
            bal += open_risk.pop(i) * t["r"]
            peak = max(peak, bal)
            dd = max(dd, 1 - bal / peak)
    return bal, dd


def report(name: str, conn: sqlite3.Connection, trades: list[dict], quality_ok: bool) -> None:
    trend15(conn, trades)
    closed_all = [t for t in trades if t["closed"]]
    mid = closed_all[len(closed_all) // 2]["entry"]
    print(f"\n== {name}: {len(closed_all)} closed trades, {time.strftime('%Y-%m-%d', time.gmtime(closed_all[0]['entry'] / 1000))}"
          f" .. {time.strftime('%Y-%m-%d', time.gmtime(closed_all[-1]['entry'] / 1000))}"
          + ("" if quality_ok else "  (no quality tiers before 10-18: every older trade counts as B)"))
    print(f"   {'rule':46} {'trades':>6} {'R/trade':>8} {'half 1':>8} {'half 2':>8} {'total':>8} {'DD R':>6} | demo $150 at today's rules")
    base = None
    for rule in RULES:
        taken = [t for t in apply(conn, trades, rule) if t["closed"]]
        h1 = sum(t["r"] for t in taken if t["entry"] < mid)
        h2 = sum(t["r"] for t in taken if t["entry"] >= mid)
        cum = peak = dd = 0.0
        for t in sorted(taken, key=lambda x: x["exit"]):
            cum += t["r"]
            peak = max(peak, cum)
            dd = max(dd, peak - cum)
        bal, add = account(taken)
        if base is None:
            base = (h1, h2)
        mark = "  both halves better" if h1 > base[0] + 1e-9 and h2 > base[1] + 1e-9 else ""
        print(f"   {rule:46} {len(taken):6d} {(h1 + h2) / max(len(taken), 1):+8.3f} {h1:+8.1f} {h2:+8.1f} {h1 + h2:+8.1f}"
              f" {dd:6.1f} | ${bal:7.2f} ({bal / 150 - 1:+5.0%}) DD {add:5.1%}{mark}")


def main() -> None:
    conn = sqlite3.connect(f"file:{PAST}?mode=ro", uri=True)
    report("PAST v6 charts (taken signals)", conn, load(conn, 1), True)
    report("REPLICATION: v6 signals skipped by the 1.5% minimum stop, as if taken", conn, load(conn, 0), True)
    conn.close()
    conn = sqlite3.connect(f"file:{LIVE}?mode=ro", uri=True)
    started = conn.execute("SELECT started_at FROM account_state WHERE account = 'paper'").fetchone()[0]
    report("FORWARD demo signals", conn, load(conn, 1, started), False)
    conn.close()


if __name__ == "__main__":
    main()
