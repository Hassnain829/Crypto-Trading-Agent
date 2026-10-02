import pytest

from tradeagent.sim.simulator import Costs, TradeState, apply_funding, close_now, open_trade, results, step, trail

FREE = Costs(maker_fee=0.0, taker_fee=0.0, slippage=0.0)
REAL = Costs(maker_fee=0.0002, taker_fee=0.0005, slippage=0.0002)


def _long(mode="fixed", costs=FREE, **kw):
    params = dict(side="long", mode=mode, entry_time=0, entry_ref=100.0, stop=99.0, take_profit_r=1.5,
                  partial_r=1.0, partial_fraction=0.5, trail_lookback=3, costs=costs)
    params.update(kw)
    return open_trade(**params)


def test_long_hits_target():
    s = _long()
    assert s.target == pytest.approx(101.5)
    step(s, (0, 100.0, 100.8, 99.6, 100.5), FREE)
    assert not s.closed
    step(s, (60_000, 100.5, 101.6, 100.4, 101.2), FREE)
    assert s.closed and s.exit_reason == "target"
    r = results(s, FREE)
    assert r["r_net"] == pytest.approx(1.5)
    assert r["mfe_r"] == pytest.approx(1.6) and r["mae_r"] == pytest.approx(-0.4)


def test_long_hits_stop():
    s = _long()
    step(s, (0, 100.0, 100.2, 98.9, 99.1), FREE)
    assert s.closed and s.exit_reason == "stop"
    assert results(s, FREE)["r_net"] == pytest.approx(-1.0)


def test_stop_and_target_in_one_candle_counts_the_stop():
    s = _long()
    step(s, (0, 100.0, 101.7, 98.8, 101.0), FREE)
    assert s.closed and s.exit_reason == "stop" and s.ambiguous


def test_gap_through_the_stop_fills_at_the_open():
    s = _long()
    step(s, (0, 100.0, 100.1, 99.5, 99.6), FREE)
    step(s, (60_000, 98.5, 98.9, 98.0, 98.2), FREE)
    assert results(s, FREE)["r_net"] == pytest.approx(-1.5)


def test_short_mirror_case():
    s = open_trade(side="short", mode="fixed", entry_time=0, entry_ref=100.0, stop=101.0, take_profit_r=2.0,
                   partial_r=1.0, partial_fraction=0.5, trail_lookback=3, costs=FREE)
    assert s.target == pytest.approx(98.0)
    step(s, (0, 100.0, 100.5, 97.9, 98.1), FREE)
    assert s.exit_reason == "target"
    assert results(s, FREE)["r_net"] == pytest.approx(2.0)


def test_costs_match_the_fee_formula():
    # GOALS-AND-METRICS.md example: 0.3% stop, taker 0.05% both ways -> fees about 0.33R
    taker_only = Costs(maker_fee=0.0005, taker_fee=0.0005, slippage=0.0)
    s = open_trade(side="long", mode="fixed", entry_time=0, entry_ref=100.0, stop=99.7, take_profit_r=1.5,
                   partial_r=1.0, partial_fraction=0.5, trail_lookback=3, costs=taker_only)
    step(s, (0, 100.0, 100.0, 99.6, 99.7), taker_only)
    r = results(s, taker_only)
    assert r["fees_r"] == pytest.approx((100.0 * 0.0005 + 99.7 * 0.0005) / 0.3)
    assert r["fees_r"] == pytest.approx(0.33, abs=0.01)
    assert r["r_net"] == pytest.approx(-1.0 - r["fees_r"])


def test_slippage_is_charged_on_entry_and_stop_but_not_on_limit_exits():
    s = _long(costs=REAL)
    assert s.entry_fill == pytest.approx(100.02)
    step(s, (0, 100.0, 101.6, 99.9, 101.0), REAL)  # target, limit exit
    r = results(s, REAL)
    assert r["slippage_r"] == pytest.approx(0.02)
    assert r["fees_r"] == pytest.approx(100.02 * 0.0005 + 101.5 * 0.0002)
    assert r["r_net"] == pytest.approx(r["r_gross"] - r["slippage_r"] - r["fees_r"])


def test_hybrid_partial_breakeven_and_trailing():
    s = _long(mode="hybrid", costs=REAL)
    assert s.target is None and s.partial_price == pytest.approx(101.0)
    step(s, (0, 100.0, 101.1, 99.8, 101.0), REAL)  # partial at 1R
    assert s.partial_done and s.remaining == pytest.approx(0.5)
    assert s.stop == pytest.approx(100.02 * (1 + 2 * 0.0005 + 0.0002))  # break-even plus fees
    trail(s, [(0, 0, 0, 101.2, 0), (0, 0, 0, 101.5, 0), (0, 0, 0, 101.4, 0)])
    assert s.stop == pytest.approx(101.2)
    trail(s, [(0, 0, 0, 100.0, 0), (0, 0, 0, 100.5, 0), (0, 0, 0, 100.4, 0)])
    assert s.stop == pytest.approx(101.2)  # never moves back
    step(s, (60_000, 101.5, 101.6, 101.1, 101.15), REAL)
    assert s.closed and s.exit_reason == "trail"
    r = results(s, REAL)
    assert r["r_gross"] == pytest.approx(0.5 * 1.0 + 0.5 * 1.2)


def test_hybrid_stop_before_partial_is_a_full_loss():
    s = _long(mode="hybrid")
    step(s, (0, 100.0, 100.4, 98.9, 99.0), FREE)
    assert s.exit_reason == "stop" and results(s, FREE)["r_net"] == pytest.approx(-1.0)


def test_funding_and_time_limit():
    s = _long()
    apply_funding(s, 0.0001, 100.0)  # long pays 0.01% of 100
    close_now(s, 120_000, 100.5, FREE, "timeout")
    r = results(s, FREE)
    assert r["funding_r"] == pytest.approx(0.01)
    assert r["r_net"] == pytest.approx(0.5 - 0.01)
    assert s.exit_reason == "timeout"


def test_state_survives_json_roundtrip():
    s = _long(mode="hybrid", costs=REAL)
    step(s, (0, 100.0, 101.1, 99.8, 101.0), REAL)
    copy = TradeState.from_json(s.to_json())
    assert copy == s


def test_stop_on_the_wrong_side_is_rejected():
    with pytest.raises(ValueError):
        _long(stop=100.5)
