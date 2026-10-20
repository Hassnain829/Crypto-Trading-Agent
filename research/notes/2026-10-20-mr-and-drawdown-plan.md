# Two tests, past data only: plan written before any result (2026-10-20)

The user approved testing these two ideas, with no change to the agent. Each is one run.

## Test A: VWAP band mean reversion (a second strategy, for range markets)

The trend engine (Q-Trend) loses in chop. A mean-reversion engine might earn there, so the two would cover each other.

- **Data:** the TradingView snapshots already stored (session VWAP and its #2 bands, which the agent reads) on 5m and 15m:
  - XRP, SOL and ETH from the live journal
  - the eight screen coins from data/research/coin_screen.db

  Binance 1m candles for the fills.
- **Long rule** (the short rule is the mirror image with the upper band):
  - candle i closes below the lower #2 band
  - candle i+1 closes back above it and is bullish
  - the signal comes at the close of i+1
- **Entry:** a limit order at the next 1m open, filled only if that minute trades through it (the same fill rule as the agent), with maker fees.
- **Stop:** the lowest low of candles i and i+1, or for shorts the highest high. The signal is skipped when the stop is closer than 0.5%: at the fees modelled, a tighter stop costs more than 0.2R.
- **Target:** the VWAP value at the signal candle's close (a fixed price). The signal is skipped when the target is less than 0.5R away.
- **Time stop:** 8 hours, a market exit at the 1m open. The session VWAP resets at 00:00 UTC.
- **One trade at a time** per coin and timeframe.
- Fees and slippage as in settings.yaml; the project's simulator (stop first when a candle touches both).

**Pass rule:**
- expectancy at least +0.15R
- profit factor at least 1.3
- win rate at least 60%
- positive in both halves
- positive on XRP, SOL and ETH together
- the correlation of daily R with the trend engine's daily R is at most 0.3, so the two can run side by side

## Test B: drawdown-based sizing (capital protection)

- **Data:** the baseline's taken trades on XRP, SOL and ETH (history and forward), in entry order, one trade at a time, $150 start, 2% risk, compounding.
- **Rule:** while the equity is more than 8% below its peak, the risk is halved (1%). At a new peak it goes back to 2%.
- **Pass rule:**
  - the maximum drawdown is at least 25% lower than with a constant 2%
  - the final equity is at most 10% lower
  - this holds in both halves of the trades

## Results (2026-10-20, one run each)

### Equity by target (asked by the user)

254 taken trades over 116 days, $150 start, 2% risk, one trade at a time with compounding. Outcomes at smaller targets come from each trade's maximum favourable excursion.

| Target | Win | Final | Return | Max DD |
|---|---|---|---|---|
| 0.25R | 85% | $183 | +22% | 12.7% |
| 0.33R | 81% | $192 | +28% | 17.4% |
| 0.50R | 74% | $221 | +47% | 18.4% |
| 0.75R | 67% | $296 | +97% | 15.1% |
| 1.00R | 59% | $331 | +121% | 17.6% |
| 1.25R | 55% | $395 | +164% | 20.5% |
| **1.50R (current)** | **53%** | **$505** | **+237%** | 20.1% |

A higher win rate costs most of the return, and the drawdown is not much smaller.

### Test B: drawdown-based sizing (half risk while more than 8% below the peak)

| Sample | Constant 2% | Protected | Drawdown | Equity |
|---|---|---|---|---|
| All | $505, max DD 20.1% | $394, max DD 15.1% | -25% | -21.9% |
| Half 1 | $239, 20.1% | $214, 15.1% | -25% | -10.2% |
| Half 2 | $317, 15.5% | $278, 13.4% | -14% | -12.4% |

**No pass.** The drawdowns are short, and the strategy recovers quickly, so halving the risk mostly slows the recovery. A constant 2% (with the 12% open-risk budget for clustered trades) is better.

### Test A: VWAP #2 band mean reversion

| Sample | Trades | Won | R / trade | PF |
|---|---|---|---|---|
| All 11 coins | 2,510 | 35% | -0.147 | 0.79 |
| XRP + SOL + ETH | 393 | 41% | -0.067 | 0.89 |
| The eight screen coins | 2,117 | 34% | -0.162 | 0.78 |

- **Halves:** all coins -0.06 / -0.23; current coins -0.09 / -0.04.
- **Exits:** 1,596 stops, 736 targets, 178 time stops.
- **Correlation with the trend engine:** -0.10 (it would diversify, but it has no edge).
- **No pass.** On crypto 5m/15m, a close back inside the #2 band does not mean-revert to the VWAP often enough: the moves continue. Not retested with other parameters.
