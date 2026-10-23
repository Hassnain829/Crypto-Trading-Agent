"""One decision per coin from the 5m and 15m signals (research/notes/2026-10-20-one-position-plan.md).

    .venv\\Scripts\\python -u research\\tools\\one_position_test.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("coordination_test", HERE / "coordination_test.py")
ct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ct)


def score(t: dict) -> int:
    return (2 if t["q"] == "A" else 0) + (1 if t["sqz"] is True else 0)


POLICIES = {
    "P0 now (every signal)": None,
    "D1 no duplicates": "D1",
    "D2 no duplicates + an opposite closes an older B": "D2",
    "P1 one per coin, the first wins": "P1",
    "P2 one per coin, the newest wins": "P2",
    "P3 one per coin, the better wins": "P3",
    "P4 P3 + a better duplicate replaces": "P4",
}


def close_at(conn: sqlite3.Connection, o: dict, at: int) -> None:
    r = ct.price_r(conn, o, at)
    if r is not None:
        o["r"], o["exit"], o["closed"] = r, at, True


def run(conn: sqlite3.Connection, trades: list[dict], policy: str | None) -> list[dict]:
    order = sorted(trades, key=lambda t: (t["entry"], -score(t), t["tf"] != "15m", t["id"]))
    out: list[dict] = []
    active: dict[str, list[dict]] = {}  # per coin, positions that may still be open (sorted input: prune by exit)

    def take(cur: dict) -> None:
        out.append(cur)
        active.setdefault(cur["symbol"], []).append(cur)

    for t in order:
        cur = dict(t)
        if policy is None:
            out.append(cur)
            continue
        live = [o for o in active.get(t["symbol"], []) if o["exit"] > t["entry"] or o["entry"] == t["entry"]]
        active[t["symbol"]] = live
        open_pos = [o for o in live if o["entry"] < t["entry"] < o["exit"] or o["entry"] == t["entry"]]
        same = [o for o in open_pos if o["side"] == t["side"]]
        opp = [o for o in open_pos if o["side"] != t["side"]]
        if policy in ("D1", "D2"):
            if same:
                continue
            if policy == "D2":
                for o in opp:
                    if o["q"] == "B":
                        close_at(conn, o, t["entry"])
            take(cur)
            continue
        if not open_pos:
            take(cur)
            continue
        if policy == "P1":
            continue
        held = open_pos[0]  # one position per coin, so at most one is open
        if held["side"] == t["side"]:
            if policy == "P4" and score(t) > score(held):
                close_at(conn, held, t["entry"])
                take(cur)
            continue
        if policy == "P2" or score(t) >= score(held):
            close_at(conn, held, t["entry"])
            take(cur)
        # P3/P4: the open position scores higher, so the new opposite signal is skipped
    return out


def both_stopped(taken: list[dict]) -> int:
    n = 0
    by_coin: dict[str, list[dict]] = {}
    for t in sorted(taken, key=lambda x: x["entry"]):
        live = [o for o in by_coin.get(t["symbol"], []) if o["exit"] > t["entry"]]
        for o in live:
            if o["side"] != t["side"] and o["entry"] < t["entry"] and t["closed"] and o["closed"] and t["r"] < -0.9 and o["r"] < -0.9:
                n += 1
        by_coin[t["symbol"]] = live + [t]
    return n


def report(name: str, conn: sqlite3.Connection, trades: list[dict], note: str = "") -> None:
    closed_all = [t for t in trades if t["closed"]]
    mid = closed_all[len(closed_all) // 2]["entry"]
    print(f"\n== {name}: {len(closed_all)} closed trades, {time.strftime('%Y-%m-%d', time.gmtime(closed_all[0]['entry'] / 1000))}"
          f" .. {time.strftime('%Y-%m-%d', time.gmtime(closed_all[-1]['entry'] / 1000))}{note}")
    # how often a signal arrives while the coin already has a position
    base = run(conn, trades, None)
    dup = [t for t in base if t["closed"] and any(o["symbol"] == t["symbol"] and o["side"] == t["side"]
                                                   and o["entry"] < t["entry"] < o["exit"] for o in base)]
    print(f"   duplicates (same direction already open on the coin): {len(dup)} trades,"
          f" {sum(t['r'] for t in dup) / max(len(dup), 1):+.3f}R a trade")
    print(f"   {'policy':48} {'trades':>6} {'R/trade':>8} {'half 1':>8} {'half 2':>8} {'total':>8} {'DD R':>6} {'both SL':>7} | demo $150 at today's rules")
    ref = None
    for pname, pol in POLICIES.items():
        taken = [t for t in run(conn, trades, pol) if t["closed"]]
        h1 = sum(t["r"] for t in taken if t["entry"] < mid)
        h2 = sum(t["r"] for t in taken if t["entry"] >= mid)
        cum = peak = dd = 0.0
        for t in sorted(taken, key=lambda x: x["exit"]):
            cum += t["r"]
            peak = max(peak, cum)
            dd = max(dd, peak - cum)
        bal, add = ct.account(taken)
        ref = ref or (h1, h2)
        mark = "  both halves better" if h1 > ref[0] + 1e-9 and h2 > ref[1] + 1e-9 else ""
        print(f"   {pname:48} {len(taken):6d} {(h1 + h2) / max(len(taken), 1):+8.3f} {h1:+8.1f} {h2:+8.1f} {h1 + h2:+8.1f}"
              f" {dd:6.1f} {both_stopped(taken):7d} | ${bal:7.2f} ({bal / 150 - 1:+5.0%}) DD {add:5.1%}{mark}")


def main() -> None:
    conn = sqlite3.connect(f"file:{ct.PAST}?mode=ro", uri=True)
    report("PAST v6 charts (taken signals)", conn, ct.load(conn, 1))
    report("REPLICATION: v6 signals skipped by the 1.5% minimum stop, as if taken", conn, ct.load(conn, 0))
    conn.close()
    conn = sqlite3.connect(f"file:{ct.LIVE}?mode=ro", uri=True)
    started = conn.execute("SELECT started_at FROM account_state WHERE account = 'paper'").fetchone()[0]
    report("FORWARD demo signals", conn, ct.load(conn, 1, started), "  (no tiers before 10-18: P3/P4 act like P2 there)")
    conn.close()


if __name__ == "__main__":
    main()
