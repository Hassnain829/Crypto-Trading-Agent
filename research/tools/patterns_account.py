r"""Second pass on the pattern findings (2026-10-23): luck or real, overlap with tier A, the demo account. Research only.

    .venv\Scripts\python -u research\tools\patterns_account.py > data\research\patterns_account.txt

Plan, written before the results: research/notes/2026-10-23-patterns2-plan.md.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
_spec = importlib.util.spec_from_file_location("patterns_test", HERE / "patterns_test.py")
pt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pt)

LONG = ROOT / "data" / "research" / "long4" / "journal.db"
LIVE = ROOT / "data" / "journal.db"
REPLAY = ROOT / "data" / "replay"
CUT_MS = 1792454400000  # 2026-10-20 00:00 UTC: the research journal before, the live journal from here
SPLIT_MS = 1727740800000  # 2024-10-01
STEP = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
RULE = {"1h": "1h", "4h": "4h", "1d": "1D"}
MOMENTUM = {"bullish marubozu", "bearish marubozu", "three white soldiers", "three black crows"}
_cache: dict = {}


def candles15(coin: str) -> pd.DataFrame:
    """15m candles: the research journal before CUT_MS, the live journal after (BTC there has only 5m, resampled)."""
    q = "SELECT open_time, open, high, low, close FROM candles WHERE symbol = ? AND timeframe = ? AND open_time {} ? ORDER BY open_time"

    def read(conn, tf, op):
        df = pd.read_sql_query(q.format(op), conn, params=(coin, tf, CUT_MS))
        df.index = pd.to_datetime(df.pop("open_time"), unit="ms", utc=True)
        return df

    with sqlite3.connect(f"file:{LONG}?mode=ro", uri=True) as a, sqlite3.connect(f"file:{LIVE}?mode=ro", uri=True) as b:
        old, new = read(a, "15m", "<"), read(b, "15m", ">=")
        if new.empty:
            new = read(b, "5m", ">=")
            if not new.empty:
                new = new.resample("15min", label="left", closed="left").agg(
                    {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    df = pd.concat([old, new])
    return df[~df.index.duplicated()].sort_index()


def masks(coin: str, tf: str):
    """(close times in ms, bullish, bearish, bullish reversal, bearish reversal) masks of the candles that complete a pattern."""
    if (coin, tf) not in _cache:
        df = _cache.get((coin, "raw"))
        if df is None:
            df = _cache[(coin, "raw")] = candles15(coin)
        if tf in RULE:
            df = df.resample(RULE[tf], label="left", closed="left").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        o, h, l, c = (df[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
        bull, bear, bull_rev, bear_rev = (np.zeros(len(c), bool) for _ in range(4))
        for name, (d, span, m) in pt.candle_patterns(o, h, l, c).items():
            (bull if d > 0 else bear)[:] |= m
            if name not in MOMENTUM:
                (bull_rev if d > 0 else bear_rev)[:] |= m
        close_ms = ((df.index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy(dtype="int64") + STEP[tf]
        _cache[(coin, tf)] = (close_ms, bull, bear, bull_rev, bear_rev)
    return _cache[(coin, tf)]


def flags(tr: pd.DataFrame, who: str, tf: str, last: int = 1, rev: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """(with, against): a pattern in / against each trade's direction among the last `last` candles closed at the decision."""
    w, a = np.zeros(len(tr), bool), np.zeros(len(tr), bool)
    for coin in (["BTC"] if who == "BTC" else tr["symbol"].unique()):
        sel = np.arange(len(tr)) if who == "BTC" else np.where(tr["symbol"].to_numpy() == coin)[0]
        close_ms, bull, bear, bull_rev, bear_rev = masks(coin, tf)
        up, dn = (bull_rev, bear_rev) if rev else (bull, bear)
        pos = np.searchsorted(close_ms, tr["decision"].to_numpy()[sel], side="right") - 1
        b, s = np.zeros(len(sel), bool), np.zeros(len(sel), bool)
        for j in range(last):
            p = pos - j
            ok = p >= 0
            b[ok] |= up[p[ok]]
            s[ok] |= dn[p[ok]]
        d = tr["d"].to_numpy()[sel]
        w[sel] = np.where(d > 0, b, s)
        a[sel] = np.where(d > 0, s, b)
    return w, a


