"""Paper account: sizing and risk rules, event order, daily stop, kill switch, consistency with exploration."""

import json

import pytest

from tradeagent.account.engine import LATE, AccountEngine, reset_account
from tradeagent.account.kill_switch import get_kill_switch, set_kill_switch
from tradeagent.account.report import account_report, consistency_issues
from tradeagent.account.rules import MarketLimits, OpenPosition, check_entry, round_down, size_position
from tradeagent.journal import connect, migrate
from tradeagent.journal.db import now_ms
from tradeagent.sim.simulator import Costs, close_now, open_trade, results, step

M1, H, DAY = 60_000, 3_600_000, 86_400_000
T0 = 1_790_208_000_000  # 2026-09-24 00:00 UTC
BASELINE, CHALLENGER = "v0-aaaaaa", "tp_2r-bbbbbb"
COSTS = Costs(maker_fee=0.0002, taker_fee=0.0005, slippage=0.0002)


def live_limits(settings):
    """The live-style limits these tests check (the configured paper account may have none)."""
    settings.paper_account.max_positions = 2
    settings.paper_account.max_positions_per_coin = 1
    settings.paper_account.daily_loss_stop = 0.10
    return settings


@pytest.fixture
def world(settings):
    live_limits(settings)
    conn = connect(settings.resolve(settings.journal.path))
    migrate(conn)
    conn.executemany(
        "INSERT INTO variants (id, params_json, params_hash, role, parent, created_at) VALUES (?, '{}', ?, ?, NULL, 0)",
        [(BASELINE, "a", "baseline"), (CHALLENGER, "b", "challenger")],
    )
    conn.executemany(  # Binance's real limits: LINK has a 20 USDT minimum order
        "INSERT INTO market_info VALUES (?, ?, ?, ?, ?, 0)",
        [("XRP", 0.0001, 0.1, 0.1, 5.0), ("LINK", 0.001, 0.01, 0.01, 20.0), ("SOL", 0.01, 0.01, 0.01, 5.0)],
    )
    conn.commit()
    yield conn, settings
    conn.close()


def add_trade(conn, symbol, side, entry_time, entry, stop, exit_time=None, exit_price=None, *, target=False,
              variant=BASELINE, tf="5m", taken=1, created_at=None, limit=False):
    """An exploration trade as the setup engine and tracker would store it (closed if exit_time is given)."""
    state = open_trade(side=side, mode="fixed", entry_time=entry_time, entry_ref=entry, stop=stop, take_profit_r=1.5,
                       partial_r=1.0, partial_fraction=0.5, trail_lookback=3, costs=COSTS, limit_entry=limit)
    if target:  # a candle that reaches the take-profit: limit exit with the maker fee
        step(state, (exit_time, entry, max(entry, state.target), min(entry, state.target), state.target), COSTS)
    elif exit_time is not None:
        close_now(state, exit_time, exit_price, COSTS, "stop")
    closed = state.closed
    cur = conn.execute(
        "INSERT INTO trades (book, variant_id, symbol, timeframe, side, signal_version, trigger_time, confirm_time,"
        " entry_time, taken, exit_mode, entry_ref, stop_initial, target, status, exit_time, exit_reason, r_net,"
        " context_json, state_json, created_at, updated_at)"
        " VALUES ('exploration', ?, ?, ?, ?, 1, ?, ?, ?, ?, 'fixed', ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?)",
        (variant, symbol, tf, side, entry_time - 10 * M1, entry_time - 5 * M1, entry_time, taken, entry, stop,
         state.target, "closed" if closed else "open", exit_time if closed else None, state.exit_reason,
         results(state, COSTS)["r_net"] if closed else None, json.dumps(state.to_json()),
         created_at or now_ms(), now_ms()),
    )
    conn.commit()
    return cur.lastrowid


def add_candle(conn, symbol, open_time, close):
    conn.execute("INSERT INTO candles VALUES (?, '1m', ?, ?, ?, ?, ?, 1.0)", (symbol, open_time, close, close, close, close))
    conn.commit()


def paper(conn, trade_id):
    return conn.execute("SELECT * FROM account_trades WHERE trade_id = ?", (trade_id,)).fetchone()


def balance(conn):
    return conn.execute("SELECT balance FROM account_state").fetchone()[0]


