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

## 2026-10-20 · stop_floor_1_5pct · {"stop":{"min_pct":1.5}}
(auto) Rejected on history before any forward trade: expectancy -0.016R is not 0.05R above the baseline's +0.254R; profit factor 0.97 below the baseline's 1.55; max drawdown 66.1R vs 11.1R; half 1: -0.076R, below the baseline's +0.198R; half 2: +0.034R, below the baseline's +0.310R

## 2026-10-20 · limit_rest_5min · {"entry":{"limit_minutes":5}}
(auto) Rejected on history before any forward trade: expectancy +0.229R is not 0.05R above the baseline's +0.254R; profit factor 1.48 below the baseline's 1.55; half 1: +0.170R, below the baseline's +0.198R; half 2: +0.288R, below the baseline's +0.310R

## 2026-10-20 · stop_floor_1_5pct · {"stop":{"min_pct":1.5}}
Widening tight swing stops to 1.5% instead of skipping them adds about 920 trades that lose (-0.016R overall, -0.076R in half 1, max DD 66.1R vs 11.1R). The 1.5% minimum does not work by keeping costs low per R: it removes bad entries. A tight swing means a choppy, low-range setup, and a wider stop does not fix it. Keep skipping them.

## 2026-10-20 · limit_rest_5min · {"entry":{"limit_minutes":5}}
A limit order resting 5 minutes fills 10 more trades, and they lose: +0.229R vs +0.254R, worse in both halves. If the price only comes back to the limit after the first minute, the move has already stalled (adverse selection). Fill in the first minute or skip, as now; market_entry's extra fills are not worth chasing either.

## 2026-10-20: 5% risk, a 20% open-risk budget, and long and short on one coin (research/notes/2026-10-20-risk-and-opposite.md)

- **Flat 5% a trade is too much for clustered signals.** Past: +616% but a 36% max drawdown. The bootstrap median drawdown is 46%, with a 37% chance of more than 50%. 3–4 signals come in the same move, so 5% a trade is 15–20% on one move.
- **Raising only the open-risk budget to 20% (A 3% / B 2%)** is the cleanest gain: past +294% vs +235% at the same drawdown. Forward it equals what the demo did before the 12% budget (+39% vs +23%).
- **A 5% / B 3% with a 20% budget** is the middle way: past +544%, max DD 26%.
- **Long and short on one coin:** the newer signal usually wins (37 to 23 past, 13 to 2 forward). The older position after an opposite signal loses: older B -0.47R past and -0.65R forward; older A -0.06R.
  - Half-size rules for counter trades are not better.
  - Closing the older **B** position when the opposite signal enters is better in both halves of both samples (+0.323R vs +0.285R past, +0.520R vs +0.372R forward) with a smaller drawdown.
  - The A/B split was found on the same data, so this is a shadow-challenger candidate only.

## 2026-10-20: linking the 5m and 15m signals; weak B trades (research/notes/2026-10-20-coordination-plan.md)