def load_trades(path: Path, variant: str, decision: str = "confirm", symbols: list[str] | None = None,
                taken_only_closed: bool = True) -> pd.DataFrame:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as c:
        tr = pd.read_sql_query(
            "SELECT id, symbol, timeframe, side, trigger_time, confirm_time, entry_time, r_net, status, context_json FROM trades"
            " WHERE variant_id = ? AND taken = 1" + (" AND status = 'closed'" if taken_only_closed else ""), c, params=(variant,))
    if symbols:
        tr = tr[tr["symbol"].isin(symbols)].reset_index(drop=True)
    base = tr["confirm_time"].fillna(tr["trigger_time"]) if decision == "confirm" else tr["trigger_time"]
    tr["decision"] = base.astype("int64") + tr["timeframe"].map(STEP).astype("int64")
    tr["d"] = np.where(tr["side"] == "long", 1, -1)
    tr["quality"] = [json.loads(j or "{}").get("quality") for j in tr["context_json"]]
    return tr.sort_values("decision").reset_index(drop=True)


def candidate(tr: pd.DataFrame) -> np.ndarray:
    return flags(tr, "coin", "1h")[0] | flags(tr, "coin", "1d")[0]


def split_line(r: np.ndarray, t: np.ndarray, mask: np.ndarray, mid: int) -> str:
    x, h1, h2 = r[mask], r[mask & (t < mid)], r[mask & (t >= mid)]
    f = lambda v: f"{v.mean():+.3f}" if len(v) else "  -  "
    return f"{len(x):5d} trades {f(x)}R | {f(h1)} ({len(h1)}) | {f(h2)} ({len(h2)})"


def part1() -> None:
    print("######## 1. LUCK OR REAL ########\n")
    news = REPLAY / "journal-news.db"
    tr = load_trades(news, "v0-e78944", decision="trigger")  # the first pass's definition
    tr["decision"] = tr["trigger_time"].astype("int64") + 900_000
    r = tr["r_net"].to_numpy()
    sources = [("coin", "15m", 3), ("coin", "1h", 1), ("coin", "4h", 1), ("coin", "1d", 1), ("BTC", "4h", 1), ("BTC", "1d", 1)]
    withs, nones, names = [], [], []
    for who, tf, last in sources:
        for rev in (False, True):
            w, a = flags(tr, who, tf, last, rev)
            withs.append(w & ~a)
            nones.append(~w & ~a)
            names.append(f"{who} {tf} {'reversal' if rev else 'any'}")
    W, N = np.array(withs), np.array(nones)
    gap = lambda W_, N_: (W_ * r).sum(1) / W_.sum(1) - (N_ * r).sum(1) / N_.sum(1)
    obs = gap(W, N)
    rng = np.random.default_rng(11)
    maxes = np.array([gap(np.roll(W, k, axis=1), np.roll(N, k, axis=1)).max()
                      for k in rng.integers(50, len(r) - 50, 2000)])
    print("Rotation test: the largest 'with minus none' gap of the 12 looks, 2,000 rotations of the flags through time")
    for name, g in zip(names, obs):
        print(f"   {name:22} gap {g:+.3f}R   p (any of the 12 this big by luck) = {(maxes >= g).mean():.3f}")

    print("\nReplication: a pattern in the trade's direction on the coin's last 1h OR 1d candle (decision = the confirmation"
          " candle's close)\n   sample: group trades R | first half | second half (split at the sample's middle)")
    board, gate = REPLAY / "journal-long-board.db", REPLAY / "journal-gate-2026-06-25.db"
    samples = [("4-year design, XRP/SOL/ETH (found here)", news, "v0-e78944", None),
               ("dip15 on BTC (3 years, not seen)", board, "dip15-e78944", ["BTC"]),
               ("v0 5m+15m, 4 coins (3 years, not seen)", board, "v0-773ea9", None),
               ("trend15 5m, 4 coins (3 years, not seen)", board, "trend15-dfc467", None),
               ("design on TradingView data since 06-25", gate, None, None)]
    for label, path, vid, syms in samples:
        if vid is None:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as c:
                vid = c.execute("SELECT id FROM variants WHERE id LIKE 'design-%'").fetchone()[0]
        t = load_trades(path, vid, symbols=syms)
        f = candidate(t)
        rr, tt = t["r_net"].to_numpy(), t["decision"].to_numpy()
        mid = int(np.median(tt))
        print(f"   {label}:")
        print(f"      with pattern  {split_line(rr, tt, f, mid)}")
        print(f"      without       {split_line(rr, tt, ~f, mid)}")

    print("\nOverlap with tier A (A = open interest up > 1% in 4 h here; Trendline values exist only from 2026-10-18)")
    for label, path, vid in (("4-year design", news, "v0-e78944"), ("TradingView since 06-25", gate, None)):
        if vid is None:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as c:
                vid = c.execute("SELECT id FROM variants WHERE id LIKE 'design-%'").fetchone()[0]
        t = load_trades(path, vid)
        f, a = candidate(t), (t["quality"] == "A").to_numpy()
        rr = t["r_net"].to_numpy()
        print(f"   {label}:")
        for la, ma in (("tier A", a), ("not A ", ~a)):
            for lf, mf in (("pattern", f), ("no pattern", ~f)):
                m = ma & mf
                print(f"      {la} + {lf:10} {m.sum():5d} trades {rr[m].mean() if m.any() else float('nan'):+.3f}R")