# ---- rules -----------------------------------------------------------------------------------
def test_size_risks_two_percent_of_the_balance_and_rounds_down(settings):
    sized = size_position(150.0, 2.0, 1.993, settings.paper_account, MarketLimits(0.1, 0.1, 5.0))
    assert sized.qty == 428.5  # 3 USDT / 0.007 = 428.57, rounded down to XRP's 0.1 step
    assert sized.risk_usd == pytest.approx(2.9995) and sized.risk_usd <= 0.02 * 150
    assert sized.notional == pytest.approx(857.0) and sized.leverage == pytest.approx(857.0 / 150)
    assert sized.notes == []


def test_leverage_cap_and_free_margin_reduce_the_size(settings):
    rules, limits = settings.paper_account, MarketLimits(0.01, 0.01, 5.0)
    capped = size_position(150.0, 100.0, 99.9, rules, limits)  # 3 USDT risk would need 3000 USDT = 20x
    assert capped.qty == 15.0 and capped.leverage == pytest.approx(10.0)
    assert capped.risk_usd == pytest.approx(1.5) and "leverage cap" in capped.notes[0]
    second = size_position(150.0, 100.0, 99.0, rules, limits, used_margin=130.0)  # 20 USDT margin left = 200 USDT at 10x
    assert second.qty == 2.0 and second.risk_usd == pytest.approx(2.0) and "free margin" in second.notes[0]
    assert size_position(150.0, 100.0, 99.0, rules, limits, used_margin=150.0) == "below the minimum order size (5 USDT)"


def test_minimum_order_size_and_rounding(settings):
    rules = settings.paper_account
    # A 20% stop leaves a 15 USDT position: below LINK's 20 USDT minimum, fine where the minimum is 5.
    assert size_position(150.0, 100.0, 80.0, rules, MarketLimits(0.01, 0.01, 20.0)) == "below the minimum order size (20 USDT)"
    assert size_position(150.0, 100.0, 80.0, rules, MarketLimits(0.01, 0.01, 5.0)).qty == 0.15
    assert size_position(150.0, 100.0, 80.0, rules, MarketLimits(1.0, 1.0, 5.0)) == "below the minimum order size (5 USDT)"
    assert size_position(150.0, 100.0, 100.0, rules, MarketLimits(0.01, 0.01, 5.0)) == "invalid stop or empty balance"
    assert round_down(0.3, 0.1) == 0.3 and round_down(1.23456, 0.001) == 1.234
    assert round_down(7.9, 1.0) == 7.0 and round_down(0.8, 0.25) == 0.75


def test_entry_checks(settings):
    live_limits(settings)
    xrp, link = OpenPosition("XRP", "long", 300.0), OpenPosition("LINK", "short", 300.0)
    base = {"balance": 150.0, "day_start_balance": 150.0, "rules": settings.paper_account, "kill_switch": "off"}
    assert check_entry(symbol="XRP", open_positions=[], **base) is None
    assert check_entry(symbol="XRP", open_positions=[xrp], **base) == "XRP already has an open position"
    assert check_entry(symbol="LINK", open_positions=[xrp], **base) is None
    assert check_entry(symbol="SOL", open_positions=[xrp, link], **base) == "max 2 open positions"
    assert check_entry(symbol="SOL", open_positions=[], **{**base, "kill_switch": "pause"}) == "kill switch is pause"
    assert check_entry(symbol="SOL", open_positions=[], **{**base, "balance": 135.5}) is None  # 9.7% down
    assert check_entry(symbol="SOL", open_positions=[], **{**base, "balance": 135.0}).startswith("daily loss stop")  # 10%


# ---- account engine --------------------------------------------------------------------------
def test_paper_trades_follow_the_baseline_with_identical_r(world):
    conn, settings = world
    win = add_trade(conn, "XRP", "long", T0 + H, 2.0, 1.98, T0 + H + 30 * M1, target=True)
    loss = add_trade(conn, "LINK", "short", T0 + H + 5 * M1, 20.0, 20.2, T0 + H + 40 * M1, 20.2)
    add_trade(conn, "SOL", "long", T0 + H, 150.0, 148.5, variant=CHALLENGER)  # not the baseline: ignored
    add_trade(conn, "SOL", "long", T0 + H + M1, 150.0, 148.5, taken=0)        # counterfactual: ignored
    counts = AccountEngine(settings, conn).process()
    assert (counts["opened"], counts["rejected"], counts["settled"]) == (2, 0, 2)
    rows = conn.execute("SELECT * FROM account_trades ORDER BY entry_time").fetchall()
    assert [r["trade_id"] for r in rows] == [win, loss] and {r["status"] for r in rows} == {"closed"}
    for r in rows:
        exploration_r = conn.execute("SELECT r_net FROM trades WHERE id = ?", (r["trade_id"],)).fetchone()[0]
        assert r["r_net"] == pytest.approx(exploration_r, abs=1e-9)
        assert r["risk_usd"] == pytest.approx(3.0)  # 2% of 150: the win closed after LINK's entry
    assert paper(conn, win)["pnl_usd"] > 0 > paper(conn, loss)["pnl_usd"]
    assert balance(conn) == pytest.approx(150 + sum(r["pnl_usd"] for r in rows))
    assert consistency_issues(conn) == (2, [])


