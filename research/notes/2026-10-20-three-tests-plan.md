# Three tests, past data only: plan written before any result (2026-10-20)

The user approved testing these three ideas, with no change to the agent. Each is one run. Nothing is tuned after seeing a result.

## Test 1: a 1h engine (Q-Trend + Klinger on 1h)

- **Data:**
  - TradingView 1h history on Market_check (10,000 bars, about 14 months) for XRP, SOL and ETH. The studies, versions and inputs are those of the AGENT charts, read with the scalp catalog template (Q-Trend, Klinger, VWAP, Zero Lag, ATP MACD). The first 300 bars are skipped for warm-up.
  - Binance 1m and 1h candles for the same period, stored in data/research/h1_engine.db.
- **Variants** (the baseline rules, only these changes):
  - **h1:** timeframes ["1h"]. Otherwise as the baseline: Q-Trend flip, Klinger and candle confirmation within 3 candles, 10-candle swing stop of at least 1.5%, limit entry at the next 1m open, target 1.5R.
  - **h1_1r:** the same with a target of 1.0R (the user's "small target").
- **Pass rule (on XRP, SOL and ETH together):**
  - at least 100 trades
  - expectancy at least +0.15R
  - profit factor at least 1.3
  - positive in both halves
  - at least 2 of the 3 coins positive
- **If it passes:** a 1h engine as a challenger in the shadow book first. It would add trades of a different horizon to the 5m/15m engine.

## Test 2: ZEC (and the other candidates) with the minimum stop = max(1.5%, scaled)

- **Scaled** = 1.5% × (the coin's 7-day median 15m range / 0.53%), as in research/notes/2026-10-19-vol-stop-plan.md. The floor of 1.5% keeps the current coins unchanged.
- **Data:** the trades the coin screen already simulated (data/research/coin_screen.db).
- **Decision rule:** the same as the coin screen:
  - at least 40 trades
  - both halves positive
  - profit factor at least 1.3
  - target hit at least 42%
  - expectancy at least +0.231R
- **If ZEC passes:** ZEC goes to the shadow book only (no demo), on the Market_check layout. That needs the user's approval.

## Test 3: late confirmation

- **Hypothesis:** trades confirmed 1–3 candles after the Q-Trend trigger do better than trades confirmed on the trigger candle itself. This was seen on the current coins' taken trades: +0.45 to +0.63R on 42 trades, against +0.21R on 212.
- **Testing on samples where it was NOT seen:**
  - (a) the current coins' skipped signals (the 1.5% minimum-stop skips), from the live journal
  - (b) the eight screen coins' baseline trades, taken and skipped, from data/research/coin_screen.db
- **Pass rule:**
  - in sample (a), late confirmations are better by at least 0.15R in both halves, with at least 25 trades per group per half
  - sample (b) points the same way
- **If it passes:** a quality flag (size tier), never a skip, since requiring a later confirmation would remove most trades.

## Results

### Test 2: minimum stop = max(1.5%, scaled)

| Coin | Trades | Won | R / trade | PF | Target hit | Halves | Verdict |
|---|---|---|---|---|---|---|---|
| **ZEC** | 131 | 50% | **+0.202** | 1.39 | 48% | +0.14 / +0.26 | **Near miss again:** every check passes except +0.231R. XRP through the same pipeline: +0.203R |
| ARB | 159 | 43% | +0.042 | 1.07 | 42% | +0.08 / +0.00 | no |
| ENA | 149 | 43% | +0.032 | 1.06 | 40% | +0.05 / +0.02 | no |
| NEAR | 126 | 41% | +0.003 | 1.00 | 40% | +0.00 / +0.00 | no |
| TAO, INJ, TIA, 1000PEPE | 128–146 | 36–40% | -0.02 to -0.14 | < 1 | 34–40% | – | no |

ZEC is the only volatile coin that, with a stricter minimum stop, trades about as well as XRP, and it does so in both halves. It does not pass the bar that was set beforehand. Adding it is the user's call: shadow book only, never the demo first.

### Test 3: late confirmation (out of sample)

| Sample | Late (1–3 candles) | Same candle | Difference by half |
|---|---|---|---|
| (a) current coins, skipped signals (1,017) | -0.301R (247) | -0.158R (770) | **-0.225 / -0.059 (late is worse)** |
| (b) eight screen coins (2,642) | -0.011R (602) | -0.093R (2,040) | +0.086 / +0.077 |

**No pass.** The two samples disagree, and in (a) late is worse. The +0.45R seen on 42 taken trades was chance.

### Test 1: the 1h engine (404 days of 1h history, XRP, SOL and ETH)

| Variant | Trades | Won | R / trade | PF | Target hit | Halves | Quarters | Verdict |
|---|---|---|---|---|---|---|---|---|
| h1 (1.5R) | 422 (1.0 a day) | 43% | +0.002 | 1.00 | 28% | +0.04 / -0.04 | +0.09 / +0.01 / -0.05 / -0.06 | **no** |
| h1_1r (1.0R) | 422 | 48% | -0.020 | 0.95 | 40% | +0.06 / -0.10 | +0.03 / +0.09 / -0.12 / -0.09 | **no** |

By coin (h1): XRP -0.01R, SOL -0.04R, ETH +0.07R. The median time in a trade is 37 hours, and part of the trades end at the 72-hour limit.

**The baseline rules have no edge on 1h charts**, with either target, over 14 months. The recent half is negative. As in 2026-10-03 (1h without Klinger), the 1h horizon is dropped.

## Summary of 2026-10-19/20

Tested on past data with rules fixed beforehand:
- liquidity pools
- stop buffers
- OI flushes
- open interest
- five fake-signal filters
- eight volatile coins
- a volatility-scaled minimum stop (twice)
- late confirmation
- a 1h engine

**Only the open interest flag passed.** It is now part of the quality tier. ZEC with a max(1.5%, scaled) minimum stop is a near miss (+0.20R, about XRP's level).

The 5m/15m baseline sits near a local optimum for these indicators. Further gains are more likely from:
1. the forward sample, to confirm the edge (100 trades) and to check the quality tiers in early November
2. new, different signal sources or strategies, rather than more filters on the same signal