def account(conn, s, vid: str, quality: dict[int, str], a_risk: float | None, b_risk: float,
            windows: list[tuple[int, int]]) -> list[tuple]:
    from tradeagent.account.engine import ACCOUNT, AccountEngine, reset_account

    with conn:
        conn.executemany("UPDATE trades SET context_json = json_set(coalesce(context_json, '{}'), '$.quality', ?) WHERE id = ?",
                         [(q, i) for i, q in quality.items()])
    s.paper_account.risk_tier_a, s.paper_account.risk_per_trade = a_risk, b_risk
    out = []
    for lo, hi in windows:
        reset_account(conn, s)
        with conn:
            conn.execute("UPDATE trades SET taken = -taken WHERE variant_id = ? AND taken > 0 AND (entry_time < ? OR entry_time >= ?)",
                         (vid, lo, hi))
        try:
            AccountEngine(s, conn).process()
        finally:
            with conn:
                conn.execute("UPDATE trades SET taken = -taken WHERE variant_id = ? AND taken < 0", (vid,))
        rows = conn.execute("SELECT balance_after, risk_usd, balance_before FROM account_trades WHERE account = ? AND status = 'closed'"
                            " ORDER BY exit_time, id", (ACCOUNT,)).fetchall()
        bal = peak = s.paper_account.starting_balance
        dd = 0.0
        for row in rows:
            bal = row[0]
            peak = max(peak, bal)
            dd = max(dd, 1 - bal / peak)
        avg = float(np.mean([row[1] / row[2] for row in rows if row[2]])) if rows else 0.0
        out.append((len(rows), bal, dd, avg))
    return out


