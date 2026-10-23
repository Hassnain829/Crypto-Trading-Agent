"""Other ways to trade XRP, SOL, ETH and BTC (research/notes/2026-10-21-outside-plan.md). Research only.

    .venv\\Scripts\\python -u research\\tools\\outside_test.py data     # 1d and 4h candles and funding from 2020 (Binance)
    .venv\\Scripts\\python -u research\\tools\\outside_test.py run
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
DB = ROOT / "data" / "research" / "outside.db"
COINS = ["XRP", "SOL", "ETH", "BTC"]
DAY, H4 = 86_400_000, 14_400_000
START6, MID6, START4 = 1601510400000, 1696118400000, 1664582400000  # 2020-10-01, 2023-10-01, 2022-10-01
TAKER, SLIP = 0.0005, 0.0002


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def data() -> None:
    from tradeagent.venues import MarketData

    md = MarketData("binance-usdm", timeout_ms=30_000)
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS candles (symbol TEXT, tf TEXT, time INTEGER, open REAL, high REAL, low REAL,"
                 " close REAL, volume REAL, PRIMARY KEY (symbol, tf, time))")
    conn.execute("CREATE TABLE IF NOT EXISTS funding (symbol TEXT, time INTEGER, rate REAL, PRIMARY KEY (symbol, time))")
    since0 = 1577836800000  # 2020-01-01
    for coin in COINS:
        market = f"{coin}/USDT:USDT"
        for tf, step in (("1d", DAY), ("4h", H4)):
            start, n = since0, 0
            while start < time.time() * 1000 - step:
                rows = md.fetch_ohlcv(market, tf, since=start, limit=1500)
                if not rows:
                    break
                with conn:
                    conn.executemany("INSERT OR REPLACE INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                     [(coin, tf, int(r[0]), r[1], r[2], r[3], r[4], r[5]) for r in rows])
                n += len(rows)
                start = int(rows[-1][0]) + step
            print(f"{coin} {tf}: {n} candles", flush=True)
        start, n = since0, 0
        ex = md.exchange if hasattr(md, "exchange") else None
        while ex is not None and start < time.time() * 1000:
            rows = ex.fetch_funding_rate_history(market, since=start, limit=1000)
            if not rows:
                break
            with conn:
                conn.executemany("INSERT OR REPLACE INTO funding VALUES (?, ?, ?)",
                                 [(coin, int(r["timestamp"]), float(r["fundingRate"])) for r in rows])
            n += len(rows)
            start = int(rows[-1]["timestamp"]) + 1
            time.sleep(0.3)
        print(f"{coin} funding: {n}", flush=True)
    conn.close()


def bars(conn: sqlite3.Connection, coin: str, tf: str) -> list[tuple]:
    return conn.execute("SELECT time, open, high, low, close FROM candles WHERE symbol = ? AND tf = ? ORDER BY time",
                        (coin, tf)).fetchall()


def atr(rows: list[tuple], n: int = 20) -> list[float | None]:
    out, trs, prev = [], [], None
    for t, o, h, l, c in rows:
        tr = h - l if prev is None else max(h - l, abs(h - prev), abs(l - prev))
        trs.append(tr)
        prev = c
        out.append(sum(trs[-n:]) / n if len(trs) >= n else None)
    return out


def funding_sum(fund: list[tuple[int, float]], a: int, b: int) -> float:
    return sum(r for t, r in fund if a < t <= b)


def trend_trades(coin: str, rows: list[tuple], fund: list[tuple[int, float]], mode: str, sides: tuple[str, ...],
                 step: int) -> list[dict]:
    """Donchian (mode 'don') or SMA-100 (mode 'sma') trend trades on closed bars; entries and exits at the next open.
    1R = 2 x ATR(20) at the signal bar; that hard stop is checked on every bar's high/low."""
    a = atr(rows)
    out, pos = [], None
    closes = [r[4] for r in rows]
    for i in range(101, len(rows) - 1):
        t, o, h, l, c = rows[i]
        nxt = rows[i + 1]
        if pos is not None:  # hard stop inside this bar (the bar after the entry onwards)
            sign = 1 if pos["side"] == "long" else -1
            hit = l <= pos["stop"] if sign > 0 else h >= pos["stop"]
            if hit and t >= pos["entry"]:
                gap = (o <= pos["stop"]) if sign > 0 else (o >= pos["stop"])
                fill = (o if gap else pos["stop"]) * (1 - sign * SLIP)
                out.append(close(pos, fill, t + step // 2, fund))
                pos = None
                continue
        if mode == "don":
            hi20, lo20 = max(r[2] for r in rows[i - 20:i]), min(r[3] for r in rows[i - 20:i])
            hi10, lo10 = max(r[2] for r in rows[i - 10:i]), min(r[3] for r in rows[i - 10:i])
            want_long, want_short = c > hi20, c < lo20
            exit_long, exit_short = c < lo10, c > hi10
        else:
            sma = sum(closes[i - 99:i + 1]) / 100
            want_long, want_short = c > sma, c < sma
            exit_long, exit_short = c < sma, c > sma
        if pos is not None:
            if (pos["side"] == "long" and exit_long) or (pos["side"] == "short" and exit_short):
                sign = 1 if pos["side"] == "long" else -1
                out.append(close(pos, nxt[1] * (1 - sign * SLIP), nxt[0], fund))
                pos = None
        if pos is None and a[i]:
            side = "long" if want_long and "long" in sides else "short" if want_short and "short" in sides else None
            if side and t >= START6 - 101 * step:
                sign = 1 if side == "long" else -1
                entry = nxt[1] * (1 + sign * SLIP)
                pos = {"symbol": coin, "side": side, "entry": nxt[0], "entry_px": entry, "stop": entry - sign * 2 * a[i],
                       "risk": 2 * a[i]}
    return out


def close(pos: dict, fill: float, at: int, fund: list[tuple[int, float]]) -> dict:
    sign = 1 if pos["side"] == "long" else -1
    gross = sign * (fill - pos["entry_px"]) / pos["risk"]
    fees = 2 * TAKER * (pos["entry_px"] + fill) / 2 / pos["risk"]
    funding = sign * funding_sum(fund, pos["entry"], at) * pos["entry_px"] / pos["risk"]  # longs pay positive funding
    return {"symbol": pos["symbol"], "side": pos["side"], "entry": pos["entry"], "exit": at, "r": gross - fees - funding,
            "q": "B", "id": pos["entry"] + hash(pos["symbol"]) % 1000}


def carry(conn: sqlite3.Connection, coin: str) -> list[tuple[int, float]]:
    """Daily returns of the delta-neutral carry (short perp + spot, 1x notional)."""
    fund = conn.execute("SELECT time, rate FROM funding WHERE symbol = ? ORDER BY time", (coin,)).fetchall()
    days: dict[int, list[float]] = {}
    for t, r in fund:
        days.setdefault(t // DAY * DAY, []).append(r)
    out, on, hist = [], False, []
    for d in sorted(days):
        want = len(hist) >= 3 and sum(hist[-3:]) > 0
        ret = 0.0
        if want != on:
            ret -= 4 * (TAKER + SLIP) / 2  # two legs in or out; half the notional in each leg
            on = want
        if on:
            ret += sum(days[d]) / 2  # funding on the perp leg (half the capital)
        out.append((d, ret))
        hist.append(sum(days[d]))
    return out


def stats(name: str, trades: list[dict], dt, years: list[tuple[int, int]]) -> str:
    if not trades:
        return f"   {name:44} no trades"
    rs = [t["r"] for t in trades]
    span = (max(t["entry"] for t in trades) - min(t["entry"] for t in trades)) / DAY / 365
    line = f"   {name:44} {len(trades):5d} ({len(trades) / max(span, 0.1):4.0f}/yr) win {sum(r > 0 for r in rs) / len(rs):4.0%} {sum(rs) / len(rs):+.3f}R |"
    for a, b in years:
        p = [t["r"] for t in trades if a <= t["entry"] < b]
        line += f" {sum(p):+6.1f}" if p else "    -  "
    cum = peak = dd = 0.0
    for t in sorted(trades, key=lambda x: x["exit"]):
        cum += t["r"]
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    bal, add = dt.account(trades, 0.02, 0.02, 0.12)
    return line + f" | total {sum(rs):+6.1f}R DD {dd:5.1f}R | $150 -> ${bal:10,.0f} ({bal / 150 - 1:+6.0%}) max DD {add:5.1%}"


def run() -> None:
    dt = _load("demo_ideas_test")
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    years6 = [(START6 + k * 365 * DAY, START6 + (k + 1) * 365 * DAY) for k in range(6)]
    fmt = lambda ms: time.strftime("%Y-%m", time.gmtime(ms / 1000))
    systems = {}
    for name, mode, sides, tf, step in (("T1-L daily Donchian 20/10, long only", "don", ("long",), "1d", DAY),
                                        ("T1-LS daily Donchian 20/10, long + short", "don", ("long", "short"), "1d", DAY),
                                        ("T2-L daily SMA100, long only", "sma", ("long",), "1d", DAY),
                                        ("T2-LS daily SMA100, long + short", "sma", ("long", "short"), "1d", DAY),
                                        ("T3-LS 4h Donchian 20/10, long + short", "don", ("long", "short"), "4h", H4)):
        allt = []
        for coin in COINS:
            fund = conn.execute("SELECT time, rate FROM funding WHERE symbol = ? ORDER BY time", (coin,)).fetchall()
            allt += [t for t in trend_trades(coin, bars(conn, coin, tf), fund, mode, sides, step) if t["entry"] >= START6]
        systems[name] = allt
    print("== 6 YEARS (2020-10 .. 2026-10), XRP SOL ETH BTC; R by year from " + " ".join(fmt(a) for a, _ in years6))
    for name, trades in systems.items():
        print(stats(name, trades, dt, years6))
        if "LS" in name:
            print(stats("   longs", [t for t in trades if t["side"] == "long"], dt, years6))
            print(stats("   shorts", [t for t in trades if t["side"] == "short"], dt, years6))
        for coin in COINS:
            print(stats(f"   {coin}", [t for t in trades if t["symbol"] == coin], dt, years6))
    print("\n   halves: 2020-10..2023-10 | 2023-10..2026-10 ($150 each)")
    for name, trades in systems.items():
        a = dt.account([t for t in trades if t["entry"] < MID6], .02, .02, .12)
        b = dt.account([t for t in trades if t["entry"] >= MID6], .02, .02, .12)
        print(f"   {name:44} {a[0] / 150 - 1:+7.0%} (DD {a[1]:4.0%}) | {b[0] / 150 - 1:+7.0%} (DD {b[1]:4.0%})")

    print("\n== FUNDING CARRY (short perp + spot, 1x, on while the 3-day funding is positive; basis ignored)")
    for coin in COINS:
        rets = carry(conn, coin)
        for lo, hi, label in ((START6, 2**62, "6 years"), (START4, 2**62, "4 years"), (MID6, 2**62, "last 3 years")):
            rr = [r for d, r in rets if lo <= d < hi]
            eq = peak = 1.0
            dd = 0.0
            for r in rr:
                eq *= 1 + r
                peak = max(peak, eq)
                dd = max(dd, 1 - eq / peak)
            yrs = len(rr) / 365
            print(f"   {coin} {label:12}: {eq - 1:+6.0%} total, {eq ** (1 / yrs) - 1 if yrs else 0:+5.1%} a year, max DD {dd:4.1%}")

    # T5 / T6 / T7 on the 4-year agent backtest
    ct, mt, at = _load("coordination_test"), _load("mtf_test"), _load("addon_test")
    lconn = sqlite3.connect(f"file:{mt.LONG4}?mode=ro", uri=True)
    trades = [t for t in ct.load(lconn, 1, mt.START4, ("XRP", "SOL", "ETH")) if t["closed"]]
    c6 = at.policy(lconn, trades, (), None)
    daily = {c: bars(conn, c, "1d") for c in ("XRP", "SOL", "ETH")}

    def daily_trend(coin: str, at_ms: int) -> str | None:
        rows = [r for r in daily[coin] if r[0] + DAY <= at_ms][-100:]
        if len(rows) < 100:
            return None
        return "long" if rows[-1][4] > sum(r[4] for r in rows) / 100 else "short"

    t6 = [t for t in c6 if daily_trend(t["symbol"], t["entry"]) in (None, t["side"])]
    t7 = mt.one_per_coin([dict(t) for t in trades], False)
    years4 = [(mt.START4 + k * 365 * DAY, mt.START4 + (k + 1) * 365 * DAY) for k in range(4)]
    print("\n== THE AGENT'S SIGNALS, 4 YEARS (2022-10 .. 2026-10), XRP SOL ETH; R by year; $150 at A 3% / B 2%, 12%")
    for name, tr in (("v6 now (every signal)", trades), ("T7 v6 + one trade per coin (5m and 15m)", t7),
                     ("T5 C6 15m only + one per coin", c6), ("T6 C6 + the daily SMA100 trend", t6)):
        rs = [t["r"] for t in tr]
        line = f"   {name:44} {len(tr):5d} {sum(rs) / len(rs):+.3f}R |" + "".join(
            f" {sum(t['r'] for t in tr if a <= t['entry'] < b):+6.1f}" for a, b in years4)
        bal, dd = dt.account(tr)
        b1 = dt.account([t for t in tr if t["entry"] < mt.SPLIT])
        b2 = dt.account([t for t in tr if t["entry"] >= mt.SPLIT])
        print(line + f" | ${bal:9,.0f} ({bal / 150 - 1:+5.0%}) DD {dd:5.1%} | 2022-24 {b1[0] / 150 - 1:+5.0%} (DD {b1[1]:3.0%})"
              f" | 2024-26 {b2[0] / 150 - 1:+5.0%} (DD {b2[1]:3.0%})")
    # trend systems on the same 4 years for a direct comparison
    print("\n== TREND SYSTEMS ON THE SAME 4 YEARS (2022-10 .. 2026-10), XRP SOL ETH BTC, 2% / 12%")
    for name, trades_ in systems.items():
        sel = [t for t in trades_ if t["entry"] >= START4]
        print(stats(name, sel, dt, years4))


if __name__ == "__main__":
    {"data": data, "run": run}[sys.argv[1]]()
