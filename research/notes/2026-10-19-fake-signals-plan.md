# Fake signals: what marks a Q-Trend signal the market goes against? Plan written before any result (2026-10-19)

The user sees many chart signals (Q-Trend, Zero Lag) after which the market moves the other way. The agent trades Q-Trend flips confirmed by Klinger and candle direction. The question: what was visible at the decision that marks the fake ones?

## Sample

- **Every baseline signal that became a simulated trade, on XRP, SOL and ETH:**
  - the taken trades: primary sample, about 254
  - the skipped signals (the 1.5% minimum-stop filter): replication sample, about 977
- **A fake signal is a trade that lost** (net R below 0). Outcomes come from the shadow simulator: same fills, fees and slippage.
- **No lookahead:** every feature uses only snapshots and candles closed at the decision (the confirmation candle's close).
- **Halves:** split by entry time.

## Features (new; nothing already tested is retested)

Already tested and not used again here:
- VWAP side
- MACD trend
- 1h and 4h trend
- the chart's own Zero Lag trend
- the 15m trend for 5m signals (the trend15 challenger)
- sessions
- the Trendline and OI tiers

New features, read from the TradingView snapshots:

| # | Feature | Flag | Idea |
|---|---|---|---|
| F1 | Chop | 3 or more Q-Trend signals (buy or sell) on the same chart in the 48 candles before the trigger | Frequent flips mean a range: the next flip is likely fake |
| F2 | Late entry | Distance of the confirmation close from the Q-Trend trend line, as a share of the price, above the sample median | The move already happened: an exhausted entry |
| F3 | Weak candle | The confirming candle's body is less than 50% of its range (TradingView OHLC) | No conviction at the confirmation |
| F4 | Low volume | The confirming candle's volume is below the average of the 20 candles before it | A move without participation |
| F5 | Weak Klinger | The absolute Klinger histogram at the confirmation is below the median of its absolute values over the 100 candles before | A weak volume confirmation |

## Pass rule (the same as the liquidity plan)

1. On the taken trades: a difference of at least 0.15R in both halves, in the same direction, with at least 25 trades per group per half.
2. The skipped signals must point the same way.
3. A feature that misses only the trade count, while the skipped signals pass fully, counts as "promising", as OI did.

## If something passes

A fake-signal flag becomes a lower size tier: for example C at 1%, with B 2% and A 3% (Trendline or OI). It never skips the trade (the user's rule). It is recorded on every trade first, then forward-checked.

## Results (2026-10-19)

**What happens to the chart's Q-Trend signals.** XRP, SOL and ETH, baseline history plus the forward test, 1,593 triggers in all:

| Step | Signals | Outcome |
|---|---|---|
| No Klinger/candle confirmation within 3 candles | 134 | No trade |
| Confirmed, stop under 1.5% (skipped) | 1,015 | 37% won, -0.194R, target hit 37%: **these are the "fake" signals the chart shows** |
| Confirmed, limit not filled | 177 | No trade |
| **Taken** | **254** | **53% won, +0.254R, target hit 46%** |

The agent already trades only about 16% of the chart's signals; most fakes are removed by the confirmation and the minimum stop.

**Five new fake-signal features: none passes.** The table gives the expectancy difference, flag minus other, in half 1 / half 2.

| Feature | Taken trades | Skipped signals |
|---|---|---|
| F1 chop (3+ signals in 48 candles) | +0.00 / +0.32; only 9 trades flagged | +0.35 / -0.16 |
| F2 late (far from the trend line) | -0.20 / +0.14 | -0.07 / -0.02 |
| F3 weak candle (body < 50%) | +0.06 / +0.27 (weak candles did *better*) | +0.02 / +0.03 |
| F4 low volume | -0.08 / +0.20 | +0.08 / -0.08 |
| F5 weak Klinger | -0.46 / +0.90; 20 trades | -0.11 / -0.24 |

**Conclusions:**
- Among the trades the agent takes, the losers cannot be told apart by chop, lateness, candle body, volume or Klinger strength. A loss rate of about 47% is part of a 1.5R strategy: break-even is 40%.
- What does separate them is already in place: the 1.5% minimum stop (the skip), and the quality tiers (Trendline, OI) for sizing.
- Weak Klinger is a mild negative on the skipped signals only. Not adopted.
