"""Tests S1-S4 of research/notes/2026-10-20-supertrend-plan.md. Study values: data/research/st_tests.db (TradingView);
trades and 1m candles: the live journal (XRP, SOL, ETH) and data/research/st_candles.db (DOGE, LTC). Read-only.

    .venv\\Scripts\\python -I research\\tools\\st_tests.py
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
from tradeagent.sim.simulator import Costs, close_now, open_trade, results, step  # noqa: E402

M, H = 60_000, 3_600_000
TF = {"5m": 5 * M, "15m": 15 * M}
SQZ_ON, SQZ_OFF = 5.0, 6.0  # palette codes: 5 = squeeze on (narrower candles), 6 = off
settings = load_settings(ROOT)
COSTS = Costs(settings.costs.maker_fee, settings.costs.taker_fee, settings.costs.slippage)
live = sqlite3.connect(f"file:{settings.resolve(settings.journal.path)}?mode=ro", uri=True)
extra = sqlite3.connect(f"file:{ROOT / 'data' / 'research' / 'st_candles.db'}?mode=ro", uri=True)
stdb = sqlite3.connect(f"file:{ROOT / 'data' / 'research' / 'st_tests.db'}?mode=ro", uri=True)
CANDLES = {"XRP": live, "SOL": live, "ETH": live, "DOGE": extra, "LTC": extra}


class Chart:
    """One coin and timeframe: bars as tuples (time, o, h, l, c, up, down, buy, sell, dema, wt1, wt2, sqz, sqz_color)."""

    def __init__(self, symbol: str, tf: str) -> None:
        self.rows = stdb.execute("SELECT time, o, h, l, c, st_up, st_down, st_buy, st_sell, dema, wt1, wt2, sqz, sqz_color"
                                 " FROM bars WHERE symbol = ? AND tf = ? ORDER BY time", (symbol, tf)).fetchall()
        self.times = [r[0] for r in self.rows]

    def index(self, t: int) -> int | None:
        i = bisect.bisect_left(self.times, t)
        return i if i < len(self.times) and self.times[i] == t else None

    def last_closed(self, t: int, step_ms: int) -> int | None:
        i = bisect.bisect_right(self.times, t - step_ms) - 1
        return i if i >= 0 else None

    @staticmethod
    def direction(row: tuple) -> str | None:
        return "long" if row[5] is not None else "short" if row[6] is not None else None


_charts: dict[tuple[str, str], Chart] = {}


def chart(symbol: str, tf: str) -> Chart:
    if (symbol, tf) not in _charts:
        _charts[(symbol, tf)] = Chart(symbol, tf)
    return _charts[(symbol, tf)]


def run_trade(symbol: str, side: str, entry_time: int, price: float, stop: float, *, target_r: float | None,
              limit: bool, exit_at: int | None = None, max_ms: int = 72 * H, partial_r: float | None = None) -> dict | None:
    sign = 1 if side == "long" else -1
    if sign * (price - stop) <= 0:
        return None
    if partial_r is not None:
        state = open_trade(side=side, mode="hybrid", entry_time=entry_time, entry_ref=price, stop=stop, take_profit_r=1.5,
                           partial_r=partial_r, partial_fraction=0.5, trail_lookback=3, costs=COSTS, limit_entry=limit)
    else:
        state = open_trade(side=side, mode="fixed", entry_time=entry_time, entry_ref=price, stop=stop,
                           take_profit_r=target_r if target_r else 1000.0, partial_r=1.0, partial_fraction=0.5,
                           trail_lookback=3, costs=COSTS, limit_entry=limit)
    end = entry_time + max_ms
    for c in CANDLES[symbol].execute("SELECT open_time, open, high, low, close FROM candles WHERE symbol = ? AND timeframe = '1m'"
                                     " AND open_time >= ? AND open_time <= ? ORDER BY open_time", (symbol, entry_time, end)):
        if (exit_at is not None and c[0] >= exit_at) or c[0] >= end:
            close_now(state, c[0], c[1], COSTS, "exit")
            break
        step(state, c, COSTS)
        if state.closed:
            break
    if not state.closed:
        return None
    return {"symbol": symbol, "entry": entry_time, "exit": state.last_time, "r": results(state, COSTS)["r_net"]}


def entry_minute(symbol: str, t: int) -> tuple | None:
    return CANDLES[symbol].execute("SELECT open, high, low FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time = ?",
                                   (symbol, t)).fetchone()


def stats(rs: list[float]) -> str:
    if not rs:
        return "no trades"
    wins, losses = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    pf = f"{wins / losses:.2f}" if losses else "-"
    return f"n={len(rs):4d} win={sum(r > 0 for r in rs) / len(rs):.0%} exp={st.mean(rs):+.3f}R PF={pf}"


def halves(ts: list[dict]) -> tuple[float, float]:
    ts = sorted(ts, key=lambda t: t["entry"])
    mid = ts[len(ts) // 2]["entry"]
    a, b = [t["r"] for t in ts if t["entry"] < mid], [t["r"] for t in ts if t["entry"] >= mid]
    return (st.mean(a) if a else 0.0), (st.mean(b) if b else 0.0)


def pf(rs: list[float]) -> float:
    losses = -sum(r for r in rs if r < 0)
    return sum(r for r in rs if r > 0) / losses if losses else 0.0


# ---------------------------------------------------------------------------------------------- S1
def s1() -> None:
    print("== S1: quality flags on the agent's trades (XRP, SOL, ETH)")
    results_by = {}
    for taken, label in ((1, "taken"), (0, "skipped")):
        trades = live.execute("""SELECT t.symbol, t.timeframe, t.side, t.confirm_time, t.entry_time, t.r_net FROM trades t
            JOIN variants v ON v.id = t.variant_id WHERE v.role = 'baseline' AND t.status = 'closed'
            AND t.symbol IN ('XRP', 'SOL', 'ETH') AND (t.taken = 1 AND ? = 1 OR t.taken = 0 AND t.reason = 'min_stop_pct' AND ? = 0)
            ORDER BY t.entry_time""", (taken, taken)).fetchall()
        rows = []
        for symbol, tf, side, confirm, entry, r in trades:
            ch = chart(symbol, tf)
            i = ch.index(confirm)
            if i is None or i < 6:
                continue
            sign = 1 if side == "long" else -1
            bar = ch.rows[i]
            recent = ch.rows[i - 5:i + 1]
            flags = {
                "ST_with": Chart.direction(bar) == side,
                "ST_fresh": any((b[7] if sign > 0 else b[8]) == 1 for b in recent),
                "WT_extreme": any(b[10] is not None and sign * b[10] <= -53 for b in recent),
                "SQZ_fire": any(ch.rows[k - 1][13] == SQZ_ON and ch.rows[k][13] == SQZ_OFF for k in range(i - 5, i + 1))
                            and bar[12] is not None and sign * bar[12] > 0,
                "DEMA_with": bar[9] is not None and sign * (bar[4] - bar[9]) > 0,
            }
            if tf == "5m":
                c15 = chart(symbol, "15m")
                j = c15.last_closed(confirm + TF["5m"], TF["15m"])
                flags["ST15_with"] = j is not None and Chart.direction(c15.rows[j]) == side
            rows.append((entry, r, flags))
        results_by[label] = rows
        print(f"   {label}: {len(rows)} trades with study values")
    verdicts = []
    for flag in ("ST_with", "ST15_with", "ST_fresh", "WT_extreme", "SQZ_fire", "DEMA_with"):
        out = {}
        print(f"   -- {flag}")
        for label in ("taken", "skipped"):
            rows = [x for x in results_by[label] if flag in x[2]]
            mid = rows[len(rows) // 2][0]
            diffs, ns = [], []
            for part in ([x for x in rows if x[0] < mid], [x for x in rows if x[0] >= mid]):
                yes = [x[1] for x in part if x[2][flag]]
                no = [x[1] for x in part if not x[2][flag]]
                if yes and no:
                    diffs.append(st.mean(yes) - st.mean(no))
                    ns.append(min(len(yes), len(no)))
            yes_all = [x[1] for x in rows if x[2][flag]]
            no_all = [x[1] for x in rows if not x[2][flag]]
            print(f"      {label:7} flag {stats(yes_all)} | other {stats(no_all)} | halves {[round(d, 3) for d in diffs]}")
            out[label] = (diffs, min(ns) if ns else 0)
        (td, tn), (sd, sn) = out["taken"], out["skipped"]
        same = len(td) == 2 and len(sd) == 2 and all((d > 0) == (td[0] > 0) for d in td + sd)
        t_size = len(td) == 2 and all(abs(d) >= 0.15 for d in td) and (td[0] > 0) == (td[1] > 0)
        t_full = t_size and tn >= 25
        s_full = len(sd) == 2 and all(abs(d) >= 0.15 for d in sd) and sn >= 25 and (sd[0] > 0) == (sd[1] > 0)
        verdict = "PASS" if t_full and same else "PROMISING" if t_size and s_full and same else "no"
        sign = "better" if td and td[0] > 0 else "worse"
        verdicts.append(f"{flag}: {verdict} (flag trades {sign})")
    print("   verdicts:", "; ".join(verdicts))


# ---------------------------------------------------------------------------------------------- S2
def s2() -> None:
    print("\n== S2: video 2 stand-alone (15m: Supertrend 12/3 flip + DEMA 200, exit on the opposite flip)")
    all_trades = []
    for symbol in ("XRP", "SOL", "ETH", "DOGE", "LTC"):
        ch, trades, busy = chart(symbol, "15m"), [], 0
        for i in range(1, len(ch.rows)):
            p, b = ch.rows[i - 1], ch.rows[i]
            if b[9] is None or p[9] is None:
                continue
            side = None
            if (b[7] == 1 and b[4] > b[9]) or (Chart.direction(b) == "long" and p[4] <= p[9] < b[4] and b[4] > b[9]):
                side = "long"
            elif (b[8] == 1 and b[4] < b[9]) or (Chart.direction(b) == "short" and p[4] >= p[9] > b[4]):
                side = "short"
            decision = b[0] + TF["15m"]
            if side is None or decision < busy:
                continue
            exit_at = next((r[0] + TF["15m"] for r in ch.rows[i + 1:] if (r[8] if side == "long" else r[7]) == 1), None)
            em = entry_minute(symbol, decision)
            stop = b[5] if side == "long" else b[6]
            if em is None or stop is None or exit_at is None:
                continue
            t = run_trade(symbol, side, decision, em[0], stop, target_r=None, limit=False, exit_at=exit_at, max_ms=14 * 24 * H)
            if t:
                trades.append(t)
                busy = t["exit"] + M
        all_trades += trades
        h = halves(trades) if trades else (0, 0)
        print(f"   {symbol:5} {stats([t['r'] for t in trades])} halves {h[0]:+.3f} / {h[1]:+.3f}")
    cur = [t for t in all_trades if t["symbol"] in ("XRP", "SOL", "ETH")]
    rs = [t["r"] for t in all_trades]
    h = halves(all_trades)
    ok = st.mean(rs) >= 0.15 and pf(rs) >= 1.3 and h[0] > 0 and h[1] > 0 and st.mean([t["r"] for t in cur]) > 0
    print(f"   all   {stats(rs)} halves {h[0]:+.3f} / {h[1]:+.3f} -> {'PASS' if ok else 'no'}")


# ---------------------------------------------------------------------------------------------- S3
def s3() -> None:
    print("\n== S3: Supertrend exits on the agent's taken trades (same entries and stops)")
    trades = live.execute("""SELECT t.symbol, t.timeframe, t.side, t.confirm_time, t.entry_time, t.entry_ref, t.stop_initial
        FROM trades t JOIN variants v ON v.id = t.variant_id WHERE v.role = 'baseline' AND t.taken = 1 AND t.status = 'closed'
        AND t.symbol IN ('XRP', 'SOL', 'ETH') ORDER BY t.entry_time""").fetchall()
    base, trail, runner = [], [], []
    for symbol, tf, side, confirm, entry, price, stop in trades:
        ch = chart(symbol, tf)
        i = ch.index(confirm)
        if i is None:
            continue
        with_trade, exit_at = Chart.direction(ch.rows[i]) == side, None
        for r in ch.rows[i + 1:]:
            d = Chart.direction(r)
            if d == side:
                with_trade = True
            elif with_trade and d is not None:
                exit_at = r[0] + TF[tf]
                break
        b = run_trade(symbol, side, entry, price, stop, target_r=1.5, limit=True)
        a = run_trade(symbol, side, entry, price, stop, target_r=None, limit=True, exit_at=exit_at)
        c = run_trade(symbol, side, entry, price, stop, target_r=None, limit=True, exit_at=exit_at, partial_r=1.5)
        if b and a and c:
            base.append(b), trail.append(a), runner.append(c)
    for name, ts in (("1.5R target (re-simulated)", base), ("S3a trail: exit on the flip", trail), ("S3b half at 1.5R + runner", runner)):
        h = halves(ts)
        print(f"   {name:30} {stats([t['r'] for t in ts])} halves {h[0]:+.3f} / {h[1]:+.3f}")
    hb = halves(base)
    for name, ts in (("S3a", trail), ("S3b", runner)):
        h = halves(ts)
        ok = h[0] - hb[0] >= 0.10 and h[1] - hb[1] >= 0.10
        print(f"   {name}: vs target by half {h[0] - hb[0]:+.3f} / {h[1] - hb[1]:+.3f} -> {'PASS' if ok else 'no'}")


# ---------------------------------------------------------------------------------------------- S4
def s4() -> None:
    print("\n== S4: Supertrend band touch (stop: 10-candle swing >= 1.5%, target 1.5R, limit entry)")
    all_trades = []
    for symbol, tf in (("XRP", "5m"), ("XRP", "15m"), ("SOL", "5m"), ("SOL", "15m"), ("ETH", "5m"), ("ETH", "15m"),
                       ("DOGE", "15m"), ("LTC", "15m")):
        ch, trades, busy = chart(symbol, tf), [], 0
        for i in range(10, len(ch.rows)):
            b = ch.rows[i]
            d = Chart.direction(b)
            if d == "long":
                line = b[5]
                ok = b[3] <= line * 1.002 and b[4] > line and b[4] > b[1]
            elif d == "short":
                line = b[6]
                ok = b[2] >= line * 0.998 and b[4] < line and b[4] < b[1]
            else:
                ok = False
            decision = b[0] + TF[tf]
            if not ok or decision < busy:
                continue
            window = ch.rows[i - 9:i + 1]
            stop = min(r[3] for r in window) if d == "long" else max(r[2] for r in window)
            em = entry_minute(symbol, decision)
            if em is None:
                continue
            price = em[0]
            if abs(price - stop) / price < 0.015 or not (em[2] < price if d == "long" else em[1] > price):
                continue
            t = run_trade(symbol, d, decision, price, stop, target_r=1.5, limit=True)
            if t:
                trades.append(t)
                busy = t["exit"] + M
        all_trades += [dict(t, tf=tf) for t in trades]
        print(f"   {symbol:5} {tf:4} {stats([t['r'] for t in trades])}")
    cur = [t for t in all_trades if t["symbol"] in ("XRP", "SOL", "ETH")]
    rs = [t["r"] for t in all_trades]
    if rs:
        h = halves(all_trades)
        ok = st.mean(rs) >= 0.15 and pf(rs) >= 1.3 and h[0] > 0 and h[1] > 0 and cur and st.mean([t["r"] for t in cur]) > 0
        print(f"   all   {stats(rs)} halves {h[0]:+.3f} / {h[1]:+.3f} -> {'PASS' if ok else 'no'}")


if __name__ == "__main__":
    s1()
    s2()
    s3()
    s4()
