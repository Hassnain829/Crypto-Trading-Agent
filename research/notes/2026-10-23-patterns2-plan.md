# 2026-10-23 (second pass): are the pattern findings real, do they pay in the account, and the remaining patterns

Written before the results. The user approved all three parts.

## The candidate under test (fixed now, not changed after looking)

**Pattern confirmation:** any of the 26 candlestick patterns of the first pass, in the trade's direction, on the coin's
last closed 1h candle OR its last closed 1d candle at the decision (the 15m signal candle's close).

## 1. Luck or real?

- **Rotation test for the 12 looks** of the first pass (6 sources × 2 pattern groups):
  - Rotate all flags together through the time-ordered trades by a random offset (at least 50 trades), 2,000 times.
  - Each time, take the largest "with minus none" gap of the 12.
  - p = the share of rotations whose largest gap reaches the observed 1h and 1d gaps.
- **Replication on trades the first pass never saw** (Backtest 1, data/replay/journal-long-board.db, 2023-10 to 2026-10):
  - dip15 on BTC (a fourth coin)
  - v0 (5m and 15m signals) and trend15 (5m signals with the 15m trend) on all four coins
  - It replicates when "with" beats "none" in both halves.
- **The agent's TradingView data:** the design's trades replayed since 2026-06-25 (data/replay/journal-gate-2026-06-25.db).
- **Overlap with tier A:** R in the four cells (A / not A × pattern / no pattern).
  - Tier A in these replays is open interest only. TradingView Trendline values exist only from 2026-10-18.

## 2. The demo account

The design (15m + dip 60, no news filter) at the user's rules: $150, max 5 open, 2 a coin, opposite skipped, the first
position a coin always, 12% budget.

| Scheme | 3% risk (A) | 2% risk (B) |
|---|---|---|
| S0 now | tier A as recorded | the rest |
| S1 | tier A or the pattern confirmation | the rest |
| S2 | the pattern confirmation only | the rest |
| S3 | nobody | all |
| S4 | as S1, except when BTC's last 4h candle is a pattern or a same-direction reversal pattern sits on the 15m at the signal | the rest |
| flat | everyone at S1's average risk | |

- The key test: **S1 against flat at the same average risk.**
- **How much bigger tier A should be** (the user's question): S1 with tier A at 2.5%, 3%, 3.5%, 4% and 5% (B stays 2%,
  the 12% budget stays). Return and drawdown for each, in both halves.
- Run on 4 years (Python indicators, data/replay/journal-news.db, v0-e78944) and on the TradingView replay since 06-25
  (design-e78944).
- It pays when S1 beats flat in return and in drawdown, in both halves of the 4 years, and on the TradingView replay.

## 3. The remaining patterns

Same rules as the first pass: stop beyond the pattern, 1.5R, 24 candles, costs, compared with chance.

- **Candlestick:**
  - bullish/bearish belt hold, spinning top, harami cross, separating lines, counterattack
  - morning/evening doji star, bullish/bearish abandoned baby, bullish/bearish tri-star
  - long-legged doji and high wave (as reversals after a trend)
  - on-neck, in-neck, thrusting, matching low, matching high, homing pigeon, descending hawk
  - advance block, deliberation, upside gap two crows, unique three river, stick sandwich, identical three crows
  - bullish/bearish three-line strike, rising/falling three methods, ladder bottom
- **Chart (1h, 4h, 1d, from pivots confirmed 3 candles later):**
  - triple top/bottom
  - rectangle breakout up/down
  - ascending, descending and symmetrical triangles
  - rising and falling wedges
  - bull and bear flags (a pole of at least 3 ATR in at most 8 candles, then 4-20 candles holding at least half of it)
- Also as context for the agent's trades: a chart-pattern breakout in the trade's direction in the last 8 candles of the
  coin's 1h or 4h.
- **Not testable, because they need price gaps that a 24/7 market almost never has:** mat hold, breakaway, tasuki gap,
  concealing baby swallow, island reversal. Rounding tops/bottoms, cup and handle, diamonds and broadening formations are
  too loosely defined to code without tuning, so they wait.

## Results (research/tools/patterns_account.py and patterns_more.py; data/research/patterns_account.txt, patterns_more.txt)

### 1. Luck or real

- **Rotation test over the 12 looks.** A gap this big shows up by luck in 32% of rotations for coin 1h (+0.103R) and 23%
  for coin 1d (+0.118R). On the first sample alone, that is not proof.
- **Replication on trades the first pass never saw.** "With pattern" (last 1h OR 1d candle) beat "without" in both halves
  every time:

| Sample | with | without |
|---|---|---|
| dip15 on BTC, 3 years | +0.091R (222; +0.043 / +0.141) | -0.092R (225; +0.020 / -0.199) |
| v0 5m+15m, 4 coins | +0.015R (2,736; +0.031 / -0.001) | -0.014R (3,820; -0.020 / -0.007) |
| trend15, 4 coins | +0.070R (1,896; +0.083 / +0.057) | +0.005R (2,613; -0.019 / +0.029) |

- On the TradingView replay since 06-25 (184 trades): +0.323R vs +0.252R, mixed between halves.
- **Verdict: probably real, but smaller than the first gap:** about +0.03R to +0.18R depending on the strategy.

### Overlap with tier A (in these replays tier A is open interest only)

- 4 years:
  - A + pattern: +0.234R (68)
  - A alone: +0.188R (69)
  - pattern alone: +0.108R (1,449)
  - neither: -0.037R (1,677)
- The overlap is small, and the pattern adds inside and outside tier A.

### 2. Demo account (design, user's rules, $150)

| Scheme | 4 years | 2022-24 | 2024-26 | TradingView since 06-25 |
|---|---|---|---|---|
| S0 now | +773%, DD 62.7%, risk 2.04% | +178% (62.7%) | +215% (53.4%) | +210% (18.3%) |
| **S1 A or pattern, 3%** | **+1,083%, DD 67.5%, risk 2.48%** | +287% (67.5%) | +209% (66.4%) | **+278% (17.8%)** |
| S2 pattern only | +1,013%, DD 68.6% | +287% (67.5%) | +190% (68.5%) | +250% (17.0%) |
| S3 all 2% | +695%, DD 62.7% | +178% | +187% | +182% (15.7%) |
| S4 S1 minus cautions | +1,493%, DD 65.1%, risk 2.29% | +317% | +284% | +226% (20.0%) |
| flat at 2.48% | +848%, DD 71.5% | +224% (71.5%) | +195% (62.2%) | +260% (18.8%) |

- **S1 against flat at the same average risk:**
  - better in return and drawdown over 4 years, in 2022-24 and on TradingView
  - in 2024-26 the return is better but the DD is worse (66.4% vs 62.2%)
  - 3 of 4 checks pass
- **S4's cautions help on 4 years but hurt on TradingView,** so they are not reliable.

**How big should tier A be (S1, B 2%):**

| tier A | 4 years | TradingView |
|---|---|---|
| 2.5% | +1,033%, DD 65.0% | +219%, DD 17.3% |
| 3.0% | +1,083%, DD 67.5% | +278%, DD 17.8% |
| 3.5% | +1,554%, DD 70.4% | +344%, DD 18.0% |
| 4.0% | +1,820%, DD 73.9% | +405%, DD 18.2% |
| 5.0% | +2,361%, DD 76.3% | +480%, DD 22.3% |

### 3. The remaining patterns

- **On their own, nothing is profitable on 5m, 15m or 1h after costs.**
  - Best candlesticks against chance: the belt holds (1h -0.10 to -0.14R, 4h -0.04 to -0.07R, 1d bullish +0.095R on 97)
    and identical three crows (1h -0.041R; 1d +0.152R on 103, 3/4 coins).
  - Spinning tops, long-legged doji, harami cross, stick sandwich, tri-stars and both three-line strikes are worse than
    chance.
  - The gap patterns never form in 24/7 crypto: counterattack, abandoned baby, upside gap two crows, unique three river,
    and nearly so on-neck, in-neck and thrusting.
- **Chart patterns are about break-even on 1h and 4h:**
  - 1h triple top +0.016R (1,240 trades, 4/4 coins)
  - 1h rectangle break down +0.058R (214)
  - 4h ascending triangle break down +0.209R (143, 3/4). That is one standout among about 50 tests, so probably luck.
  - 4h bull flag +0.050R (216)
  - 1d samples are too small.
- **As context for the design's trades:**
  - the remaining candlesticks on the last 1h candle: with +0.072R (791) vs none +0.031R, both halves. On the 1d: no help.
  - a chart breakout in the last 8 candles of 1h/4h, in either direction, beats none: 4h against +0.132R and with +0.057R
    vs none -0.033R. The direction does not matter, the market being active does. This matches the earlier findings on
    BTC's big days.
