"""Paper trades drawn on TradingView: what is drawn, and when it is drawn again (with a fake CDP)."""

import asyncio
import json

import pytest

from tradeagent.account.engine import AccountEngine
from tradeagent.journal import connect, migrate
from tradeagent.journal.db import now_ms
from tradeagent.sim.simulator import Costs, close_now, open_trade, results, step
from tradeagent.tv.drawings import TradeDrawer, drawing_spec

M1, H = 60_000, 3_600_000
T0 = 1_790_208_000_000  # 2026-09-24 00:00 UTC
COSTS = Costs(maker_fee=0.0002, taker_fee=0.0005, slippage=0.0002)


class FakeCDP:
    def __init__(self):
        self.calls = []

    async def evaluate(self, page, expression, *, await_promise=False):
        self.calls.append((page, expression))
        if "createMultipointShape" in expression:
            return {"ids": [f"shape{len(self.calls)}", f"label{len(self.calls)}"], "chart": 1}
        return 2  # removed


@pytest.fixture
def world(settings):
    conn = connect(settings.resolve(settings.journal.path))
    migrate(conn)
    conn.execute("INSERT INTO variants (id, params_json, params_hash, role, parent, created_at)"
                 " VALUES ('v0-aaaaaa', '{}', 'a', 'baseline', NULL, 0)")
    conn.executemany("INSERT INTO market_info (symbol, tick_size, step_size, min_qty, min_notional, updated_at) VALUES (?, ?, ?, ?, ?, 0)",
                     [("XRP", 0.0001, 0.1, 0.1, 5.0), ("LINK", 0.001, 0.01, 0.01, 20.0), ("SOL", 0.01, 0.01, 0.01, 5.0)])
    conn.commit()
    yield conn, settings
    conn.close()


def add_trade(conn, state, closed):
    r = results(state, COSTS)["r_net"] if closed else None
    cur = conn.execute(
        "INSERT INTO trades (book, variant_id, symbol, timeframe, side, signal_version, trigger_time, confirm_time,"
        " entry_time, taken, exit_mode, entry_ref, stop_initial, target, status, exit_time, exit_reason, r_net,"
        " context_json, state_json, created_at, updated_at)"
        " VALUES ('exploration', 'v0-aaaaaa', 'XRP', '15m', 'long', 1, ?, ?, ?, 1, 'fixed', ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?)",
        (state.entry_time - 30 * M1, state.entry_time - 15 * M1, state.entry_time, state.entry_ref, state.stop_initial,
         state.target, "closed" if closed else "open", state.last_time if closed else None, state.exit_reason, r,
         json.dumps(state.to_json()), now_ms(), now_ms()),
    )
    conn.commit()
    return cur.lastrowid


def test_open_then_closed_trades_are_drawn_and_redrawn(world):
    conn, settings = world
    state = open_trade(side="long", mode="fixed", entry_time=T0 + H, entry_ref=2.0, stop=1.97, take_profit_r=1.5,
                       partial_r=1.0, partial_fraction=0.5, trail_lookback=3, costs=COSTS, limit_entry=True)
    trade_id = add_trade(conn, state, closed=False)
    AccountEngine(settings, conn).process()
    cdp = FakeCDP()
    pages = {settings.layout_for("XRP"): "xrp-page"}

    async def provider():
        return pages

    drawer = TradeDrawer(settings, conn, cdp, provider)
    assert asyncio.run(drawer.sync())["drawn"] == 1
    assert asyncio.run(drawer.sync()) == {}  # nothing changed: nothing drawn again
    page, js = cdp.calls[0]
    assert page == "xrp-page" and '"long"' in js and '"label": null' in js

    step(state, (T0 + H + 45 * M1, 2.0, 2.05, 1.99, 2.04), COSTS)  # the target is hit
    assert state.closed
    with conn:
        conn.execute("UPDATE trades SET status = 'closed', exit_time = ?, exit_reason = ?, r_net = ?, state_json = ?"
                     " WHERE id = ?", (state.last_time, state.exit_reason, results(state, COSTS)["r_net"],
                                       json.dumps(state.to_json()), trade_id))
    AccountEngine(settings, conn).process()
    counts = asyncio.run(drawer.sync())
    assert counts["redrawn"] == 1
    assert "removeEntity" in cdp.calls[-2][1]  # the open drawing is removed first
    assert "TP +" in cdp.calls[-1][1]
    row = conn.execute("SELECT drawn_state, shape_ids FROM trade_drawings").fetchone()
    assert row["drawn_state"] == "closed" and len(json.loads(row["shape_ids"])) == 2

    assert asyncio.run(drawer.clear()) == 2
    assert conn.execute("SELECT count(*) FROM trade_drawings").fetchone()[0] == 0


def test_drawing_spec_uses_the_paper_position(world, settings):
    conn, settings = world
    state = open_trade(side="long", mode="fixed", entry_time=T0 + H, entry_ref=2.0, stop=1.97, take_profit_r=1.5,
                       partial_r=1.0, partial_fraction=0.5, trail_lookback=3, costs=COSTS)
    close_now(state, T0 + H + 30 * M1, 1.97, COSTS, "stop")
    add_trade(conn, state, closed=True)
    AccountEngine(settings, conn).process()
    trade = TradeDrawer(settings, conn, FakeCDP(), None)._trades()[0]
    spec = drawing_spec(trade, settings, now_ms())
    assert spec["symbol"] == "BINANCE:XRPUSDT.P" and spec["interval"] == "15"
    assert spec["entry"] == pytest.approx(2.0 * (1 + COSTS.slippage)) and spec["stop"] == 1.97
    assert spec["entry_time"] == (T0 + H) // 1000 and spec["end_time"] == (T0 + H + 30 * M1) // 1000
    assert spec["label"].startswith("SL -") and spec["label_price"] == 1.97 and spec["risk_pct"] == 2.0
