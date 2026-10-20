"""Backtest the current setup (signal version 6) on the past XRP, SOL and ETH charts.

The AGENT charts' studies (agent_studies_v6.json: scalp on 5m, scalp15 with Trendline on 15m, Squeeze instead of VWAP)
are put on Market_check, 10,000 bars are read with the agent's read_history, and the whole agent runs on a copy of
the journal (data/replay/journal-v6.db): SetupEngine (baseline, quality tiers from the 15m Trendline and the
TradingView OI history, squeeze recorded), Tracker, and the demo account with today's rules. The live journal is
only read.

    .venv\\Scripts\\python -u research\\tools\\v6_backtest.py tv
    .venv\\Scripts\\python -u research\\tools\\v6_backtest.py replay
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
import statistics as st
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("coin_screen", HERE / "coin_screen.py")
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)
from tradeagent.journal import connect, migrate  # noqa: E402
from tradeagent.tv import js  # noqa: E402
from tradeagent.tv.cdp import TradingViewCDP  # noqa: E402
from tradeagent.tv.snapshots import Snapshot, store_snapshots  # noqa: E402

ROOT = cs.ROOT
SNAPS = ROOT / "data" / "research" / "v6_snapshots.db"
REPLAY = ROOT / "data" / "replay" / "journal-v6.db"
COINS = ["XRP", "SOL", "ETH"]
JOBS = [("5", "5m", "scalp"), ("15", "15m", "scalp15")]
FAILED_JS = """(function () {
  var api = window.TradingViewApi, ch = api.chart(0), model = api._chartWidgetCollection.getAll()[0].model().model();
  return ch.getAllStudies().filter(function (s) { return model.dataSourceForId(s.id).isFailed(); }).map(function (s) { return s.name; });
})()"""
READY_JS = cs.LOAD_JS.replace("if (!src || src.isLoading() || src.isFailed()) return false;",
                              "if (!src || src.isFailed()) return true; if (src.isLoading()) return false;")


def studies_for(interval: str) -> list[dict]:
    agent = json.loads((HERE / "agent_studies_v6.json").read_text(encoding="utf-8"))
    out = []
    for s in agent:
        if s["interval"] == interval:
            version = (s.get("pine") or {}).get("version")
            out.append({"name": s["name"], "scriptIdPart": s["scriptIdPart"], "inputs": s["inputs"],
                        "version": None if not version or version.startswith("-") else version})
    return out


async def tv_phase() -> None:
    cdp = TradingViewCDP(timeout=1000)
    page = next(p for p in await cdp.chart_pages() if p.layout_id == cs.LAYOUT)
    conn = connect(SNAPS)
    migrate(conn)
    for res, tf, template in JOBS:
        print(f"{tf}: studies", await cdp.evaluate(page, f"({cs.SET_STUDIES_JS})({json.dumps(studies_for(res))})",
                                                  await_promise=True), flush=True)
        for coin in COINS:
            if conn.execute("SELECT count(*) FROM snapshots WHERE symbol = ? AND timeframe = ?", (coin, tf)).fetchone()[0] > 1000:
                print(f"  {coin} {tf}: already stored")
                continue
            symbol = f"BINANCE:{coin}USDT.P"
            loaded = await cdp.evaluate(page, f"({READY_JS})({json.dumps(symbol)}, {json.dumps(res)}, 10000)", await_promise=True)
            failed = await cdp.evaluate(page, FAILED_JS)
            spec_ = cs.catalog.js_spec(template)
            if failed:
                print(f"  {coin} {tf}: failed studies {failed}; read without them")
                spec_ = {k: v for k, v in spec_.items() if v["study"] not in failed}
            stored, from_time = 0, 0
            while from_time is not None:
                raw = await cdp.evaluate(page, js.read_history(spec_, 0, from_time, cs.WARMUP, 2000))
                if raw.get("error") or raw.get("problems") or raw.get("symbol") != symbol:
                    print(f"  {coin} {tf}: read problem {raw.get('error') or raw.get('problems')}")
                    break
                store_snapshots(conn, [Snapshot(coin, tf, r[0] * 1000, 6, int(time.time() * 1000), values=r[6], ohlcv=r[1:6],
                                                source="backfill") for r in raw["rows"]])
                stored += len(raw["rows"])
                from_time = raw.get("next_time")
            print(f"  {coin} {tf}: {loaded.get('bars')} bars, {stored} snapshots", flush=True)
    conn.close()


def merge_trendline(conn: sqlite3.Connection) -> int:
    """Where the 15m snapshots lack Trendline values (the study failed on 10,000 bars), take its flags from the
    TradingView history read on 2026-10-18 (research/tools/indicator_history.py) and from the live journal."""
    flags = {}
    tl = sqlite3.connect(ROOT / "data" / "research" / "indicators_history.db")
    for coin, t, plot in tl.execute("SELECT symbol, time, plot FROM flags WHERE tf = '15m' AND study LIKE 'Dynamic Trendline%'"
                                    " AND plot LIKE '%alertcondition%'"):
        flags.setdefault((coin, t), {"long": 0, "short": 0})["long" if "LONG" in plot else "short"] = 1
    covered = {c: tl.execute("SELECT max(time) FROM bars WHERE symbol = ? AND tf = '15m'", (c,)).fetchone()[0] for c in COINS}
    live = sqlite3.connect(f"file:{cs.settings.resolve(cs.settings.journal.path)}?mode=ro", uri=True)
    live_flags = {}
    for coin, t, v in live.execute("SELECT symbol, bar_time, values_json FROM snapshots WHERE timeframe = '15m'"
                                   " AND problems_json IS NULL AND values_json LIKE '%trendline%'"):
        tlv = json.loads(v).get("trendline")
        if tlv:
            live_flags[(coin, t)] = {"long": tlv.get("long", 0), "short": tlv.get("short", 0)}
    changed = 0
    for sid, coin, t, v in conn.execute("SELECT id, symbol, bar_time, values_json FROM snapshots WHERE timeframe = '15m'").fetchall():
        values = json.loads(v)
        if "trendline" in values:
            continue
        if t <= (covered.get(coin) or 0):
            values["trendline"] = flags.get((coin, t), {"long": 0, "short": 0})
        elif (coin, t) in live_flags:
            values["trendline"] = live_flags[(coin, t)]
        else:
            continue
        conn.execute("UPDATE snapshots SET values_json = ? WHERE id = ?", (json.dumps(values), sid))
        changed += 1
    conn.commit()
    return changed


def account_run(conn: sqlite3.Connection, settings, label: str) -> dict:
    from tradeagent.account.engine import AccountEngine, reset_account

    reset_account(conn, settings)
    AccountEngine(settings, conn).process()
    rows = conn.execute("SELECT entry_time, pnl_usd, r_net, balance_after, notes FROM account_trades WHERE account = 'paper'"
                        " AND status = 'closed' ORDER BY exit_time, id").fetchall()
    rejected = conn.execute("SELECT count(*) FROM account_trades WHERE account = 'paper' AND status = 'rejected'").fetchone()[0]
    start = settings.paper_account.starting_balance
    peak, dd, bal = start, 0.0, start
    for r in rows:
        bal = r[3]
        peak = max(peak, bal)
        dd = max(dd, (peak - bal) / peak)
    a_tier = sum(1 for r in rows if r[4] and "quality A" in r[4])
    print(f"   {label:38} {len(rows)} closed, {rejected} skipped | ${start:.0f} -> ${bal:.2f} ({bal / start - 1:+.0%}),"
          f" max DD {dd:.1%}, quality-A sized {a_tier}")
    return {"final": bal, "dd": dd}


def replay_phase() -> None:
    from tradeagent.setups.config import load_variants, register_variants
    from tradeagent.setups.engine import SetupEngine
    from tradeagent.sim.tracker import Tracker

    REPLAY.parent.mkdir(parents=True, exist_ok=True)
    REPLAY.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{cs.settings.resolve(cs.settings.journal.path)}?mode=ro", uri=True)
    dst = sqlite3.connect(REPLAY)
    src.backup(dst)
    src.close()
    dst.close()
    conn = connect(REPLAY)
    migrate(conn)
    with conn:
        for table in ("snapshots", "setups", "trades", "account_trades", "account_state", "open_interest"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM engine_state WHERE key LIKE 'engine:%'")
    snaps = sqlite3.connect(SNAPS)
    rows = snaps.execute("SELECT symbol, timeframe, bar_time, signal_version, open, high, low, close, volume, values_json,"
                         " problems_json, read_at, latency_ms, source FROM snapshots").fetchall()
    conn.executemany("INSERT INTO snapshots (symbol, timeframe, bar_time, signal_version, open, high, low, close, volume,"
                     " values_json, problems_json, read_at, latency_ms, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    print(f"v6 snapshots copied: {len(rows)}; Trendline merged into {merge_trendline(conn)} 15m snapshots")
    oi = sqlite3.connect(ROOT / "data" / "research" / "oi_history.db")
    oi_rows = [(c, (t + 900) * 1000, v) for c, t, v in oi.execute("SELECT symbol, time, c FROM oi")]
    conn.executemany("INSERT OR REPLACE INTO open_interest (symbol, time, amount, value) VALUES (?, ?, ?, NULL)", oi_rows)
    conn.commit()
    print(f"OI history (TradingView, matches Binance) inserted: {len(oi_rows)} snapshots")

    settings = cs.settings.model_copy(deep=True)
    settings.journal.path = str(REPLAY)
    baseline = load_variants(settings.resolve(settings.shadow.setups), cs.catalog)[0]
    register_variants(conn, [baseline])
    counts = SetupEngine(settings, [baseline], conn).process()
    counts.update(Tracker(settings, conn).update())
    print("engine:", dict(counts))

    trades = conn.execute("SELECT entry_time, r_net, symbol, timeframe, context_json, exit_reason FROM trades"
                          " WHERE taken = 1 AND status = 'closed' ORDER BY entry_time").fetchall()
    if not trades:
        print("no closed trades")
        return

    def line(name: str, rs: list[float]) -> str:
        if not rs:
            return f"   {name:34} no trades"
        w, l = sum(x for x in rs if x > 0), -sum(x for x in rs if x < 0)
        return f"   {name:34} n={len(rs):3d} win={sum(x > 0 for x in rs) / len(rs):.0%} exp={st.mean(rs):+.3f}R PF={w / l if l else 0:.2f} total={sum(rs):+.1f}R"

    first, last = trades[0][0], trades[-1][0]
    print(f"\n== SHADOW: every baseline signal, v6 charts ({time.strftime('%Y-%m-%d', time.gmtime(first / 1000))} .. "
          f"{time.strftime('%Y-%m-%d', time.gmtime(last / 1000))})")
    rs = [t[1] for t in trades]
    print(line("all", rs))
    mid = trades[len(trades) // 2][0]
    print(line("half 1", [t[1] for t in trades if t[0] < mid]))
    print(line("half 2", [t[1] for t in trades if t[0] >= mid]))
    for coin in COINS:
        print(line(coin, [t[1] for t in trades if t[2] == coin]))
    for tf in ("5m", "15m"):
        print(line(tf, [t[1] for t in trades if t[3] == tf]))
    ctx = [json.loads(t[4] or "{}") for t in trades]
    print(line("quality A (Trendline or OI)", [t[1] for t, c in zip(trades, ctx) if c.get("quality") == "A"]))
    print(line("quality B", [t[1] for t, c in zip(trades, ctx) if c.get("quality") == "B"]))
    print(line("squeeze fired", [t[1] for t, c in zip(trades, ctx) if c.get("sqz_fire") is True]))
    print(line("squeeze not fired", [t[1] for t, c in zip(trades, ctx) if c.get("sqz_fire") is False]))

    print("\n== DEMO ACCOUNT replayed over the same history ($150, every signal, overlapping positions handled)")
    account_run(conn, settings, "today's rules (A 3%, B 2%, 12% cap)")
    flat = settings.model_copy(deep=True)
    flat.paper_account.risk_tier_a = None
    account_run(conn, flat, "flat 2% (no tiers), 12% cap")
    live_rules = settings.model_copy(deep=True)
    for k in type(settings.paper_account).model_fields:
        setattr(live_rules.paper_account, k, getattr(settings.live_account, k))
    account_run(conn, live_rules, "live limits (2%, 12% cap, 10% day stop)")
    conn.close()


if __name__ == "__main__":
    if sys.argv[1] == "tv":
        asyncio.run(tv_phase())
    elif sys.argv[1] == "replay":
        replay_phase()