def test_signals_are_handled_in_time_order(world):
    conn, settings = world
    a = add_trade(conn, "XRP", "long", T0 + H, 2.0, 1.98, T0 + H + 10 * M1, 2.03)
    blocked = add_trade(conn, "XRP", "short", T0 + H + 5 * M1, 2.01, 2.03, T0 + H + 20 * M1, 2.0)  # A still open
    b = add_trade(conn, "XRP", "long", T0 + H + 15 * M1, 2.02, 2.0)                                 # A has closed
    same_time = add_trade(conn, "XRP", "long", T0 + H + 15 * M1, 2.02, 2.0, tf="15m")              # B came first
    AccountEngine(settings, conn).process()
    assert paper(conn, a)["status"] == "closed"
    assert paper(conn, blocked)["reject_reason"] == "XRP already has an open position"
    assert paper(conn, same_time)["reject_reason"] == "XRP already has an open position"
    assert paper(conn, b)["status"] == "open"
    assert paper(conn, b)["balance_before"] == pytest.approx(150 + paper(conn, a)["pnl_usd"])  # A settled first
    assert paper(conn, b)["risk_usd"] == pytest.approx(0.02 * paper(conn, b)["balance_before"], rel=1e-3)


def test_max_open_positions(world):
    conn, settings = world
    add_trade(conn, "XRP", "long", T0 + H, 2.0, 1.98)
    add_trade(conn, "LINK", "long", T0 + H + M1, 20.0, 19.8)
    sol = add_trade(conn, "SOL", "long", T0 + H + 2 * M1, 150.0, 148.5)
    AccountEngine(settings, conn).process()
    assert paper(conn, sol)["reject_reason"] == "max 2 open positions"
    assert conn.execute("SELECT count(*) FROM account_trades WHERE status = 'open'").fetchone()[0] == 2


def test_daily_loss_stop_pauses_only_the_paper_account_until_midnight_utc(world):
    conn, settings = world
    gap = add_trade(conn, "XRP", "long", T0 + H, 2.0, 1.98, T0 + H + 5 * M1, 1.9)  # gapped through the stop: -5R
    blocked = add_trade(conn, "SOL", "long", T0 + 2 * H, 150.0, 148.5)
    next_day = add_trade(conn, "SOL", "long", T0 + DAY + H, 150.0, 148.5, tf="15m")
    exploration_before = conn.execute("SELECT * FROM trades ORDER BY id").fetchall()
    AccountEngine(settings, conn).process()
    loss = paper(conn, gap)["pnl_usd"]
    assert loss < -0.10 * 150
    assert paper(conn, blocked)["reject_reason"].startswith("daily loss stop")
    assert paper(conn, next_day)["status"] == "open"  # the stop resets at 00:00 UTC
    assert paper(conn, next_day)["balance_before"] == pytest.approx(150 + loss)
    # The exploration book is untouched: the blocked signal is still a taken, open exploration trade.
    assert [tuple(r) for r in conn.execute("SELECT * FROM trades ORDER BY id")] == [tuple(r) for r in exploration_before]
    assert account_report(conn, settings)["daily_stop_days"] == 1


