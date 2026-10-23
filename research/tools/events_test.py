r"""US macro events (FOMC, and the 8:30 New York releases such as CPI and jobs data) on 4 years of data, and what
they do to the planned design's trades (the user, 2026-10-21). Research only.

    .venv\Scripts\python -u research\tools\events_test.py

- FOMC: the statement days (14:00 New York time), from the Fed's published calendars, 2022-11 .. 2026-09.
- 8:30 news days: found in the data. A day counts when BTC's 1m candle at 8:30 New York time is at least 4 times
  the median of that minute over the surrounding 30 days (CPI, jobs data, PPI, retail sales, GDP and PCE all come
  out at that minute; the market decides which ones matter).
- Market behaviour: the range of the hour after the event against the same hour on normal days, how often the price
  ran at least 0.5% both ways within that hour (wicks both sides), and how often the first 15 minutes pointed the
  wrong way for the next 4 hours.
- The planned design (15m signals, 5m dip entry, max 2 a coin, opposite skipped, max 5; the agent's own engine on
  the validation copy data/research/long4/validate.db): trades that were open over an event, and rules that keep
  away from events, in R and as the demo account (A 3% / B 2%, 12% budget, $150).
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import statistics as st
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
DB = ROOT / "data" / "research" / "long4" / "validate.db"
NY = ZoneInfo("America/New_York")
M1, H = 60_000, 3_600_000
COINS = ["BTC", "XRP", "SOL", "ETH"]

FOMC = """2022-11-02 2022-12-14 2023-02-01 2023-03-22 2023-05-03 2023-06-14 2023-07-26 2023-09-20 2023-11-01 2023-12-13
2024-01-31 2024-03-20 2024-05-01 2024-06-12 2024-07-31 2024-09-18 2024-11-07 2024-12-18 2025-01-29 2025-03-19 2025-05-07
2025-06-18 2025-07-30 2025-09-17 2025-10-29 2025-12-10 2026-01-28 2026-03-18 2026-04-29 2026-06-17 2026-07-29 2026-09-16""".split()


def ny_ms(day: str, hh: int, mm: int) -> int:
    t = datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}").replace(tzinfo=NY)
    return int(t.astimezone(timezone.utc).timestamp() * 1000)


def candle(conn, coin: str, t: int):
    return conn.execute("SELECT open, high, low, close FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time = ?",
                        (coin, t)).fetchone()


def window(conn, coin: str, start: int, minutes: int):
    return conn.execute("SELECT open_time, open, high, low, close FROM candles WHERE symbol = ? AND timeframe = '1m'"
                        " AND open_time >= ? AND open_time < ? ORDER BY open_time", (coin, start, start + minutes * M1)).fetchall()


def news_days(conn) -> list[str]:
    """Weekdays whose 8:30 New York 1m BTC candle is at least 4x the median of that minute in the 30 days around."""
    first = datetime(2022, 10, 1)
    days, ranges = [], {}
    d = first
    while d < datetime(2026, 10, 18):
        if d.weekday() < 5:
            day = d.strftime("%Y-%m-%d")
            c = candle(conn, "BTC", ny_ms(day, 8, 30))
            if c:
                ranges[day] = (c[1] - c[2]) / c[0]
        d += timedelta(days=1)
    keys = sorted(ranges)
    for i, day in enumerate(keys):
        around = [ranges[k] for k in keys[max(0, i - 15):i + 16] if k != day]
        if around and ranges[day] >= 4 * st.median(around) and ranges[day] >= 0.002:
            days.append(day)
    return days


def behaviour(conn, events: list[int], normal: dict[int, list[int]]) -> dict:
    out = {}
    for coin in COINS:
        rng, rng_normal, both, fake, moves = [], [], 0, 0, []
        for t in events:
            w = window(conn, coin, t, 240)
            if len(w) < 200:
                continue
            p0 = w[0][1]
            hour = w[:60]
            hi, lo = max(c[2] for c in hour), min(c[3] for c in hour)
            rng.append((hi - lo) / p0)
            if hi / p0 - 1 >= 0.005 and 1 - lo / p0 >= 0.005:
                both += 1
            r15, r4h = w[14][4] / p0 - 1, w[-1][4] / p0 - 1
            moves.append(abs(r4h))
            if r15 * r4h < 0 and abs(r4h) >= 0.005:
                fake += 1
            base = []
            for tn in normal[t]:
                wn = window(conn, coin, tn, 60)
                if len(wn) >= 55:
                    base.append((max(c[2] for c in wn) - min(c[3] for c in wn)) / wn[0][1])
            if base:
                rng_normal.append(st.median(base))
        n = len(rng)
        out[coin] = {"events": n, "range": st.median(rng) if rng else None, "normal": st.median(rng_normal) if rng_normal else None,
                     "both_sides": both / n if n else None, "fakeout": fake / n if n else None,
                     "move_4h": st.median(moves) if moves else None}
    return out


def normal_hours(events: list[int], all_events: set[int]) -> dict[int, list[int]]:
    """The same clock time on the 10 weekdays before each event that had no event."""
    out = {}
    for t in events:
        picks, k = [], 1
        while len(picks) < 10 and k < 40:
            tn = t - k * 86_400_000
            if datetime.fromtimestamp(tn / 1000, timezone.utc).weekday() < 5 and all(abs(tn - e) > 3 * H for e in all_events):
                picks.append(tn)
            k += 1
        out[t] = picks
    return out


def design_trades(conn) -> list[dict]:
    """The planned design through the demo account with the user's rules; the trades it took, with their shadow R."""
    spec = importlib.util.spec_from_file_location("long_data", HERE / "long_data.py")
    ld = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ld)
    ld.use_4y()
    from tradeagent.account.engine import AccountEngine, reset_account
    from tradeagent.journal import connect

    jc = connect(DB)
    vid = jc.execute("SELECT DISTINCT variant_id FROM trades WHERE variant_id LIKE 'v0-%'").fetchone()[0]
    with jc:
        jc.execute("UPDATE variants SET role = CASE id WHEN ? THEN 'baseline' ELSE 'challenger' END", (vid,))
        jc.execute("DELETE FROM engine_state")
    s = ld.long_settings(["XRP", "SOL", "ETH"])
    pa = s.paper_account
    pa.starting_balance, pa.risk_per_trade, pa.risk_tier_a, pa.max_open_risk = 150.0, 0.02, 0.03, 0.12
    pa.max_positions, pa.max_positions_per_coin, pa.allow_opposite, pa.first_position_always = 5, 2, False, True
    pa.daily_loss_stop, pa.symbols, pa.leverage_cap, pa.drawdown_brake = None, ["XRP", "SOL", "ETH"], 10, None
    reset_account(jc, s)
    AccountEngine(s, jc).process()
    rows = jc.execute("SELECT t.id, t.symbol, t.side, t.entry_time, t.exit_time, t.r_net, t.r_gross, t.entry_ref, t.stop_initial,"
                      " t.context_json FROM account_trades a JOIN trades t ON t.id = a.trade_id"
                      " WHERE a.account = 'paper' AND a.status = 'closed' ORDER BY t.entry_time").fetchall()
    jc.close()
    return [{"id": r[0], "symbol": r[1], "side": r[2], "entry": r[3], "exit": r[4], "r": r[5], "cost": (r[6] - r[5]),
             "entry_ref": r[7], "stop": r[8], "q": json.loads(r[9] or "{}").get("quality") or "B"} for r in rows]


