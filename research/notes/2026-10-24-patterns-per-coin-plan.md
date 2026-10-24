# 2026-10-24: tier-A factors compared, pattern counts per coin, HTF patterns per coin, other coins (plan)

Written before the results. The user approved the research. No development until the user says so.

## 1. Which tier-A factor is best, and what do several together do

- **The factors** (the design's 4-year trades, XRP/SOL/ETH):
  - a: recorded tier A (open interest; Trendline values are missing before 2026-10-18)
  - b: a candlestick pattern in the trade's direction on the coin's last 1h or 1d candle
  - c: a 4h chart breakout in the trade's direction in the last 2 4h candles
  - d: BTC moved 2%+ in the trade's direction over the last 12 h
  - skip: BTC moved 2%+ against the trade over the last 12 h
- **Shown:**
  - R with and without each factor, in both halves
  - R by how many factors agree (0, 1, 2, 3+)
  - the simple account (user's rules, A 3% / B 2%) with each factor alone, the pairs, all of them, and with or without
    the skip
  - the same on the TradingView replay since 2026-06-25

## 2. How often each pattern forms

- All 65 candlestick patterns on 5m, 15m, 1h, 4h and 1d, and the 20 chart patterns on 1h, 4h and 1d.
- For XRP, SOL, ETH and BTC over 4 years, as counts and as a count a month.
- Output: data/research/pattern_counts.csv and a summary.

## 3. HTF patterns with the new design, per coin

- **The design's trades:**
  - XRP, SOL and ETH over 4 years
  - BTC from dip15 over 3 years
- **Rules:**
  - Split per coin and per higher timeframe (1h, 4h, 1d) by the pattern on the last closed candle in the trade's
    direction (candlestick patterns), or a breakout in the last 2 candles (chart patterns).
  - R with the pattern vs without any.
  - Per individual pattern, pooled over the coins, when 30+ trades match.
- **The 5m question:** v0's 5m-signal trades (3 years, 4 coins) split the same way. Does an HTF pattern make 5m signals
  worth taking?

## 4. Other coins

- The design replayed with the agent's engine on all 13 coins of the 1.5-year journal (research/tools/replay_other.py):
  ADA, AVAX, BNB, DOGE, LINK, LTC, NEAR, SUI, ZEC, and XRP/SOL/ETH/BTC on the same window.
- Shown per coin: R a trade, the same HTF-pattern split, and factors b, c and d.

## Results, parts 1-3 (data/research/factor_compare.txt, pattern_counts.csv / pattern_counts.txt, pattern_coins.txt)

### 1. Tier-A factors (the design's 4-year trades)

| Factor | on | with | without |
|---|---|---|---|
| a OI/Trendline | 4% (2025-26 only) | +0.211R | +0.030R |
| b 1h/1d candle pattern | 46% | +0.114R (+0.109 / +0.117) | -0.028R |
| c 4h chart breakout | 4% | +0.199R (+0.095 / +0.314) | +0.030R |
| d BTC 12h move with | 10% | +0.158R (+0.134 / +0.184) | +0.025R |

- **By how many factors agree:**
  - 0: -0.068R (1,416 trades, 43%, both halves negative)
  - 1: +0.109R
  - 2: +0.145R (248)
  - 3+: +0.854R (14)
- **Account (simple, user's rules), alone:**
  - none: +728%, DD 62.7%
  - a: +807%, DD 62.7%
  - b: +1,061%, DD 68.2%
  - c: +813%, DD 62.0%
  - d: +1,009%, DD 65.0%
- **Account, combined:**
  - b+d: +1,309%
  - b+c+d: +1,372%, DD 70.0%
  - all: +1,421%, DD 68.2%
  - all + skip against BTC: +1,430%, DD 59.3%
  - the skip alone: +722%, DD 57.3% (2024-26 DD 42.1% vs 53.6%)
- **The best of each kind:**
  - strongest per trade but rare: c (and a)
  - most added return: b, but it raises the DD the most
  - best value: d (only 10% of trades, +281 points)
  - best drawdown protection: the skip
- TradingView since 06-25 points the same way on small samples.

### 2. Pattern counts

data/research/pattern_counts.csv holds every pattern x timeframe x coin.
- The counts are similar across XRP, SOL, ETH and BTC.
- 4h examples per coin over 4 years:
  - bearish engulfing 413-480
  - bullish engulfing 394-437
  - double top/bottom 248-308
  - hammer 218-268
  - morning star 44-61
  - three white soldiers and black crows almost never
- The gap patterns never form.

### 3. HTF patterns with the design, per coin

- **Pooled (XRP/SOL/ETH 4 years + BTC dip15 3 years, 3,710 trades):**
  - 1h candle with +0.059R vs none +0.002R
  - 4h candle with +0.013R vs none +0.071R (worse)
  - 1d candle with +0.056R vs none +0.036R
  - 4h chart breakout with +0.221R (170)
  - 1d chart breakout with +0.143R (339; +0.188 / +0.097)
  - 1h chart breakout with +0.055R
- **Per coin, the candle factor differs:**
  - XRP: 1h with +0.029R vs none +0.096R and 1d +0.008R vs +0.125R, so it hurts
  - SOL: 1d +0.119R vs -0.034R, both halves
  - ETH: 1h +0.144R vs -0.057R, both halves
  - BTC: 1h +0.053R vs -0.134R; 4h candle +0.108R vs -0.084R
- **Chart breakouts (4h/1d) in the trade's direction are positive on every coin:**
  - XRP: 4h +0.486R (39), 1d +0.197R
  - SOL: 4h +0.130R, 1d +0.115R
  - ETH: 4h +0.033R, 1d +0.258R
  - BTC: 4h +0.385R (22), 1d -0.073R
- **Single patterns:** the samples are small and there are many comparisons. Bearish confirmations for shorts held up
  better than bullish ones for longs:
  - good: 1h bearish engulfing +0.140R (276, both halves), 1h three outside down +0.085R, 4h bearish spinning top +0.216R
  - bad: 4h bullish engulfing -0.181R (102, both halves), 4h hammer -0.059R
- **5m signals:** an HTF pattern does not rescue them. XRP 5m with a 1h pattern: -0.175R. They stay out.

## Results, part 4: 13 coins, 2025-04 to 2026-10 (data/research/other_coins.txt, package_other.txt, revised_package.txt)

- **The new design per coin (R a trade):**
  - positive: ZEC +0.148R, XRP +0.132R, SUI +0.046R, ETH +0.030R, LINK +0.014R, ADA +0.010R
  - about zero: BNB, AVAX, DOGE, NEAR, SOL (-0.011R)
  - negative: BTC -0.030R, LTC -0.132R
  - The 9 other coins average +0.017R. In the account (one group at a time) they lose: -78%, DD 95%. The coin choice
    matters.
- **The candle factor b does not hold up:**
  - On the 9 other coins: with +0.006R vs without +0.037R.
  - On XRP/SOL/ETH in this replay: +0.037R vs +0.065R. In the account, b as tier A gave -14% (DD 79%) against +37% for
    everyone at 2%.
  - In the 4-year replay it fades: 2022-10 to 2025-04 with +0.140R vs -0.058R; 2025-04 to 2026-10 +0.071R vs +0.025R.
  - The two replays share only 902 of about 1,215 signals in the common window (indicator warm-up differs), and b flips
    between them. It is fragile.
- **c (4h chart breakout) and d (BTC 12h move with the trade):**
  - They hold on XRP/SOL/ETH in both replays and both windows: c +0.22R to +0.27R vs +0.04R; d +0.14R to +0.19R vs +0.04R.
  - They fail on the 9 other coins: c -0.052R, d +0.004R. A plausible reason is that the big caps follow BTC most (1h
    correlation ETH 0.83, SOL 0.70, XRP 0.62).
- **Skipping trades against a 2%+ BTC 12h move lowers the drawdown in every data set:**
  - 4 years: 57.3% vs 62.7%
  - 13-coin XRP/SOL/ETH: 54.4% vs 56.1%
  - TradingView: 11.1% vs 15.7%
  - other coins: 83.7% vs 94.9%
- **Revised package: tier A = a or c or d, plus the skip (b dropped):**

| | everyone 2% | a only (today) | old a+b+c+d + skip | **revised a+c+d + skip** |
|---|---|---|---|---|
| 4 years | +728%, DD 62.7% | +807%, DD 62.7% | +1,430%, DD 59.3% | **+1,089%, DD 59.7%** (2022-24 +174%, 2024-26 +335% DD 44.5%) |
| 13-coin XRP/SOL/ETH, 1.5 years | +44%, DD 56.1% | +57%, DD 57.3% | +46%, DD 66.6% | **+120%, DD 54.3%** |
| TradingView since 06-25 | +183%, DD 15.7% | +211%, DD 18.3% | +266%, DD 14.3% | **+219%, DD 12.2%** |

The revised package beats today's tiers in all three data sets, with a lower drawdown in all three. Tier A covers about 20%
of the trades.

## Trades a day with the revised package, by market regime (research/tools/trades_by_regime.py)

- **The revised package** (the design's 4-year trades, simple account at the user's rules):
  - 1.61 trades a day, 11.3 a week, 49 a month
  - +0.066R a trade; 20% of the trades at 3%
- **Trades on a day:** none on 30% of days, 1 on 25%, 2-3 on 33%, 4+ on 12%. The most in one day was 8.

| BTC daily range | days | trades a day | days without a trade | R a trade |
|---|---|---|---|---|
| quiet (< 2.0%) | 25% | 0.84 | 50% | -0.001R |
| normal (2.0-4.5%) | 50% | 1.69 | 26% | -0.024R |
| volatile (4.5-6.4%) | 15% | 2.18 | 17% | +0.091R |
| very volatile (> 6.4%) | 10% | 2.14 | 20% | +0.452R |

| Coins' volume vs their 30-day median | days | trades a day | R a trade |
|---|---|---|---|
| low (< 0.8x) | 28% | 0.77 | -0.083R |
| normal | 43% | 1.66 | +0.034R |
| high (1.25-2x) | 22% | 2.30 | +0.119R |
| very high (> 2x) | 7% | 2.28 | +0.244R |

- The money is made on volatile, high-volume days. Quiet days are flat or slightly negative.
- Last 4 months: 1.12 trades a day. BTC's median daily range was 2.5%, vs 3.1% over the 4 years.
