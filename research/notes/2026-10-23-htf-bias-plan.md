# 2026-10-23: higher-timeframe candle patterns as the direction, scalps on the lower timeframe (plan, before the results)

The user asked: if the agent read the candlestick patterns of 1h, 4h and 1d, and scalped on 15m or 5m in their direction
(for example shorts after a 4h bearish engulfing), with the same risk rules, would it do better? Chart patterns are rare,
so they should stay as one more factor.

## Data

- XRP, SOL and ETH (the demo's coins) on the 4-year research journal, 2022-10 to 2026-10. BTC is a check.
- Halves split at 2024-10-01.

## The bias

- Any of the 26 first-pass candlestick patterns on a closed 1h, 4h or 1d candle sets a direction.
- It lasts for the next 2 candles of that timeframe (2 h, 8 h, 2 days). 1 and 4 candles are shown as a check.
- A candle with both a bullish and a bearish pattern gives no bias.
- **Chart patterns as a separate bias:** a breakout of a 1h or 4h chart pattern (the double/triple top and bottom, head
  and shoulders, rectangles, triangles, wedges and flags of research/tools/patterns_more.py) in the same way.

## A. Pure pattern scalping (no Q-Trend)

- **Entry:** inside the bias window, the first 15m (or 5m) candle that closes against the bias, a pullback. Enter at the
  next candle's open in the bias direction.
- **Stop and target:** stop at the 10-candle swing of that chart, target 1.5R, at most 2 days, costs 0.14% round trip.
- **Two stop rules:**
  - (i) the agent's: skip when the stop is closer than 1.5%; the next pullback in the window may still qualify
  - (ii) a scalper's: only stops closer than 0.2% are skipped
- One trade per bias window and coin.
- **Chance:** the same entry rule after random non-pattern candles of the same timeframe, with a random direction.

## B. The agent's design with the bias (a hybrid)

- The design's 4-year trades (15m Q-Trend + Klinger + candle, 5m dip entry) split by bias at the decision: with it,
  against it, or none.
- Shows R a trade and how many trades a day remain.

## Judgement

- A scalping version is worth a full account test only if it makes money after costs in both halves on at least 2 of the
  3 coins, and beats chance.
- The hybrid is worth it only if "with bias" beats the design in both halves and keeps enough trades a day.

## Results (research/tools/htf_bias_test.py; data/research/htf_bias.txt)

### A. Pure pattern scalping (XRP+SOL+ETH pooled, window 2; chance = random direction at non-pattern candles)

| Bias -> entry | agent stop (>= 1.5%) | chance | scalper stop (>= 0.2%) |
|---|---|---|---|
| candle 1h -> 15m | 6.2/day, -0.041R | -0.045R | 22.9/day, -0.212R |
| candle 1h -> 5m | 3.5/day, -0.064R | -0.089R | 22.8/day, -0.315R |
| candle 4h -> 15m | 2.7/day, -0.034R | -0.016R | 5.7/day, -0.196R |
| candle 4h -> 5m | 1.9/day, -0.080R | -0.038R | 5.7/day, -0.358R |
| candle 1d -> 15m | 0.8/day, +0.023R (-0.010 / +0.055) | -0.045R | 0.9/day, -0.218R |
| candle 1d -> 5m | 0.7/day, -0.006R | -0.070R | 0.9/day, -0.433R |
| chart 1h -> 15m | 3.4/day, -0.025R | -0.045R | 7.7/day, -0.125R |
| chart 1h -> 5m | 1.8/day, -0.008R | -0.069R | 7.6/day, -0.223R |
| **chart 4h -> 15m** | **1.0/day, +0.056R (+0.036 / +0.074)** | -0.013R | 1.9/day, -0.097R |
| chart 4h -> 5m | 0.7/day, -0.040R | -0.043R | 1.9/day, -0.278R |

- **A candlestick pattern's direction on 1h, 4h or 1d is about as good as a coin flip for lower-timeframe scalps.** It
  loses after costs, and on 4h it is worse than chance. Tight scalper stops lose 0.1-0.4R a trade to costs.
- **Only chart 4h -> 15m with the agent's stop passes the rule.** +0.056R in both halves; XRP +0.072R (+0.020 / +0.113)
  and SOL +0.123R (+0.120 / +0.126) are positive in both halves; ETH -0.062R; BTC +0.018R. Window 1: +0.071R; window 4:
  +0.027R.
  - It is one of about 20 combinations tested (t about 1.8), so it needs the TradingView data, an account test with the
    design, and the overlap with the design's trades before it counts.

### B. The design with the bias (4-year trades, 2.20 a day)

| Bias (2 candles) | with | against | none |
|---|---|---|---|
| candle 1h | +0.060R, 1.19/day (+0.061 / +0.059) | +0.113R (183) | -0.002R, 0.89/day |
| candle 4h | -0.011R | +0.009R | +0.091R |
| candle 1d | +0.057R (+0.056 / +0.058) | +0.030R | +0.032R |
| chart 1h | +0.061R, 0.43/day | -0.138R (94) | +0.039R |
| chart 4h | +0.199R, 0.10/day (+0.095 / +0.314) | +0.117R (457) | +0.016R |

As before, the patterns help the design as a size factor. As a filter they would cut the trades a day.
