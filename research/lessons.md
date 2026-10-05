# Lessons

One entry per experiment decision, newest last. Written by the Experiment Manager (marked "(auto)") and by Claude's research. Read this before proposing anything.

## Before the learning loop (research of 2026-10-03 and 2026-10-04)

- **A minimum stop distance is what makes the strategy work.** Skipping setups whose swing stop is closer than 1.5% turned −0.159R into +0.116R; fees and slippage eat tight stops. Lowering it destroys the edge: 1% gives about +0.03R, and no minimum gives −0.175R.
- **Limit entries beat market entries.** The maker fee is cheaper and there is no slippage. Only fills where the first minute trades through count.
- **Coins matter more than tuning.** XRP, SOL and ETH stayed positive in both halves.
  - LINK, ADA and SUI chop: only 35–37% of their trades reach 1.5R, against 45–48% on XRP and SOL, and 43–46% of their stopped trades had first reached +0.5R.
  - BTC, BNB, DOGE and AVAX were negative.
- **Holding until the opposite 15m signal was worse than the fixed 1.5R target.**
- **Pullback limit entries** (waiting for a better price) filled too rarely to help.
- **Promising, being tested forward:** 5m signals only with the 15m trend (`trend15`) gave +0.276R against +0.237R, with fewer trades, and was the steadiest across quarters. Only 15m signals (`tf_15m`) gave +0.257R.

## 2026-10-04 · min_stop_1pct · {"filters":{"min_stop_pct":1.0}}
History on XRP/SOL/ETH: +0.072R a trade over 429 trades against the baseline's +0.237R, worse in both halves (+0.060R and +0.082R against +0.253R and +0.221R). Stops between 1% and 1.5% lose to costs. Retired before the forward test.

## 2026-10-04 · min_stop_2pct · {"filters":{"min_stop_pct":2.0}}
History: +0.142R over 100 trades against +0.237R, worse overall and in the first half (+0.012R against +0.253R). Half the trades and no better: 1.5% stays the minimum. Retired before the forward test.

## 2026-10-04 · confirm_0 · {"confirmation":{"window":0}}
History: +0.204R over 175 trades against +0.237R, worse in both halves (+0.201R and +0.207R). Letting the confirmation come up to 3 candles after the trigger adds good trades. Retired before the forward test.

## 2026-10-04 · stop_1h_swing · {"stop":{"anchor":"1h"}}
History: +0.183R over 209 trades against +0.237R, worse in both halves (+0.209R and +0.158R). The stop beyond the 1h swing wins more often (56% against 52%) but earns less a trade. Retired before the forward test.

## 2026-10-04 · trigger_strong · {"trigger":{"long":"strong_buy","short":"strong_sell"}}
History: +0.219R over only 83 trades against +0.237R; +0.368R in the first half but +0.041R in the second. Unstable, and too few trades. Retired before the forward test.

## 2026-10-04 · be_1r · {"exit":{"breakeven_r":1.0}}
(auto) Rejected on history before any forward trade: expectancy +0.189R is not 0.05R above the baseline's +0.237R; profit factor 1.46 below the baseline's 1.50; half 1: +0.208R, below the baseline's +0.253R; half 2: +0.169R, below the baseline's +0.221R
Break-even at +1R gives back more than it saves: many winners dip back to the entry after +1R and still reach 1.5R.

## 2026-10-04 · tp_125 · {"exit":{"take_profit_r":1.25}}
(auto) Rejected on history before any forward trade: expectancy +0.188R is not 0.05R above the baseline's +0.237R; profit factor 1.41 below the baseline's 1.50; half 1: +0.206R, below the baseline's +0.253R; half 2: +0.170R, below the baseline's +0.221R
A 1.25R target wins only slightly more often and gives up 0.25R on every winner; 1.5R stays better.

## 2026-10-04 · tp_2 · {"exit":{"take_profit_r":2.0}}
(auto) Rejected on history before any forward trade: expectancy +0.135R is not 0.05R above the baseline's +0.237R; profit factor 1.24 below the baseline's 1.50; max drawdown 14.0R vs 11.1R; half 1: +0.149R, below the baseline's +0.253R; half 2: +0.120R, below the baseline's +0.221R
Most moves do not reach 2R before the stop: 1.5R stays the better target.

## 2026-10-04 · session_04_20 · {"filters":{"session_utc":[4,20]}}
(auto) Rejected on history before any forward trade: expectancy +0.268R is not 0.05R above the baseline's +0.237R; half 1: +0.142R, below the baseline's +0.253R
The late hours are weak only in the second half of the history; cutting them hurts the first half. Hour filters look regime-dependent, so the running session challengers must prove themselves forward.

## 2026-10-04 · lookback_15 · {"stop":{"lookback":15}}
(auto) Rejected on history before any forward trade: expectancy +0.076R is not 0.05R above the baseline's +0.237R; profit factor 1.14 below the baseline's 1.50; max drawdown 19.2R vs 11.1R; half 1: +0.044R, below the baseline's +0.253R; half 2: +0.108R, below the baseline's +0.221R
A 15-candle stop is wider, so many more setups pass the 1.5% minimum, and those extra setups lose. The 10-candle swing and the 1.5% minimum work as a pair.
