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

## 2026-10-18 · video_original · {"entry":{"mode":"market"},"filters":{"min_stop_pct":0.0}}
Reference only. Forward 4-18 Oct on XRP/SOL/ETH: 306 trades, -0.225R a trade, -68.8R in total, profit factor 0.70, against the baseline's +0.373R on 38 trades. The video's original rules lose money; the minimum stop distance (1.5%) and limit entries carry the edge. Retired.

## 2026-10-18 · research round (no experiment recorded; full numbers in research/notes/2026-10-18.md)
- Long and short open on the same coin at once: 18 pairs in 42 demo trades; one stop and one target in 10 of 11; net about 0R a pair. No skip/close rule beat "every signal" in all three periods (history halves + forward).
- Smaller targets for counter-trend trades lose: the win rate rises to 75-82% but each win shrinks more than the losses saved. 1.5R stays best for with-trend and counter-trend trades. The 4h trend flips between periods (+0.41R vs -0.29R): no 4h rule.
- Signals skipped by the 1.5% minimum stop lose in every stop-width bucket at every target 0.5-1.5R; min stop 1% with a 2.5R target doubles the trades at about 0R.
- Tested on the history and NOT better in all three periods: no Klinger, no candle direction, window 5 (no effect), hybrid partial exits at 0.75R/1.0R (worse in all three), pullback limit 0.25R/30 min (loses 70% of trades, negative forward), target 1.75R, 1h signals without Klinger, 5m+15m+1h. Do not propose these again against this baseline.
- Chart research 2026-10-18: continuation entries on a VWAP reclaim inside the Q-Trend trend (same risk rules) decay +0.188R -> +0.047R -> -0.162R (history halves, forward). Do not propose. Entries on the cheap side of VWAP did best (+0.60R, 28 trades): a hint only.
- Indicators 2026-10-18: SMC Pro [RFX] is not machine-readable (0 plots). LuxAlgo and Liquidity Sweep signals have no robust standalone edge on 1h over 14 months. Trendline breakout (RFX) as a same-direction confirmation within 1-4 h before the agent's trades: about +0.55R vs +0.20R. Pending the repaint test (closed-source, pivot-based).
- Repaint test 2026-10-18 (bar replay, warmed-up XRP): Trendline, LuxAlgo, Liquidity Sweep and Q-Trend never repaint; signals depend on the loaded history length. Quality sizing (3% when a Trendline breakout confirms within 2 h, else 2%) beat flat risk at the same average risk in both halves (+292% vs +233% over 3.5 months). ADX and UT Bot add nothing.
