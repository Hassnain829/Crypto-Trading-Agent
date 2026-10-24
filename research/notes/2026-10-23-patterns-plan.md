# 2026-10-23: candlestick and chart patterns (plan, written before the results)

The user asked: if the agent knew candlestick patterns and chart patterns like an experienced trader, and watched BTC's
daily and 4h candles, would its trades get better? People say patterns work best on higher timeframes. Do they also work
on 15m and 5m?

No pattern research has been done before. The closest is the Dynamic Trendline Breakout [RFX], a chart-pattern breakout
that already sets quality tier A (+0.59R vs +0.23R as a confirmation, 2026-10-18).

## Data

- Binance USDT-M candles of XRP, SOL, ETH and BTC from the research journal (data/research/long4), 2022-10 to 2026-10.
- 5m and 15m as stored; 1h, 4h and 1d built from 15m (UTC days).
- Halves: before and after 2024-10-01.

## Patterns, textbook definitions (not tuned)

- Shapes: body = |close - open|, range = high - low, average body = mean body of the 10 candles before.
- Trend before the pattern: the close just before its first candle vs the close 10 candles earlier.
- Reversal patterns need the opposite trend before them.

| Group | Bullish | Bearish |
|---|---|---|
| Single | hammer, inverted hammer, dragonfly doji, bullish marubozu | hanging man, shooting star, gravestone doji, bearish marubozu |
| Double | bullish engulfing, bullish harami, piercing line, tweezer bottom, bullish kicker | bearish engulfing, bearish harami, dark cloud cover, tweezer top, bearish kicker |
| Triple | morning star, three white soldiers, three inside up, three outside up | evening star, three black crows, three inside down, three outside down |
| Chart (4h, 1d) | double bottom, inverse head and shoulders | double top, head and shoulders |

- Marubozu and soldiers/crows are momentum patterns, so they have no trend condition.
- Chart patterns use pivots confirmed 3 candles later, so there is no look-ahead:
  - double bottom/top: two pivots within 1 ATR(14), 5 to 60 candles apart; entry when a close breaks the pivot between them
  - head and shoulders: a head at least 0.5 ATR beyond two shoulders that are within 1 ATR of each other; entry on a close
    through the neckline (the nearer of the two troughs)

## Test 1: does a pattern work on its own?

- Trade rule:
  - enter at the next candle's open in the pattern's direction
  - stop beyond the pattern's extreme (its low for bullish)
  - target 1.5R, at most 24 candles, then out at the close
  - if the stop and the target are hit in the same candle, it counts as a stop
- Costs: 0.14% round trip (fees and slippage) in R.
- Setups whose stop is closer than 0.2% of the entry are skipped, because costs alone would be 0.7R.
- Compare each pattern with chance: the same trade rule on random candles in the same direction and trend context, with
  the stop at the extreme of the same number of last candles.
- **A pattern counts as working** when it beats chance after costs in both halves, on at least 3 of the 4 coins.

## Test 2: do patterns improve the agent's trades?

- The planned design's 3,263 trades over 4 years (data/replay/journal-news.db, v0-e78944).
- For each trade, look for a pattern in the trade's direction, or against it, in these places:
  - the coin's 15m: the last 3 closed candles at the decision
  - the coin's 1h, 4h and 1d: the last closed candle
  - BTC's 4h and 1d: the last closed candle
- **A pattern helps** when trades with it beat trades without it in both halves, on enough trades (about 100), before any
  account test.

## Not in this first pass

Triangles, flags, pennants, wedges, rectangles, cup and handle, diamonds and the like. Their definitions vary a lot, and
the Trendline breakout already covers triangle and line breaks.

## Results (research/tools/patterns_test.py; output in data/research/patterns.txt)

### Test 1: patterns traded on their own (net R a trade after costs, 4 coins pooled)

- **Higher timeframes are better.** The typical pattern goes from about -0.40R on 5m, -0.30R on 15m and -0.20R on 1h to
  about -0.10R to +0.05R on 4h and up to +0.09R on 1d. That is mostly because costs weigh less on wider stops.
- **Nothing on 5m, 15m or 1h is profitable on its own.** Many patterns beat chance there, but chance is -0.35 to -0.47R.
- **The best on 4h and 1d are small:**
  - 1d bullish engulfing: +0.088R (259 trades, 3/4 coins, both halves)
  - 4h morning star: +0.050R (208 trades, 4/4)
  - 4h double bottom: +0.012R (1,142 trades, 4/4)
  - 4h head and shoulders: +0.050R (197 trades, 2/4)
- **Momentum patterns beat chance more than classic reversals.** These are marubozu, three soldiers/crows and three
  outside up/down.
- **Some patterns do worse than chance on every timeframe:** inverted hammer, hanging man (-0.5 to -0.7R) and the tweezers.

### Test 2: the design's 3,263 trades by the pattern at the decision

| Source | with the trade | against | none |
|---|---|---|---|
| coin 15m, last 3 candles, reversal patterns | -0.115R (188; -0.025 / -0.179) | +0.069R | +0.029R |
| **coin 1h, last candle** | **+0.099R (1,233; +0.102 / +0.096)** | +0.135R (64) | -0.004R (1,964; both halves -0.004) |
| coin 4h, last candle | -0.035R (670) | -0.025R (500) | +0.076R (2,088) |
| **coin 1d, last candle** | **+0.139R (483; +0.120 / +0.153)** | +0.022R (524) | +0.022R (2,249) |
| BTC 4h, last candle | -0.043R (609) | -0.033R (503) | +0.073R (2,143), both halves |
| BTC 1d, last candle | +0.075R (467; +0.093 / +0.063) | +0.024R | +0.032R |

- **Candidates:**
  - a candle pattern in the trade's direction on the coin's last 1h candle: +0.10R vs about 0, in both halves, about t 2.4
  - the same on the last daily candle: +0.14R vs +0.02R, both halves, about t 1.9
  - Both fit as size factors (like tier A), not as filters, which would remove 40-60% of the trades.
- **Warnings:**
  - BTC's last 4h candle being any pattern goes with worse trades (about -0.04R vs +0.07R).
  - A same-direction reversal pattern on the 15m right at the signal is bad (-0.115R).
- **Caveats:**
  - There are 6 sources × 3 groups, so some splits will look good by chance.
  - The overlap with tier A (the Trendline breakout) has not been checked.
- **Next:** an account replay with these as size factors (4 years and the TradingView replay since June), the overlap with
  tier A, and then a forward test in the shadow book.