def part2() -> None:
    from tradeagent.config import load_settings
    from tradeagent.journal import connect
    from tradeagent.learning.long_screen import overlay

    print("\n\n######## 2. THE DEMO ACCOUNT (the design, 15m + dip 60, no news filter; the user's rules, $150) ########")
    settings = load_settings(ROOT)
    s = settings.model_copy(deep=True)
    coins = ["XRP", "SOL", "ETH"]
    s.exchange.symbols = {c: settings.exchange.symbols[c] for c in coins}
    pa = s.paper_account
    pa.symbols, pa.starting_balance, pa.max_open_risk = coins, 150.0, 0.12
    pa.max_positions, pa.max_positions_per_coin, pa.allow_opposite, pa.first_position_always = 5, 2, False, True
    pa.daily_loss_stop, pa.leverage_cap, pa.drawdown_brake = None, 10, None
    for label, src, kind in (("4 YEARS (Python indicators, 2022-10 to 2026-10)", REPLAY / "journal-news.db", "news"),
                             ("TRADINGVIEW DATA since 2026-06-25", REPLAY / "journal-gate-2026-06-25.db", "gate")):
        copy = REPLAY / f"journal-patterns-{kind}.db"
        for p in (copy, copy.with_name(copy.name + "-wal"), copy.with_name(copy.name + "-shm")):
            p.unlink(missing_ok=True)
        with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as a, sqlite3.connect(copy) as b:
            a.backup(b)
        if kind == "news":
            s.learning.long_history, s.learning.long_history_years = str(LONG), None
            conn = overlay(s, "patterns-news", resume=True)
            vid = "v0-e78944"
            windows = [(0, 2**62), (0, SPLIT_MS), (SPLIT_MS, 2**62)]
        else:
            conn = connect(copy)
            vid = conn.execute("SELECT id FROM variants WHERE id LIKE 'design-%'").fetchone()[0]
            windows = [(0, 2**62)]
        with conn:
            conn.execute("UPDATE variants SET role = CASE id WHEN ? THEN 'baseline' ELSE 'challenger' END", (vid,))
            conn.execute("DELETE FROM engine_state")
        t = load_trades(copy, vid, taken_only_closed=False)
        cand = candidate(t)
        btc_w, btc_a = flags(t, "BTC", "4h")
        caution = btc_w | btc_a | flags(t, "coin", "15m", 3, rev=True)[0]
        rec_a = (t["quality"] == "A").to_numpy()
        ids = t["id"].to_numpy()
        q = lambda m: {int(i): ("A" if x else "B") for i, x in zip(ids, m)}
        schemes = [("S0 now (tier A as recorded)", q(rec_a), 0.03),
                   ("S1 tier A or pattern", q(rec_a | cand), 0.03),
                   ("S2 pattern only", q(cand), 0.03),
                   ("S3 everyone 2%", q(np.zeros(len(t), bool)), None),
                   ("S4 = S1 minus BTC-4h / 15m cautions", q((rec_a | cand) & ~caution), 0.03)]
        print(f"\n=== {label} ===   ({len(t)} taken trades; pattern on {cand.mean():.0%}, recorded A on {rec_a.mean():.0%})")
        head = "all" + (" | 2022-24 | 2024-26" if len(windows) > 1 else "")
        print(f"   scheme: trades, $150 ->, max DD, average risk  [{head}]")
        results = {}
        for name, quality, a_risk in schemes:
            res = account(conn, s, vid, quality, a_risk, 0.02, windows)
            results[name] = res
            print(f"   {name:40} " + " | ".join(f"{n} tr ${b:,.0f} ({b / 150 - 1:+.0%}) DD {d:.1%} risk {r:.2%}" for n, b, d, r in res))
        avg_s1 = results["S1 tier A or pattern"][0][3]
        res = account(conn, s, vid, q(np.zeros(len(t), bool)), None, round(avg_s1, 4), windows)
        print(f"   {'flat at S1 average risk ' + format(avg_s1, '.2%'):40} "
              + " | ".join(f"{n} tr ${b:,.0f} ({b / 150 - 1:+.0%}) DD {d:.1%} risk {r:.2%}" for n, b, d, r in res))
        print("   How big should tier A be? S1 (tier A or pattern), B at 2%, 12% budget:")
        for a_risk in (0.025, 0.03, 0.035, 0.04, 0.05):
            res = account(conn, s, vid, q(rec_a | cand), a_risk, 0.02, windows)
            print(f"      A {a_risk:.1%}: " + " | ".join(f"{n} tr ${b:,.0f} ({b / 150 - 1:+.0%}) DD {d:.1%}" for n, b, d, r in res))
        conn.close()


def main() -> None:
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)  # the live agent comes first
    part1()
    part2()


if __name__ == "__main__":
    main()
