"""Dashboard backend: settings overrides with audit, exchange keys, live preview and the data layer."""

import json
from pathlib import Path

import pytest

from tradeagent import exchanges
from tradeagent.account.engine import AccountEngine
from tradeagent.account.preview import live_preview
from tradeagent.config import PaperAccountConfig, load_settings
from tradeagent.journal import connect, migrate
from tradeagent.journal.db import now_ms
from tradeagent.settings_store import apply_overrides, audit_log, overrides, reset_value, set_value
from tradeagent.sim.simulator import Costs, close_now, open_trade, results, step

M1, H = 60_000, 3_600_000
T0 = 1_790_208_000_000
COSTS = Costs(0.0002, 0.0005, 0.0002)


@pytest.fixture
def world(settings):
    conn = connect(settings.resolve(settings.journal.path))
    migrate(conn)
    conn.execute("INSERT INTO variants (id, params_json, params_hash, role, parent, created_at) VALUES"
                 " ('v0-aaaaaa', ?, 'a', 'baseline', NULL, 0)", (json.dumps({}),))
    conn.executemany("INSERT INTO market_info (symbol, tick_size, step_size, min_qty, min_notional, updated_at) VALUES (?, ?, ?, ?, ?, 0)",
                     [("XRP", 0.0001, 0.1, 0.1, 5.0), ("LINK", 0.001, 0.01, 0.01, 20.0), ("SOL", 0.01, 0.01, 0.01, 5.0)])
    conn.commit()
    yield conn, settings
    conn.close()


def add_trade(conn, symbol, entry_time, entry, stop, exit_time, win):
    state = open_trade(side="long", mode="fixed", entry_time=entry_time, entry_ref=entry, stop=stop, take_profit_r=1.5,
                       partial_r=1.0, partial_fraction=0.5, trail_lookback=3, costs=COSTS)
    if win:
        step(state, (exit_time, entry, state.target, entry, state.target), COSTS)
    else:
        close_now(state, exit_time, stop, COSTS, "stop")
    conn.execute(
        "INSERT INTO trades (book, variant_id, symbol, timeframe, side, signal_version, trigger_time, confirm_time, entry_time,"
        " taken, exit_mode, entry_ref, stop_initial, target, status, exit_time, exit_reason, r_net, context_json, state_json,"
        " created_at, updated_at) VALUES ('exploration', 'v0-aaaaaa', ?, '15m', 'long', 1, ?, ?, ?, 1, 'fixed', ?, ?, ?,"
        " 'closed', ?, ?, ?, ?, ?, ?, ?)",
        (symbol, entry_time - 30 * M1, entry_time - 15 * M1, entry_time, entry, stop, state.target, exit_time,
         state.exit_reason, results(state, COSTS)["r_net"], json.dumps({"htf": {"1h": "bull", "4h": "bear"}, "values": {}}),
         json.dumps(state.to_json()), now_ms(), now_ms()))
    conn.commit()


# ---- settings overrides ------------------------------------------------------------------------
def test_a_saved_setting_is_validated_audited_and_applied(world, repo_root):
    conn, settings = world
    assert set_value(conn, settings, "paper_account.risk_per_trade", 0.5) is not None  # above the 5% cap: refused
    assert overrides(conn) == {}
    assert set_value(conn, settings, "paper_account.risk_per_trade", 0.01) is None
    assert set_value(conn, settings, "paper_account.max_positions", 3) is None
    fresh = load_settings(repo_root)
    assert apply_overrides(fresh, conn) == []
    assert fresh.paper_account.risk_per_trade == 0.01 and fresh.paper_account.max_positions == 3
    log = audit_log(conn)
    assert [r["key"] for r in log] == ["paper_account.max_positions", "paper_account.risk_per_trade"]
    assert json.loads(log[1]["old_json"]) == 0.02 and json.loads(log[1]["new_json"]) == 0.01

    reset_value(conn, fresh, load_settings(repo_root), "paper_account.max_positions")
    again = load_settings(repo_root)
    apply_overrides(again, conn)
    assert again.paper_account.max_positions == load_settings(repo_root).paper_account.max_positions  # the file's value
    assert "reset" in audit_log(conn)[0]["source"]


