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

## 2026-10-19 · session_08_24 · {"filters":{"session_utc":[8,24]}}
(auto) Rejected on history before any forward trade: half 1: +0.165R, below the baseline's +0.198R

## 2026-10-19 · exit_opposite_signal · {"exit":{"opposite_signal":true}}
(auto) Rejected on history before any forward trade: expectancy +0.122R is not 0.05R above the baseline's +0.254R; profit factor 1.41 below the baseline's 1.55; half 1: +0.065R, below the baseline's +0.198R; half 2: +0.179R, below the baseline's +0.310R

## 2026-10-19 · session_08_24 · {"filters":{"session_utc":[8,24]}}
The night hours (00-08 UTC) are weak only in the 2nd half of the history: cutting them helped overall but made the 1st half worse (+0.165R vs +0.198R). Like session_04_20, hour filters are regime-dependent on this history; only forward data (session_07_21, session_13_21) can settle them.

## 2026-10-19 · exit_opposite_signal · {"exit":{"opposite_signal":true}}
Closing on the opposite Q-Trend trigger of the same chart cuts more winners than it saves losers: worse in both halves (+0.065R and +0.179R) and PF 1.41. A flip on the trading chart is mostly noise inside the trade; the fixed 1.5R target and swing stop stay better, as with be_1r.

## 2026-10-19: liquidity ideas on past data (research/notes/2026-10-19-liquidity-plan.md)

- **Liquidity pools in the way of the target** (previous day or 4 h range, equal highs/lows) do not separate good trades from bad ones in both halves. The prior range lies before the target in 97% of trades.
- **Stop hunts are rare for this strategy:** only 9% of stop-outs swept back 0.5R inside within 30 minutes. Do not widen stops past liquidity pools.
- **Open interest rising more than 1% in the 4 hours before a signal marks better trades.**
  - Taken trades: +0.63R vs +0.22R.
  - Skipped signals: +0.04R vs -0.22R.
  - It holds in both halves of both samples. The effect is strongest on longs.
  - Candidate for a quality tier, after an overlap check with the Trendline tier.
- **OI flushes** (15m OI -1.5% with a 1% price move) are too rare to test. TradingView's `_OI` symbols match Binance's OI history (XRP and ETH closely, SOL loosely).

## 2026-10-19: fake signals (research/notes/2026-10-19-fake-signals-plan.md)

- Of 1,593 Q-Trend triggers on XRP, SOL and ETH, the agent took 254 (53% won, +0.25R).
  - The 1,015 confirmed signals it skipped for a stop under 1.5% won 37% (-0.19R). Those are the chart's "fake" signals.
  - The confirmation and the minimum stop already remove most fakes.
- Chop (signals in the last 48 candles), late entries (distance from the trend line), weak candle bodies, low volume and weak Klinger do not separate the taken losers from the winners in both halves. Do not propose them as filters.

## 2026-10-19: more volatile coins (research/notes/2026-10-19-coin-screen.md)

- Of ZEC, NEAR, 1000PEPE, ENA, INJ, TIA, ARB and TAO, none qualifies with the baseline rules.
  - ZEC +0.075R is the best of them, and is positive in both halves. The others are negative.
  - The current coins over the same windows: ETH +0.40R, SOL +0.32R, XRP +0.23R.
- More volatility gives more trades but less follow-through: the target is hit 34–44% vs 46–51%. On these coins the 1.5% minimum stop no longer filters the chop.
- Do not swap ETH: it is the best coin per trade.
- The screen pipeline (research/tools/coin_screen.py) reproduces the live journal: XRP +0.20R vs +0.23R.

## 2026-10-19: volatility-scaled minimum stop (research/notes/2026-10-19-vol-stop-plan.md)