def r_at(conn, t: dict, at: int) -> float | None:
    row = conn.execute("SELECT open FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time >= ? ORDER BY open_time LIMIT 1",
                       (t["symbol"], at)).fetchone()
    if row is None:
        return None
    sign = 1 if t["side"] == "long" else -1
    return sign * (row[0] - t["entry_ref"]) / abs(t["entry_ref"] - t["stop"]) - t["cost"]


def account(trades: list[dict]) -> tuple[float, float]:
    ev = []
    for i, t in enumerate(trades):
        ev += [(t["entry"], 1, i), (t["exit"], 0, i)]
    ev.sort()
    bal = peak = 150.0
    dd, open_ = 0.0, {}
    for _, kind, i in ev:
        t = trades[i]
        if kind == 1:
            room = 0.12 * bal - sum(open_.values())
            risk = min(bal * (0.03 if t["q"] == "A" else 0.02), room)
            if risk > 0.001 * bal:
                open_[i] = risk
        elif i in open_:
            bal += open_.pop(i) * t["r"]
            peak = max(peak, bal)
            dd = max(dd, 1 - bal / peak)
    return bal, dd


def main() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    news = news_days(conn)
    fomc_t = [ny_ms(d, 14, 0) for d in FOMC]
    news_t = [ny_ms(d, 8, 30) for d in news if d not in FOMC]
    all_t = set(fomc_t) | set(news_t)
    by_year = {}
    for d in news:
        by_year[d[:4]] = by_year.get(d[:4], 0) + 1
    print(f"FOMC statement days: {len(fomc_t)} (2022-11 .. 2026-09)")
    print(f"8:30 New York news days found in the data: {len(news_t)} | by year {by_year}")
    print("   the 12 biggest 8:30 candles:", ", ".join(sorted(news, key=lambda d: -(lambda c: (c[1] - c[2]) / c[0])(candle(conn, 'BTC', ny_ms(d, 8, 30))))[:12]))

    print("\n== MARKET BEHAVIOUR in the hour after the event (median; 'normal' = the same hour on 10 quiet weekdays before)")
    for label, events in (("FOMC 14:00", fomc_t), ("8:30 news", news_t)):
        b = behaviour(conn, events, normal_hours(events, all_t))
        print(f"   {label}:")
        for coin, m in b.items():
            print(f"      {coin:4} {m['events']:3d} events | 1-hour range {m['range']:.2%} vs normal {m['normal']:.2%}"
                  f" (x{m['range'] / m['normal']:.1f}) | ran 0.5%+ both ways {m['both_sides']:.0%} | first 15 min pointed the"
                  f" wrong way {m['fakeout']:.0%} | 4-hour move {m['move_4h']:.2%}")

    trades = design_trades(conn)
    mid = trades[len(trades) // 2]["entry"]
    print(f"\n== THE PLANNED DESIGN: {len(trades)} trades the demo account took (XRP/SOL/ETH, 4 years)")

    def stats(label: str, sel: list[dict]) -> str:
        if not sel:
            return f"   {label:52} none"
        rs = [t["r"] for t in sel]
        return (f"   {label:52} {len(sel):5d} trades | won {sum(r > 0 for r in rs) / len(rs):4.0%} | stopped"
                f" {sum(r <= -0.9 for r in rs) / len(rs):4.0%} | {st.mean(rs):+.3f}R a trade")

    def over(t: dict, events: list[int]) -> bool:
        return any(t["entry"] < e < t["exit"] for e in events)

    def near(t: dict, events: list[int], before: int, after: int) -> bool:
        return any(e - before <= t["entry"] < e + after for e in events)

    print(stats("all", trades))
    print(stats("open over an FOMC statement", [t for t in trades if over(t, fomc_t)]))
    print(stats("open over an 8:30 news release", [t for t in trades if over(t, news_t)]))
    print(stats("open over no event", [t for t in trades if not over(t, fomc_t + news_t)]))
    print(stats("entered within 1 h before or after FOMC", [t for t in trades if near(t, fomc_t, H, H)]))
    print(stats("entered within 1 h before or after 8:30 news", [t for t in trades if near(t, news_t, H, H)]))

    def close_before(sel: list[dict], events: list[int], minutes: int) -> list[dict]:
        out = []
        for t in sel:
            e = next((e for e in sorted(events) if t["entry"] < e - minutes * M1 < t["exit"]), None)
            if e is not None:
                r = r_at(conn, t, e - minutes * M1)
                if r is not None:
                    t = {**t, "r": r, "exit": e - minutes * M1}
            out.append(t)
        return out

    rules = {
        "R0 now (no event rule)": trades,
        "R1 no new entry 1 h before to 1 h after FOMC": [t for t in trades if not near(t, fomc_t, H, H)],
        "R2 no new entry 1 h before to 1 h after FOMC and 8:30 news": [t for t in trades if not near(t, fomc_t + news_t, H, H)],
        "R3 R1 + close open trades 15 min before FOMC": close_before([t for t in trades if not near(t, fomc_t, H, H)], fomc_t, 15),
        "R4 R2 + close open trades 15 min before every event": close_before(
            [t for t in trades if not near(t, fomc_t + news_t, H, H)], fomc_t + news_t, 15),
        "R5 no new entry 4 h before to 2 h after FOMC": [t for t in trades if not near(t, fomc_t, 4 * H, 2 * H)],
    }
    print("\n== RULES (R in shadow terms; the demo account at A 3% / B 2%, 12% budget, $150, on the same trades)")
    base = None
    for name, sel in rules.items():
        rs = [t["r"] for t in sel]
        h1 = sum(t["r"] for t in sel if t["entry"] < mid)
        h2 = sum(t["r"] for t in sel if t["entry"] >= mid)
        bal, dd = account(sel)
        base = base or (h1, h2)
        print(f"   {name:58} {len(sel):5d} trades {st.mean(rs):+.3f}R | half 1 {h1:+6.1f}R half 2 {h2:+6.1f}R |"
              f" $150 -> ${bal:,.0f} ({bal / 150 - 1:+.0%}) max DD {dd:.1%}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