def test_the_account_engine_uses_settings_changed_while_it_runs(world):
    conn, settings = world
    engine = AccountEngine(settings, conn)
    set_value(conn, settings, "paper_account.max_positions", 3)
    apply_overrides(settings, conn)
    assert engine.rules.max_positions == 3


def test_bad_overrides_in_the_journal_are_skipped(world):
    conn, settings = world
    with conn:
        conn.execute("INSERT INTO settings (key, value_json, updated_at) VALUES ('cfg:paper_account.risk_per_trade', '9', 0)")
        conn.execute("INSERT INTO settings (key, value_json, updated_at) VALUES ('cfg:exchange.name', '\"x\"', 0)")
    problems = apply_overrides(settings, conn)
    assert len(problems) == 2 and settings.paper_account.risk_per_trade == 0.02


# ---- exchange keys ---------------------------------------------------------------------------
def test_exchange_keys_are_checked_saved_masked_and_removed(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("OTHER=keep\n", encoding="utf-8")
    assert "Passphrase is empty" in exchanges.check("bitget", {"apiKey": "bg_" + "a" * 30, "secret": "b" * 64})
    assert exchanges.check("bitget", {"apiKey": "bg_" + "a" * 30, "secret": "b" * 64, "password": "myPass123"}) == []
    assert any("does not look right" in p for p in exchanges.check("binance", {"apiKey": "has space here 123456", "secret": "x" * 64}))
    exchanges.save(env, "binance", {"apiKey": "A" * 64, "secret": "B" * 64})
    status = exchanges.status(env)
    assert status["binance"]["configured"] and not status["mexc"]["configured"]
    assert status["binance"]["masked"]["API key"] == "AAAA" + "•" * 8 + "AAAA"
    assert "OTHER=keep" in env.read_text(encoding="utf-8")
    exchanges.remove(env, "binance")
    assert not exchanges.status(env)["binance"]["configured"] and "OTHER=keep" in env.read_text(encoding="utf-8")
    assert exchanges.test_connection("mexc", {"apiKey": None, "secret": None}) == (False, "Keys are missing")


def test_every_exchange_lists_what_it_needs():
    assert [f.env for f in exchanges.EXCHANGES["bitget"].fields] == ["BITGET_API_KEY", "BITGET_API_SECRET", "BITGET_API_PASSPHRASE"]
    assert len(exchanges.EXCHANGES["mexc"].fields) == 2 and exchanges.EXCHANGES["binance"].ccxt_id == "binanceusdm"


# ---- live preview ----------------------------------------------------------------------------
def test_live_preview_replays_trades_through_limits_without_writing(world):
    conn, settings = world
    for i, symbol in enumerate(("XRP", "LINK", "SOL")):  # three overlapping trades
        entry = {"XRP": 2.0, "LINK": 20.0, "SOL": 150.0}[symbol]
        add_trade(conn, symbol, T0 + H + i * M1, entry, entry * 0.98, T0 + 3 * H, win=i != 1)
    unlimited = live_preview(conn, settings, PaperAccountConfig(starting_balance=150, risk_per_trade=0.02, leverage_cap=10))
    limited = live_preview(conn, settings, PaperAccountConfig(starting_balance=150, risk_per_trade=0.02, leverage_cap=10,
                                                              max_positions=1))
    assert unlimited["taken"] == 3 and unlimited["skipped"] == {}
    assert limited["taken"] == 1 and limited["skipped"] == {"max 1 open positions": 2}
    assert conn.execute("SELECT count(*) FROM account_trades").fetchone()[0] == 0  # nothing stored


# ---- data layer ------------------------------------------------------------------------------
def test_the_dashboard_data_layer_reads_a_journal(world):
    from tradeagent.dashboard.data import Store

    conn, settings = world
    add_trade(conn, "XRP", T0 + H, 2.0, 1.96, T0 + 2 * H, win=True)
    add_trade(conn, "SOL", T0 + 3 * H, 150.0, 147.0, T0 + 4 * H, win=False)
    AccountEngine(settings, conn).process()
    store = Store(settings)
    assert store.agent_status()["state"] == "stopped"
    paper = store.paper()
    assert paper["closed"] == 2 and paper["balance"] != 150
    assert len(store.equity_curve()) == 3
    s = store.strategy("all")
    assert s["trades"] == 2 and len(s["cumulative_r"]) == 2
    groups = store.breakdowns("all")
    assert {g["group"] for g in groups["Coin"]} == {"XRP", "SOL"} and {g["group"] for g in groups["4h trend"]} == {"against trend"}
    assert store.paper_trades(None, None, None, None, False)[0]["coin"] == "SOL"
    detail = store.trade_detail(store.shadow_trades(None, None, None, None, None, None)[0]["trade_id"])
    assert detail["trade"]["symbol"] in ("XRP", "SOL") and detail["legs"]
    assert store.feed() and store.today()["paper_closed"] >= 0
    assert [h["version"] for h in store.learning()["history"]][-3:] == ["v2", "v3", "v3.1"]
    assert store.experiments()["rows"] == [] and store.experiments()["rules"]["min_trades"] == 100
    gate = store.gate()
    assert len(gate["gate"]) == 10 and all({"name", "value", "ok", "progress"} <= set(c) for c in gate["gate"])
    store.set_kill_switch("pause")
    assert store.kill_switch() == "pause"


def test_the_learning_history_shows_a_version_without_numbers():
    """A promoted experiment has no demo return on its history and a version switched by hand may have no numbers at all
    (v4, 2026-10-24): the Learning page must still open (it failed with a 500 on the missing return)."""
    from tradeagent.dashboard.pages.learning import _history_line

    bare = _history_line({"adopted_at": T0, "trades": None, "expectancy_r": None, "paper_return_pct": None})
    assert "trades" not in bare and "demo account" not in bare
    promoted = _history_line({"adopted_at": T0, "trades": 120, "expectancy_r": 0.21, "paper_return_pct": None})
    assert promoted.endswith("120 trades · +0.210R per trade")
    full = _history_line({"adopted_at": T0, "trades": 260, "expectancy_r": 0.116, "paper_return_pct": 19.5})
    assert full.endswith("260 trades · +0.116R per trade · demo account +19.5% on that history")


def test_the_slow_reports_from_their_own_process_equal_the_reports_built_here(world):
    """The gate and the variant report are built by `python -m tradeagent.dashboard.slow_reports` (2026-10-29: in a
    thread they held Python's lock for seconds and every click waited); they must be the same reports, through JSON."""
    import json

    from tradeagent.account.report import account_report
    from tradeagent.dashboard.data import Store

    conn, settings = world
    add_trade(conn, "XRP", T0 + H, 2.0, 1.96, T0 + 2 * H, win=True)
    add_trade(conn, "SOL", T0 + 3 * H, 150.0, 147.0, T0 + 4 * H, win=False)
    conn.execute("UPDATE trades SET fees_r = 0.02, slippage_r = 0, funding_r = 0, r_gross = r_net + 0.02")  # the variant report sums them
    conn.commit()
    AccountEngine(settings, conn).process()
    store = Store(settings)

    def same(report: dict) -> dict:  # through JSON, without the two numbers that move with the clock
        report = json.loads(json.dumps(report))
        report.pop("days_running")
        report["live_preview"].pop("trades_per_day")
        return report
    assert same(store._build_in_worker("gate", store.settings)) == same(account_report(conn, store.settings))
    assert store._build_in_worker("variants", None) == json.loads(json.dumps(Store._variants(conn)))
    rules = store.settings.paper_account.model_copy(update={"risk_per_trade": 0.01})  # limits not saved yet
    preview = json.loads(json.dumps(live_preview(conn, store.settings, rules, since=None)))
    from_worker = store.preview_in_worker(store.settings, rules, None)
    preview.pop("trades_per_day"), from_worker.pop("trades_per_day")
    assert from_worker == preview and from_worker["taken"] == 2


def test_a_slow_report_is_rebuilt_only_when_the_journal_changed(world):
    """Checked every `seconds`, but rebuilt only after a closed trade, an account or settings change (or after
    SLOW_MAX_AGE_S): most 5-minute checks find nothing new and cost nothing."""
    import time

    from tradeagent.dashboard.data import Store

    conn, settings = world
    store = Store(settings)
    builds = []

    def fake_worker(report, _settings):
        builds.append(report)
        return len(builds)
    store._build_in_worker = fake_worker
    worker = ("gate", None)
    assert store.cached_slow("gate", 0, lambda c: -1, worker) == 1  # the first build is waited for
    assert store.cached_slow("gate", 0, lambda c: -1, worker) == 1  # nothing changed: no rebuild
    assert builds == ["gate"]
    add_trade(conn, "XRP", T0 + H, 2.0, 1.96, T0 + 2 * H, win=True)  # a trade closed
    assert store.cached_slow("gate", 0, lambda c: -1, worker) == 1  # the old one at once...
    for _ in range(50):  # ...while the new one is built
        if store._cache["gate"][1] == 2:
            break
        time.sleep(0.05)
    assert builds == ["gate", "gate"] and store.cached_slow("gate", 60, lambda c: -1, worker) == 2
    store.invalidate()  # a setting or the kill switch changed: rebuilt at the next look
    store.cached_slow("gate", 0, lambda c: -1, worker)
    for _ in range(50):
        if len(builds) == 3:
            break
        time.sleep(0.05)
    assert len(builds) == 3


def test_the_settings_reach_the_worker_process_unchanged(settings):
    from tradeagent.config import Settings

    back = Settings.model_validate_json(settings.model_dump_json())
    assert back.model_dump() == settings.model_dump()


def test_the_dashboard_answers_a_click_in_the_browser_before_the_server(monkeypatch):
    """The menu highlights at once and a bar runs until the new page's title is there (a click that shows nothing on a
    busy VPS looked lost)."""
    from tradeagent.dashboard import app, theme

    assert "busy-bar" in app.BUSY_HTML and "nav.dataset.page" in app.BUSY_HTML and "onAny" in app.BUSY_HTML
    assert "#busy-bar.on" in theme.css("dark")


def test_dashboard_times_follow_the_time_zone_setting():
    from tradeagent.dashboard import widgets

    ms = 1791014100000  # 2026-10-03 07:55 UTC
    try:
        widgets.use_timezone(lambda: "Asia/Karachi")
        assert (widgets.when(ms), widgets.tz_label()) == ("10-03 12:55", "UTC+5")
        widgets.use_timezone(lambda: "Asia/Kolkata")
        assert (widgets.when(ms), widgets.tz_label()) == ("10-03 13:25", "UTC+5:30")
        widgets.use_timezone(lambda: "Etc/UTC")
        assert (widgets.when(ms), widgets.tz_label()) == ("10-03 07:55", "UTC")
    finally:
        widgets.use_timezone(lambda: "Etc/UTC")


def test_slow_reports_are_built_off_the_event_loop_and_never_make_a_page_wait(world):
    import threading
    import time

    from tradeagent.dashboard.data import Store

    conn, settings = world
    store = Store(settings)
    builds, threads = [], []

    def slow(c):
        threads.append(threading.current_thread().name)
        time.sleep(0.3)
        builds.append(c.execute("SELECT count(*) FROM variants").fetchone()[0])
        return len(builds)

    assert store.cached_slow("report", 60, slow) == 1  # the very first call waits for the first build
    assert threads[0].startswith("dashboard-report")  # built in a worker thread with its own connection
    t0 = time.monotonic()
    assert store.cached_slow("report", 0, slow) == 1  # older than 0 s: the old one comes back at once...
    assert time.monotonic() - t0 < 0.1
    for _ in range(50):  # ...while the rebuild runs in the background
        if store._cache["report"][1] == 2:
            break
        time.sleep(0.05)
    assert store.cached_slow("report", 60, slow) == 2
    store.invalidate()  # a settings change: kept on show, marked old
    assert store._cache["report"] == (0.0, 2)