- **Letting the 15m trend decide the 5m signals loses:** past +45.4R vs +53.5R, forward +9.3R vs +16.4R, and not replicated. 5m pullback signals against the 15m pay.
- **One direction per coin (newest wins)** fails past half 1 and the replication sample.
- **Closing the older B position on an opposite signal** is better in both past and both forward halves (+335% vs +236% past, +62% vs +24% forward at today's rules). It is slightly worse on the skipped-signal sample, so it is a shadow-challenger candidate only.
- **Do not skip B trades.** Only A: +153% vs +236%. B trades without a later opposite signal make about +0.35R. The weak B group at entry is B without a squeeze release (about +0.05R on 66 trades); forward check from 2026-10-20.

## 2026-10-20: one decision per coin from both charts (research/notes/2026-10-20-one-position-plan.md)

- **Duplicate signals are weak everywhere.** A second signal in the same direction while the coin already has a position makes +0.06R past, +0.01R forward, and -0.24R on the replication sample.
  - Skipping them (D1) keeps the money: +235% vs +236% past, +39% vs +24% forward. It cuts the drawdown from 10.0R to 5.8R.
- **"One position per coin, the better signal wins"** (score: A = 2, squeeze = 1; an opposite signal replaces the open position unless the open one scores higher):
  - +308% vs +236% past and +48% vs +24% forward, with half the drawdown and no long-and-short double stops.
  - It is in-sample for the score, and slightly worse on the replication sample.
- **One position per coin with "the first wins"** (`max_positions_per_coin = 1`) is the worst: +171%.

## 2026-10-20: today's ideas on the 51 real demo signals (research/notes/2026-10-20-demo-ideas.md)

- With the tiers filled in from the v6 charts:
  - A +0.52R vs B +0.24R.
  - Squeeze fired +0.54R vs +0.17R.
  - B without squeeze -0.02R.
  - Duplicates -0.02R.
  - Counter signals +0.57R.
- One position per coin with the newer or better signal winning: +53% vs +29% on the demo at today's rules, DD 7.2% vs 10.6%, no double stops.
  - Closing the older B: +47%. No duplicates: +45%.
- 15m decides, only-A and first-wins lose again.
- 51 trades over 15 days: no rule beats "now" in more than 84% of the bootstrap samples. That is evidence, not proof.

## 2026-10-20: the current strategy and every idea on 1.5 and 4 years (research/notes/2026-10-20-long-test-plan.md)

Python copies of Q-Trend, Klinger and Squeeze ran on Binance candles. On the v6 window they gave +0.340R against TradingView's +0.285R.

- **The baseline has almost no long-run edge.**
  - XRP/SOL/ETH, 4 years: 7,193 trades, +0.008R. The demo at today's rules goes $150 to $63, with a 92% max drawdown.
  - 1.5 years: +0.015R (gross +0.047R).
  - The years swing from +104% to -91%. The forward +0.37R is a good regime.
- **5m signals lose in every year. 15m signals make +0.035R.**
- **15m decides (5m only with the 15m Q-Trend, the trend15 challenger)** is the only idea better in every third of 4 years: +0.039R, +719% vs -58%. It also helps on 1.5 years and on the check coins. The drawdown is still 79% at 2–3% risk, and 48% at 1%.
- **The ideas from the 98-day and demo tests fail on 4 years:** P3, no duplicates, close-the-older, one per coin. Bigger risk is ruinous.
- **The session challengers that lead forward (+0.80R) are about 0R on 4 years.** A 100-day history screen cannot catch regime luck; long data must screen proposals.

## 2026-10-21: one decision per coin, 4 years (research/notes/2026-10-21-mtf-plan.md)

- **15m only + one position per coin (C6) is the only design positive in every year** on XRP/SOL/ETH:
  - +0.061R a trade.
  - +519% vs -58% over 4 years at today's risk, max DD 59% vs 92%.
  - Out-of-sample (2024-10 to 2026-10): +232% vs -88%, DD 39%.
  - Long and short are never open together.
  - It helps on the check coins too; on BTC it loses less money but more per trade.
- **5m entries with an exit on the 15m flip (the user's design) fail.** The flip exit cuts winners.
- **1h/4h Q-Trend agreement filters fail.**
- **The squeeze filter on C1** has the lowest drawdown (49%) but fails in-sample. Watch it forward.

## 2026-10-21: a second same-direction position per coin (research/notes/2026-10-21-addon-test.md)

- **A 15m add-on with its own 1.5R** makes more over 4 years (+617% vs +519%) but less in the last 2 years (+160% vs +232%). It has a higher drawdown (52% vs 39% out-of-sample), 27 double stops vs 1, and it is worse on BTC and the check coins.
- **A smaller (1.0R) or shared target for the add-on is worse.**
- **5m add-ons lose** (out-of-sample -29%).
- One position per coin on 15m (C6) stays the best.

## 2026-10-21: other ways to trade the same coins (research/notes/2026-10-21-outside-plan.md)

- **Daily trend following, long only (Donchian 20/10, 2×ATR stop), is the most robust edge found.**
  - XRP/SOL/ETH/BTC over 6 years: +1.71R a trade, $150 to $2,034 (+1,256%) at 2% risk, max DD 30%.
  - Both halves positive, every coin positive.
  - About 22 trades a year; costs are tiny per R.
- **Shorts lose in every trend system tested** (daily, SMA100, 4h).
- **Funding carry earns 0–4% a year** (optimistic). Not worth it.
- **v6 with one trade per coin** (5m and 15m, first wins) is still -57% over 4 years. The 5m first signals block the 15m ones. C6 (15m only + one per coin) is the intraday fix.
- **Half C6 + half daily trend:** +340% over 4 years with DD 44%, vs C6 +519% / DD 59% and trend +161% / DD 26%.
- **One-position variants (2026-10-21):**
  - An opposite 15m signal that only closes the position (V2): fewer stops (37% vs 52%) but +229% vs +519%.
  - Reversing on it (V3) fails: +69%, out-of-sample -17%.
  - The squeeze filter on C6 (V1): +186%.
  - C6 stays the best.

## 2026-10-21: the 5m times the 15m entry (research/notes/2026-10-21-entry-timing-plan.md)

- **Waiting for the first 5m candle that closes against the trade** (within 1 h, else enter at the 1-hour mark), entering at the next 5m open and keeping the 15m target price (E3), is better in both halves:
  - C6: +737% vs +519%, 2024-26 +331% vs +232%.
  - A1: +1,307% vs +617%.
  - It is not worse on BTC or the check coins per trade. The gain per trade is small.
- **Limit dips 0.25R/0.5R miss 40–73% of the trades; Klinger timing fails out-of-sample.**

## 2026-10-21: the second entry on a 5m dip; drawdown levers (research/notes/2026-10-21-second-entry-and-dd.md)

- **The first position from 15m and the second from a later 15m signal entered on a 5m dip (F1):** +793% over 4 years.
  - Both entries on the dip (A1+E3) is better: +1,307%.
  - A 5m-signal add-on (F3) and averaging down at a 0.5R dip (F4) fail.
- **At most 2 same-direction positions across XRP/SOL/ETH (corr2)** raises the return and lowers the drawdown: C6+E3 +1,127% with DD 46%, and 2024-26 +349% with DD 36%.
  - Adding a half-risk brake 10% below the peak brings the drawdown to about 30% and halves the return.
- **Max 2 per coin with up to 6 open (no cross-coin cap):** +1,307%, DD 62%. With at most 2 same-direction positions across the coins (4 open at most): +1,825%, DD 50%. Six open positions happen at only 1% of entries.
- **Crowded positions (2026-10-21):**
  - With up to 6 open, the worst day was -12.8%. The 12% budget caps one move.
  - 4–5 same-direction positions happened only 5 times in 4 years.
  - With the 2-same-direction cap, the worst day was -10.4% and the max DD 49.5% vs 62.5%.
- **The user's constraints (2026-10-21):** every coin may always open its first position, up to 5 same-direction positions in total.
  - Result: +1,368%, DD 62%; with the brake +646%, DD 42%.
  - Adding the second only when the first is in profit or at +0.5R is worse.
  - Blocking the third coin's same-direction first position (B) stays better: +1,825%, DD 50%.
- **Implementation check (2026-10-21), the agent's own engine and account on 4 years:**
  - The 15m signal with the dip + limit entry and the user's rules: +773% (DD 63%).
  - Entering at once: +508%. A market order after the dip: +323%.
  - The research's +1,357% assumed every dip entry fills; 342 limit entries miss, often the runaways. Always validate a research entry rule with the engine's own fill logic.

## 2026-10-21 · stop_mult_075 · {"stop":{"multiplier":0.75}}
(auto) Rejected on history before any forward trade: expectancy +0.293R is not 0.05R above the baseline's +0.259R; profit factor 1.53 below the baseline's 1.56; half 1: +0.195R, below the baseline's +0.198R

## 2026-10-21 · stop_mult_080 · {"stop":{"multiplier":0.8}}
(auto) Rejected on history before any forward trade: expectancy +0.297R is not 0.05R above the baseline's +0.259R

## 2026-10-21 · stop_mult_075 · {"stop":{"multiplier":0.75}}
A stop at 0.75 of the swing (same target price) is past the sweet spot: +0.293R vs +0.259R but PF 1.53 vs 1.56 and half 1 +0.195R vs +0.198R. Tightening further stops out more winners that first dip about 0.3-0.8R against, and the cost per R rises; the gain from 0.8 to 0.75 is gone. Do not tune the multiplier lower.

## 2026-10-21 · stop_mult_080 · {"stop":{"multiplier":0.8}}
A stop at 0.8 of the swing is better in both halves (+0.224R vs +0.198R, +0.370R vs +0.320R) with the same PF 1.56, but only +0.038R overall, below the 0.05R bar, with DD 13.2R vs 11.1R. Most of the gain is the bigger win in R on the same exits, not better trades; 0.75 is already worse, so it is a flat, small edge on a 100-day sample. Worth a 4-year check in research tools before any new proposal.

## 2026-10-21: 1m and 3m charts (research/notes/2026-10-21-lowtf-test.md)

- **On one year of XRP/SOL/ETH, the baseline rules lose on 1m** (-0.19R a trade; costs about 0.30R a trade) **and break even on 3m** (+0.01R).
- 5m was -0.01R and 15m +0.06R in the same year.
- Lower charts mean more signals but smaller stops, so fees eat the edge.

## 2026-10-21: FOMC and 8:30 news days (research/notes/2026-10-21-macro-events.md)

- **The hour after FOMC is about 3x a normal hour's range** (BTC 1.77% vs 0.60%), with 0.5%+ both ways in about 40%. After 8:30 releases it is about 2x.
- **The planned design's trades open over events did better** (FOMC +0.19R, 8:30 +0.16R, vs +0.05R otherwise). Its 1.5%+ swing stops survive the wicks, and the moves reach targets.
- **Keep-away rules** (no entries ±1 h, closing before the event) cut the 4-year return from +783% to +540–647% without lowering the drawdown. Do not black out events.
- The live risk is slippage on stops during spikes. Measure it before going live.

## 2026-10-21: daily news through price shocks and Fear & Greed (research/notes/2026-10-21-news-proxies.md)

- **Entries within 1 h after BTC moved 2%+ in 5 minutes lose:** -0.22R on the main coins, -0.84R on the other coins.
  - Waiting 1 h after such a move: +985% vs +783% over 4 years, better in both halves, and fewer than 2% of trades are affected.
- **No trades when the Fear & Greed Index is below 20 or above 80:** +1,272% vs +783%, both halves better.
  - Replicated on the other coins (+0.034R vs +0.007R).
  - Extreme-greed longs are the worst group (-0.41R).
- **Contrarian or with-the-crowd side rules by Fear & Greed fail.**
- **Coin-level shock waits** cut the drawdown but are not proven.
- **Both candidates need the agent's own engine on 4 years before a change.** Fear & Greed needs the user's approval as a new external input.

## 2026-10-22 · min_stop_175 · {"filters":{"min_stop_pct":1.75}}
(auto) Rejected on history before any forward trade: expectancy +0.146R is not 0.05R above the baseline's +0.258R; profit factor 1.30 below the baseline's 1.56; half 1: -0.012R, below the baseline's +0.178R; half 2: +0.286R, below the baseline's +0.336R

## 2026-10-22 · lookback_8 · {"stop":{"lookback":8}}
(auto) Rejected on history before any forward trade: expectancy +0.199R is not 0.05R above the baseline's +0.258R; profit factor 1.41 below the baseline's 1.56; half 1: +0.071R, below the baseline's +0.178R; half 2: +0.302R, below the baseline's +0.336R

## 2026-10-22 · max_candles_48 · {"exit":{"max_candles":48}}
(auto) Rejected on history before any forward trade: expectancy +0.148R is not 0.05R above the baseline's +0.258R; half 1: +0.040R, below the baseline's +0.178R; half 2: +0.253R, below the baseline's +0.336R

## 2026-10-22 · be_125 · {"exit":{"breakeven_r":1.25}}
(auto) Rejected on history before any forward trade: expectancy +0.229R is not 0.05R above the baseline's +0.258R; profit factor 1.51 below the baseline's 1.56; half 1: +0.142R, below the baseline's +0.178R; half 2: +0.313R, below the baseline's +0.336R

## 2026-10-22 · min_stop_175 · {"filters":{"min_stop_pct":1.75}}
A 1.75% minimum stop is worse in both halves (-0.012R and +0.286R against +0.178R and +0.336R), PF 1.30. The setups with stops between 1.5% and 1.75% are not the marginal ones; they carry much of the edge. With 1.0%, 1.75% and 2.0% all worse, 1.5% is a clear peak: do not tune min_stop_pct again.

## 2026-10-22 · lookback_8 · {"stop":{"lookback":8}}
An 8-candle swing stop is worse in both halves (+0.071R and +0.302R against +0.178R and +0.336R), PF 1.41. With lookback 15 also worse, 10 candles is the right swing for this setup: a shorter swing lets different, weaker setups pass the 1.5% minimum instead of only the strong ones. Do not tune stop.lookback around 10.

## 2026-10-22 · max_candles_48 · {"exit":{"max_candles":48}}
Closing at market after 48 chart candles lowers the drawdown (7.0R vs 11.1R) but cuts the slow winners: +0.148R vs +0.258R, worse in both halves (+0.040R vs +0.178R). Trades that run long still reach the target often enough; the 26 history timeouts already earn +0.18R. A time exit is not the fix for the 44 stops that first reached +0.5R.

## 2026-10-22 · be_125 · {"exit":{"breakeven_r":1.25}}
Break-even at +1.25R is worse in both halves (+0.142R and +0.313R against +0.178R and +0.336R), PF 1.51, just like be_1r. Winners often touch 1.25R, dip back to the entry and still reach 1.5R. Break-even rules do not work with this 1.5R target at any level tested; do not propose more.

## 2026-10-22: the 9 shadow variants and the news filters with the agent's own engine (long_results; data/research/news_validate.txt)

- **3 years, XRP/SOL/ETH/BTC, the current demo rules:** only the 15m variants are positive.
  - trend15: +0.032R, demo +239%, DD 76%
  - dip15: +0.034R, demo +56%, DD 69%
  - tf_15m: +0.020R, demo +17%
  - v0 is -0.002R, demo -83%, DD 97%.
- **The 3-week forward leaderboard misleads:** every variant shows +0.3 to +0.6R there.
- **The news filters on the design (4 years, the user's rules):**
  - design alone: +773%, DD 62.7%
  - both filters: +1,123%, DD 49.5%
  - The BTC-shock wait removed only 42 trades, so most of its gain is timing luck.
  - The trades Fear & Greed removed were losers with about 77% confidence only.

## 2026-10-23: TradingView replay since June, BTC trend, the quiet drop (research/notes/2026-10-23-gate-replay.md)

- **The replay on the agent's own TradingView snapshots is exact:** v0 since 10-02 matched the live agent on all 438 shared signals and all 390 closed results.
- **TradingView vs the Python indicator copies:** the new strategy's results are almost equal (09-15 to 10-19: +0.405R vs +0.413R, 49 of 62 trades the same). The 4-year Python replays are a fair stand-in.
- **The new strategy (15m + 5m dip) since 09-15:** +0.380R, PF 1.94, 1.7 signals a day; demo at the user's rules +56.7% vs v0's +42.7%.
  - From 06-25 the Fear & Greed filter removed 27 winning trades (+5.9R, extreme fear in late June). Without filters: +210% vs +173%.
  - The filter is not proven either way.
- **BTC's direction (daily or 4h trend) does not help as a filter:** it flips between halves.
- **BTC moving a lot does help:** after a ±3% BTC day, trades did better in both directions (+0.137R / +0.099R vs +0.019R).
- A 2% BTC move within 4-7 15m candles comes before better-than-average trades (+0.081R vs +0.030R). Do not wait after it.
- **A slow 4-5% drop with small swings gives no trades:** every signal failed the 1.5% minimum stop.
  - Taking them anyway would have lost 13.1R in 72 hours.
  - The minimum stop is doing its job.

## 2026-10-23: candlestick and chart patterns (research/notes/2026-10-23-patterns-plan.md)

- **Patterns traded on their own lose on 5m, 15m and 1h after costs.**
  - They improve with the timeframe; the best are small: 1d bullish engulfing +0.088R, 4h morning star +0.050R, 4h double bottom +0.012R.
  - Inverted hammer, hanging man and tweezers are worse than chance everywhere.
- **As context for the agent's own trades, they look useful:**
  - a pattern in the trade's direction on the coin's last 1h candle: +0.099R vs -0.004R
  - the same on the last daily candle: +0.139R vs +0.022R
  - both in both halves
  - These are size-factor candidates, not filters. The next step is the account test and the overlap with tier A.
- **Any pattern on BTC's last 4h candle comes with worse trades:** -0.04R vs +0.07R.
- **Second pass, same day (research/notes/2026-10-23-patterns2-plan.md):**
  - On the first sample alone the 1h/1d pattern gap could be luck (rotation p 0.23-0.32 over 12 looks).
  - It replicated on unseen trades in both halves: dip15 on BTC +0.091R vs -0.092R, v0 +0.015R vs -0.014R, trend15 +0.070R vs +0.005R.
  - Tier A for "pattern in the trade's direction on the last 1h or 1d candle" at 3%: 4 years +1,083% (DD 67.5%) vs +848% (DD 71.5%) for flat sizing at the same 2.48% average risk; TradingView since June +278% vs +260%. The 2024-26 DD was worse than flat.
  - A bigger tier A raises return and drawdown together. On TradingView the DD jumps at 5% (22.3%).
  - The remaining candlestick patterns and the chart patterns add nothing on their own. Gap patterns never form in crypto.
  - A chart breakout in either direction marks an active market, where the design does better.
- **Higher-timeframe candle patterns as the direction for 15m/5m scalps (research/notes/2026-10-23-htf-bias-plan.md):**
  - The direction of a 1h/4h/1d candlestick pattern is no better than a coin flip; every version loses after costs.
  - The one exception: a 4h chart-pattern breakout as the bias with a 15m pullback entry and the agent's stop rules. +0.056R, about 1 trade a day on 3 coins, both halves, XRP and SOL positive, ETH negative. It is one of about 20 tests, so it is a candidate second engine that needs validation.
- **Indicators plus candle patterns (research/notes/2026-10-23-confluence.md):**
  - 31% of the design's 15m signal candles are a recognisable pattern. A same-way marubozu on the signal candle did better (+0.19 to +0.37R, small samples).
  - A signal after three same-coloured candles (identical three crows) is late: -0.21R.
  - The three-line strike in its strike direction beats chance on 1h, but it still loses after costs.
  - The working combination is the agent's indicators plus a same-way pattern on the higher timeframe (1h/1d).
- **BTC leads the alts (research/notes/2026-10-23-btc-and-engine2.md):**
  - On BTC -3% days, XRP/SOL/ETH fell on 93-99% of them.
  - BTC's slow trend does not help, but BTC's move over the last 12 h (2%+) known at the decision does: with it +0.158R, against it +0.005R. It replicated on v0.
  - The tier-A package (1h/1d pattern, 4h chart breakout, BTC 12h move with the trade), with trades against a 2%+ BTC 12h move skipped: 4 years +1,430%, DD 59.3% vs +728%, DD 62.7% for flat 2%. Both halves are better.
  - The second engine (4h chart breakout -> 15m) adds trades and money but does not replicate on 9 other coins (+0.017R). Shadow first.
- **Tier-A package checked on 13 coins and a second replay (research/notes/2026-10-24-patterns-per-coin-plan.md):**
  - The 1h/1d candle-pattern factor (b) is fragile. It fades after 2025, flips between two replays of the same window, and fails on 9 other coins. Drop it.
  - The 4h chart breakout (c) and the BTC 12h move (d) hold on XRP/SOL/ETH in both replays and windows, but not on other coins.
  - Skipping trades against a 2%+ BTC 12h move cuts the drawdown in every data set.
  - Revised package a+c+d + skip: 4 years +1,089% (DD 59.7%); 13-coin XRP/SOL/ETH +120% (DD 54.3%); TradingView +219% (DD 12.2%). It beats today's tiers everywhere, with a lower DD everywhere.
  - The design itself is weak on most other coins (+0.017R average), so coin choice matters.
- **Trades a day with the revised package (research/notes/2026-10-24-patterns-per-coin-plan.md):**
  - About 1.6 a day over 4 years; 1.1 a day in the quieter last 4 months.
  - Quiet BTC days give 0.8 a day at about 0R. Volatile days give 2.2 a day at +0.09R to +0.45R.
  - On high-volume days: 2.3 a day at +0.12R to +0.24R. The strategy earns on active days.
