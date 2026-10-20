# Supertrend, WaveTrend, Squeeze Momentum, and the user's two Supertrend videos: plan written before any result (2026-10-20)

Past data only; no change to the agent. The user asked that the test studies stay on Market_check afterwards (no restore to NEAR).

## Data

TradingView history on Market_check (qteGoFhV), 10,000 bars, for these studies:
- **Supertrend** (built-in): ATR 12, factor 3, as in video 2; video 1 uses factor 2.5–3.
- **DEMA 200** (built-in).
- **WaveTrend [LazyBear]** (PUB;1): defaults 10/21, levels ±53/±60.
- **Squeeze Momentum [LazyBear]** (PUB;175): defaults.

Coins and timeframes:
- XRP, SOL and ETH on 5m and 15m
- DOGE and LTC on 15m: the coins video 2 tested

Outcomes:
- for our trades: the shadow simulator's results in the live journal
- for the stand-alone strategies: the project's simulator on Binance 1m candles, with the same fees and slippage

## Test S1: quality flags on the agent's trades (the OI method)

Each flag is read at the confirmation candle's close, on the trade's own chart:

| Flag | Long (the short is the mirror image) |
|---|---|
| ST_with | Supertrend is in an uptrend (video 1's directional bias) |
| ST15_with (5m trades only) | the 15m Supertrend is in an uptrend (video 1's higher-timeframe bias) |
| WT_extreme | WaveTrend wt1 ≤ -53 on one of the last 6 candles (oversold before a long) |
| SQZ_fire | the squeeze released (squeeze on → off) within the last 6 candles, and the momentum value is > 0 |

**Samples:** the taken trades (primary) and the skipped signals (replication), on XRP, SOL and ETH.

**Pass rule:**
- on the taken trades, a difference of at least 0.15R in both halves, with at least 25 trades per group per half, or
- "promising": the taken trades miss only the trade count while the skipped signals pass fully, in the same direction.

A passing flag becomes a size tier (never a skip).

## Test S2: video 2 as a stand-alone strategy (15m)

- **Long entry:** at a 15m close where Supertrend flips to an uptrend and the close is above the DEMA 200. Also, following the video's tip, at a close that crosses above the DEMA while Supertrend is already up.
- **Fill:** at the next 1m open, as a market order (taker fee plus slippage).
- **Stop:** the Supertrend line at the entry candle.
- **Exit:** at the next 1m open after a 15m close where Supertrend flips against the trade. No fixed target, as the video says.
- **Shorts:** the mirror image. One position at a time per coin.

**Pass rule:**
- expectancy at least +0.15R
- profit factor at least 1.3
- positive in both halves
- positive on XRP, SOL and ETH together

DOGE and LTC are reported to check the video's claim: 60% won and +130% over 100 trades.

## Test S3: video 1's Supertrend trailing exit on the agent's trades

- On the baseline's taken trades, the 1.5R target is replaced: the trade is held until its chart's Supertrend flips against it (a close-based exit at the next 1m open). The initial stop stays, and so does the 72-hour limit.
- If Supertrend is against the trade at entry, the exit waits until it first turns with the trade and then flips against it.

**Pass rule:** expectancy at least 0.10R better than the same trades with the 1.5R target, in both halves.

The band-touch entries with key levels and candle patterns in video 1 are discretionary, so they cannot be tested mechanically. The liquidity tests of 2026-10-19 covered key levels.

## Additions from my own reasoning (written before any result; the user asked for more than the videos)

So far the flags that worked (the Trendline breakout, rising OI) both mark the start of a fresh move with new participation. Following that idea:

- **S1 extra flags:**
  - **ST_fresh:** Supertrend flipped in the trade's direction within the last 6 candles. Two independent trend detectors then agree at the start of a move.
  - **DEMA_with:** the confirmation close is on the trade's side of the DEMA 200 (video 2's filter, used as a flag on our trades).

  Same pass rule as the other S1 flags.
- **S3b (runner):** on our taken trades, half is closed at the 1.5R target. The other half runs, with a break-even stop after the partial, until Supertrend flips against the trade. It passes if the expectancy is at least 0.10R better than the 1.5R target in both halves.
- **S4: Supertrend band touch, my mechanical version of video 1's main idea.**
  - **Long:** Supertrend is up, the candle's low comes within 0.2% of the Supertrend line (or below it), and it closes above the line as a bullish candle.
  - **Stop:** the lowest low of the last 10 candles; skipped when closer than 1.5% (the lesson of this project: tight stops lose).
  - **Exit:** target 1.5R, at most 72 h.
  - Limit entry at the next 1m open (the agent's fill rule), one position per coin and timeframe. Shorts are the mirror image.
  - Run on XRP, SOL and ETH on 5m and 15m, and on DOGE and LTC on 15m.
  - Pass rule: the same as S2.

## Results (2026-10-20, one run)

**Data check.** Squeeze state code 5 means squeeze on: its candles are narrower (median range 0.247% vs 0.272%), and it lasts 20 bars on average against 12 for code 6.

### S1: flags on our trades (taken 192, skipped 748; flag minus other, half 1 / half 2)

| Flag | Taken | Skipped | Verdict |
|---|---|---|---|
| ST_with | 183 of 192 trades are "with" (Q-Trend and Supertrend flip together); -0.16 / -1.26 on 9 "against" trades | +0.02 / +0.28 | no information |
| ST15_with (5m) | +0.81 / -0.41 | +0.13 / +0.12 | no |
| ST_fresh | -0.01 / -0.38 | +0.03 / +0.09 | no |
| WT_extreme | **-0.14 / -0.65** (flagged trades -0.08R vs +0.36R, n 26) | -0.20 / -0.08 | no (consistently worse, but below the thresholds) |
| **SQZ_fire** | **+0.22 / +0.15** (flagged +0.396R, 58% won, n 92, vs +0.211R, n 100) | +0.07 / -0.12 | **passes the primary rule on the taken trades; NOT replicated on the skipped signals** |
| DEMA_with | -0.43 / -0.44 (with the DEMA was worse) | +0.03 / +0.14 | no |

SQZ_fire overlaps little with tier A (Trendline or OI), on the taken trades:

| | Squeeze fired | Not fired |
|---|---|---|
| Tier A | **+0.66R (68% won, n 31)** | +0.50R (n 32) |
| Tier B | +0.26R (n 61) | +0.08R (47% won, n 68) |

### S2: video 2 stand-alone (15m, Supertrend 12/3 + DEMA 200, exit on the opposite flip)

| Coin | Trades | Won | R / trade |
|---|---|---|---|
| XRP | 153 | 31% | +0.01 |
| SOL | 162 | 31% | -0.04 |
| ETH | 174 | 26% | -0.17 |
| DOGE | 168 | 25% | -0.03 |
| LTC | 161 | 32% | ~0.00 |

LTC's raw -9.5R comes from one trade whose Supertrend line equalled the entry (-1,540R). Without stops under 0.3%, LTC is +0.003R.

**No pass. The video's claim (60% won, +130%) is not reproduced:** 25–32% won and about 0R over 818 trades.

### S3: Supertrend exits on our taken trades (192, re-simulated)

| Exit | R / trade | Halves |
|---|---|---|
| 1.5R target | **+0.300** (55% won) | +0.38 / +0.22 |
| S3a: exit on the flip | +0.151 | +0.22 / +0.09 |
| S3b: half at 1.5R + runner | +0.156 | +0.21 / +0.10 |

**No pass.** Both are 0.12–0.17R worse; the fixed 1.5R target stays.

### S4: Supertrend band touch (stop ≥ 1.5%, 1.5R target)

51 trades in all (touches with wide swings are rare), +0.10R, halves -0.49 / +0.51. **No pass.**

## Conclusion

- The squeeze release in the trade's direction (SQZ_fire) is the only candidate. It is as strong as OI on the taken trades and adds to tier A, but the skipped signals do not confirm it, so the evidence is weaker than for OI.
- **Next:** record it on every trade first (it needs the Squeeze study on the AGENT charts, which is a catalog change), then decide in early November with forward data.
- WaveTrend oversold/overbought before a trade is consistently mildly negative. Not adopted.
- Market_check keeps the four test studies (the user's wish), on LTC 15m.

## Applied on 2026-10-20 (the user's decision) and the sizing test

- **Squeeze Momentum [LazyBear] replaced VWAP** on the AGENT 5m/15m charts at 00:15 UTC, signal version 6. Every trade now records `sqz_fire` and `sqz_momentum`. The size is unchanged.
- filter_vwap was retired, and `filters.vwap` left the research knobs.

**Sizing test, past data only** (192 taken trades on XRP, SOL and ETH with every flag known; $150, compounding, one trade at a time):

| Scheme | Final | Return | Max DD | Average risk | Halves |
|---|---|---|---|---|---|
| flat 2% | $447 | +198% | 17.5% | 2.00% | +101% / +48% |
| **current:** A (Trendline or OI) 3%, B 2% | $626 | +317% | 19.2% | 2.33% | +149% / +67% |
| A including squeeze 3%, B 2% | $719 | +379% | 21.6% | 2.65% | +166% / +80% |
| by flag count, 1.5 / 2.5 / 3.5% | $683 | +356% | 20.7% | 2.31% | +160% / +75% |

- The flag-count scheme takes the same average risk as the current tiers and returns more in both halves.
- It is in-sample, and the squeeze evidence lacks replication. Decide after the forward check.
