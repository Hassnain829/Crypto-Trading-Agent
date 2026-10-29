"""Chart-pattern breakouts (setups/chart_patterns.py), ported from the 2026-10-23 research."""

import numpy as np

from tradeagent.setups.chart_patterns import breakout_masks, breakouts


def _bars(closes):
    c = np.array(closes, dtype=float)
    o = np.r_[c[0], c[:-1]]
    return o, np.maximum(o, c) + 0.2, np.minimum(o, c) - 0.2, c


def _double_bottom():
    path = [100.0] * 30
    for a, b, n in ((100, 90, 10), (90, 100, 10), (100, 90.3, 10), (90.3, 103, 13)):
        path += list(np.linspace(a, b, n + 1))[1:]
    return _bars(path)


def test_a_double_bottom_breaks_out_when_a_close_clears_the_high_between_the_lows():
    o, h, l, c = _double_bottom()
    found = breakouts(o, h, l, c)
    assert found["double bottom"][0] == 1
    j1, j2 = int(np.argmin(l[:50])), 50 + int(np.argmin(l[50:]))
    middle = h[j1:j2 + 1].max()
    first = next(i for i in range(j2 + 3, len(c)) if c[i] > middle)
    assert set(found["double bottom"][1]) == {first}  # equal lows can find it twice; the candle is what counts


def test_the_newest_candle_is_checked_only_live():
    o, h, l, c = _double_bottom()
    t = breakouts(o, h, l, c)["double bottom"][1][0]
    cut = slice(0, t + 1)  # the breakout candle is the newest one
    assert "double bottom" not in breakouts(o[cut], h[cut], l[cut], c[cut])
    assert set(breakouts(o[cut], h[cut], l[cut], c[cut], include_last=True)["double bottom"][1]) == {t}


def test_a_breakout_never_depends_on_later_candles():
    rng = np.random.default_rng(3)
    o, h, l, c = _bars(100 + np.cumsum(rng.normal(0, 1, 400)))
    full_bull, full_bear = breakout_masks(o, h, l, c)
    for t in range(120, 398):
        bull, bear = breakout_masks(o[:t + 1], h[:t + 1], l[:t + 1], c[:t + 1], include_last=True)
        assert (bull[-1], bear[-1]) == (full_bull[t], full_bear[t]), t