def test_kill_switch_pause_and_close_all(world):
    conn, settings = world
    position = add_trade(conn, "XRP", "long", T0 + H, 2.0, 1.98)
    engine = AccountEngine(settings, conn)
    engine.process()
    add_candle(conn, "XRP", T0 + H + 30 * M1, 2.05)
    set_kill_switch(conn, "close_all", "test")
    counts = engine.process()
    assert counts["closed_by_kill_switch"] == 1 and get_kill_switch(conn) == "pause"
    row = paper(conn, position)
    assert (row["status"], row["exit_reason"], row["exit_time"]) == ("closed", "kill switch", T0 + H + 31 * M1)
    entry_fill, exit_fill = 2.0 * (1 + COSTS.slippage), 2.05 * (1 - COSTS.slippage)
    expected = 150 * (exit_fill - entry_fill) - 150 * (entry_fill + exit_fill) * COSTS.taker_fee
    assert row["pnl_usd"] == pytest.approx(expected)
    assert conn.execute("SELECT status FROM trades WHERE id = ?", (position,)).fetchone()[0] == "open"  # exploration goes on
    paused = add_trade(conn, "SOL", "long", T0 + 2 * H, 150.0, 148.5)
    engine.process()
    assert paper(conn, paused)["reject_reason"] == "kill switch is pause"
    set_kill_switch(conn, "off", "test")
    resumed = add_trade(conn, "SOL", "long", T0 + 3 * H, 150.0, 148.5)
    engine.process()
    assert paper(conn, resumed)["status"] == "open"
    assert consistency_issues(conn) == (2, [])
    audit = conn.execute("SELECT new_json FROM settings_audit WHERE key = 'kill_switch' ORDER BY id").fetchall()
    assert [json.loads(r[0]) for r in audit] == ["close_all", "pause", "off"]


def test_processing_again_or_after_a_restart_changes_nothing(world):
    conn, settings = world
    add_trade(conn, "XRP", "long", T0 + H, 2.0, 1.98, T0 + H + 10 * M1, 2.03)
    add_trade(conn, "LINK", "short", T0 + H + 5 * M1, 20.0, 20.2)
    add_trade(conn, "SOL", "long", T0 + H + 6 * M1, 150.0, 148.5)
    add_trade(conn, "LINK", "long", T0 + H + 7 * M1, 20.0, 19.8)
    AccountEngine(settings, conn).process()
    before = [tuple(r) for r in conn.execute("SELECT * FROM account_trades ORDER BY id")]
    state = "SELECT balance, day, day_start_balance, last_entry_time, baseline FROM account_state"
    state_before = tuple(conn.execute(state).fetchone())
    counts = AccountEngine(settings, conn).process()  # a new engine, as after a restart
    assert sum(counts.values()) == 0
    assert [tuple(r) for r in conn.execute("SELECT * FROM account_trades ORDER BY id")] == before
    assert tuple(conn.execute(state).fetchone()) == state_before


def test_a_late_signal_is_recorded_but_not_traded(world):
    conn, settings = world
    add_trade(conn, "XRP", "long", T0 + H + 10 * M1, 2.0, 1.98)
    engine = AccountEngine(settings, conn)
    engine.process()
    late = add_trade(conn, "SOL", "long", T0 + H, 150.0, 148.5, created_at=now_ms() + 60_000)
    engine.process()
    assert (paper(conn, late)["status"], paper(conn, late)["reject_reason"]) == ("rejected", LATE)


def test_a_new_baseline_is_followed_from_its_promotion_on(world):
    conn, settings = world
    add_trade(conn, "XRP", "long", T0 + H, 2.0, 1.98)
    old = add_trade(conn, "LINK", "long", T0 + 2 * H, 20.0, 19.8, variant=CHALLENGER)
    engine = AccountEngine(settings, conn)
    engine.process()
    with conn:
        conn.execute("UPDATE variants SET role = CASE id WHEN ? THEN 'baseline' ELSE 'retired' END", (CHALLENGER,))
    new = add_trade(conn, "LINK", "long", now_ms() + H, 20.0, 19.8, variant=CHALLENGER)
    engine.process()
    assert paper(conn, old) is None and paper(conn, new)["status"] == "open"
    assert conn.execute("SELECT baseline FROM account_state").fetchone()[0] == CHALLENGER


def test_the_account_waits_for_market_info(world):
    conn, settings = world
    with conn:
        conn.execute("DELETE FROM market_info WHERE symbol = 'LINK'")
    add_trade(conn, "XRP", "long", T0 + H, 2.0, 1.98)
    counts = AccountEngine(settings, conn).process()
    assert counts["waiting_market_info"] == 1
    assert conn.execute("SELECT count(*) FROM account_trades").fetchone()[0] == 0


