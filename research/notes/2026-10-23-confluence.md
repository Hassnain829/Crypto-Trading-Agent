# 2026-10-23: indicators and candle patterns together (research/tools/confluence_check.py)

The user asked:
- whether the agent should read the agent's indicators and the candle patterns together
- how the indicators relate to candle patterns
- about their example of BTC's daily three-line strike with the indicators agreeing

## How the agent's 15m signals line up with 15m candle patterns (the design, 4 years, 3,263 trades)

| The signal candle is | trades | R |
|---|---|---|
| a pattern in the trade's direction | 376 (12%) | +0.070R |
| only a pattern against it | 615 (19%) | +0.048R |
| no pattern | 2,272 (70%) | +0.030R |

- **A same-way marubozu on the signal candle:**
  - bearish marubozu: +0.366R (70 trades; +0.258 / +0.400)
  - bullish marubozu: +0.188R (69 trades; +0.507 / +0.007)
- **A signal after three same-coloured candles is late:** identical three crows, same way, -0.214R (91; both halves
  negative).
- These samples are small. They are ideas, not rules.

## The three-line strike traded in the direction of its strike candle (4 coins, 4 years)

| tf | short (3 green + big red) | long (3 red + big green) | chance short / long |
|---|---|---|---|
| 15m | -0.200R (1,890) | -0.313R (1,908) | -0.307R / -0.332R |
| 1h | -0.050R (639) | -0.048R (507) | -0.220R / -0.229R |
| 4h | -0.131R (171) | -0.045R (134) | -0.157R / -0.166R |
| 1d | -0.256R (27) | -0.312R (23) | -0.132R / -0.060R |

- In the strike candle's direction it beats chance clearly on 1h (+0.17R), but it still loses after costs.
- On daily candles it formed only 50 times in 4 years on 4 coins.

## BTC on 2026-10-23 (UTC daily candles)

- **The last days:**
  - 10-19: a shooting star and a bearish spinning top
  - 10-20 and 10-21: green
  - 10-22: a big red candle (84,050 -> 81,385) that swallowed the two green candles before it. That is not a textbook
    three-line strike, which needs three.
  - 10-23 (open): a small long-legged doji
- **Indicators (Python copies):**
  - Q-Trend 4h flipped to sell on 10-22 16:00 UTC.
  - Klinger 4h is below its signal.
  - Q-Trend daily is still in its July buy trend, but the price (81,427) is below its trend line (82,969).
  - Klinger daily turned below its signal today.
- The demo does not trade BTC. For XRP/SOL/ETH trades, BTC's direction has not helped (2026-10-23 gate-replay note).

## Higher-timeframe patterns checked at the same time as the lower-timeframe signal

| HTF pattern, with the agent's own 15m signal | with | none |
|---|---|---|
| last 1h candle (or 1d) in the trade's direction | +0.099R to +0.114R | -0.004R to -0.028R |
| 1h, last 2 candles | +0.060R | -0.002R |
| 1d, last 2 candles | +0.057R | +0.032R |
| 4h candle pattern | -0.011R | +0.091R |
| 4h chart breakout | +0.199R (146) | +0.016R |

- Patterns alone, as the direction for 15m/5m scalps, lose (htf-bias note).
- **Indicators plus a higher-timeframe pattern** is the combination that works. It replicated on unseen trades.