- A minimum stop of 1.5% × (the coin's 7-day median 15m range / 0.53%):
  - ZEC rises from +0.075R to +0.211R (both halves positive, PF 1.41, target 49%), a near miss against the +0.231R bar.
  - The other volatile coins end around 0 or below.
- On XRP, SOL and ETH the scaled minimum drops to 0.7–1.0% and the edge disappears. Never go below the 1.5% floor; max(1.5%, scaled) is the untested form for volatile coins.
- **Entry timing is not late.**
  - Entries come at the 1m open after the signal candle closes, at practically the signal's close price.
  - 83% of trades confirm on the trigger candle itself. The 42 that confirmed 1–3 candles later did better (+0.45 to +0.63R): a small sample and a new hypothesis.
  - Winners take a median of 13.8 hours and first go about 0.34R against: the price of the 1.5% minimum stop.

## 2026-10-20: ZEC with max(1.5%, scaled) stop; late confirmation (research/notes/2026-10-20-three-tests-plan.md)

- With a minimum stop of max(1.5%, volatility-scaled), ZEC makes +0.202R (131 trades, PF 1.39, both halves positive), about XRP's level, but it misses the +0.231R bar. The other volatile coins stay around 0 or below.
- A confirmation 1–3 candles after the trigger is not better out of sample: it is worse on the current coins' skipped signals. Do not propose it.

## 2026-10-20: 1h engine (research/notes/2026-10-20-three-tests-plan.md)

- The baseline rules on 1h charts (Q-Trend + Klinger, 404 days, 422 trades) make +0.002R with a 1.5R target and -0.020R with 1.0R. The recent half is negative on both. Do not propose a 1h engine with these rules.

## 2026-10-20: high win rate, drawdown sizing, VWAP mean reversion (research/notes/2026-10-20-mr-and-drawdown-plan.md)

- **Smaller targets raise the win rate and cut the return.** With a 0.25R target, 85% win and +22% over 116 days. With 1.5R, 53% win and +237%. The drawdown is about the same. Do not chase win rate.
- **Halving the risk while 8% or more below the peak** cuts the drawdown by 14–25% but the return by 10–22%. No.
- **VWAP #2 band mean reversion** (close back inside the band, target the VWAP, 2-candle stop): 2,510 trades on 11 coins, 35% won, -0.15R. Crypto band breaks continue rather than revert at 5m/15m.

## 2026-10-20: Supertrend, WaveTrend, Squeeze, and two YouTube Supertrend strategies (research/notes/2026-10-20-supertrend-plan.md)

- **Video 2's strategy** (Supertrend 12/3 + DEMA 200, exit on the opposite flip) on XRP, SOL, ETH, DOGE and LTC 15m: 818 trades, 25–32% won, about 0R. Its claim of 60% won and +130% does not hold. A Supertrend stop can sit on the entry (one trade was -1,540R): never trade without a minimum stop.
- **Supertrend exits** (trail on the flip, or a runner after 1.5R) are 0.12–0.17R worse than the fixed 1.5R target on our trades.
- **Supertrend direction adds nothing:** 95% of our trades already agree with it. The 15m Supertrend, a fresh flip and the DEMA 200 side gave no robust edge.
- **Squeeze released in the trade's direction:** taken trades +0.40R vs +0.21R in both halves, and additive to tier A (both flags +0.66R). Not confirmed on the skipped signals. Record it forward before any size change.
- **WaveTrend at oversold before a long** (or overbought before a short) is mildly worse in both samples.

## 2026-10-20: signal version 6 replayed on the past charts (research/notes/2026-10-20-v6-backtest.md)

- The whole agent on the v6 TradingView history of XRP, SOL and ETH (2026-07-13 to 10-18): 188 trades, 54% won, +0.285R, PF 1.63, positive in both halves and on every coin.
  - Quality A: 66% won, +0.58R. Quality B: +0.13R.
- The demo account with today's rules: $150 to $503 (+235%, max DD 16%), against +161% (DD 20%) with a flat 2%. These are in-sample numbers for the tiers.