def test_open_positions_are_valued_at_the_last_price(world):
    conn, settings = world
    add_trade(conn, "SOL", "short", T0 + H, 150.0, 151.5)
    add_candle(conn, "SOL", T0 + H + 10 * M1, 148.5)
    engine = AccountEngine(settings, conn)
    engine.process()
    [position] = engine.mark_to_market()
    entry_fill, exit_fill = 150.0 * (1 - COSTS.slippage), 148.5 * (1 + COSTS.slippage)
    expected = 2.0 * (entry_fill - exit_fill) - 2.0 * (entry_fill + exit_fill) * COSTS.taker_fee
    assert position["last_price"] == 148.5 and position["unrealized_usd"] == pytest.approx(expected)
    report = account_report(conn, settings)
    assert report["balance"] == 150.0 and report["equity"] == pytest.approx(150.0 + expected)
    assert report["gate_met"] is False


def test_limit_entries_pay_the_maker_fee_in_the_paper_account_too(world):
    conn, settings = world
    trade = add_trade(conn, "XRP", "long", T0 + H, 2.0, 1.98, T0 + H + 30 * M1, target=True, limit=True)
    AccountEngine(settings, conn).process()
    row = paper(conn, trade)
    assert row["entry_fill"] == 2.0  # no slippage on a limit fill
    exploration_r = conn.execute("SELECT r_net FROM trades WHERE id = ?", (trade,)).fetchone()[0]
    assert row["r_net"] == pytest.approx(exploration_r, abs=1e-9)
    assert row["fees_usd"] == pytest.approx(row["qty"] * (2.0 + 2.03) * COSTS.maker_fee, rel=1e-6)


def test_a_forward_test_starts_fresh_and_ignores_history(world):
    conn, settings = world
    old = add_trade(conn, "XRP", "long", T0 + H, 2.0, 1.98, T0 + H + 30 * M1, target=True)
    engine = AccountEngine(settings, conn)
    engine.process()
    assert paper(conn, old)["status"] == "closed" and balance(conn) != 150.0
    reset_account(conn, settings, from_now=True)
    assert balance(conn) == 150.0 and paper(conn, old) is None
    engine.process()  # the old signal is history: not taken again
    assert paper(conn, old) is None
    new = add_trade(conn, "SOL", "long", now_ms() + H, 150.0, 148.5)
    engine.process()
    assert paper(conn, new)["status"] == "open"


def test_the_gate_counts_the_baselines_forward_shadow_trades(world):
    conn, settings = world
    add_trade(conn, "XRP", "long", T0 + H, 2.0, 1.98, T0 + H + 30 * M1, target=True)  # history: not counted
    reset_account(conn, settings, from_now=True)
    start = conn.execute("SELECT started_at FROM account_state").fetchone()[0]
    later = start + H
    add_trade(conn, "SOL", "long", later, 150.0, 148.5, later + 30 * M1, target=True)
    add_trade(conn, "LINK", "short", later + M1, 20.0, 20.2, later + 40 * M1, 20.2)
    add_trade(conn, "XRP", "long", later + 2 * M1, 2.0, 1.98, later + 50 * M1, target=True, variant=CHALLENGER)
    report = account_report(conn, settings)
    assert report["forward_start"] == start and report["strategy_trades"] == 2  # baseline only, since the start
    gate = {c["name"]: c["value"] for c in report["gate"]}
    assert gate["strategy trades (forward, every signal)"] == f"2 / {settings.goal.min_trades}"
    assert settings.goal.min_trades == 100


def test_no_limits_means_every_signal_is_taken(settings):
    settings.paper_account.max_positions = None
    settings.paper_account.max_positions_per_coin = None
    settings.paper_account.daily_loss_stop = None
    open_positions = [OpenPosition("XRP", "long", 100.0)] * 7
    base = {"day_start_balance": 150.0, "rules": settings.paper_account, "kill_switch": "off"}
    assert check_entry(symbol="XRP", open_positions=open_positions, balance=60.0, **base) is None  # -60% today
    assert check_entry(symbol="XRP", open_positions=[], balance=150.0, **{**base, "kill_switch": "pause"}) == "kill switch is pause"


def test_the_configured_demo_account_has_no_trade_limits(repo_root):
    from tradeagent.config import load_settings

    rules = load_settings(repo_root).paper_account
    assert (rules.max_positions, rules.max_positions_per_coin, rules.daily_loss_stop) == (None, None, None)
