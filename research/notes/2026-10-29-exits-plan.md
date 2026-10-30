# 2026-10-29: smart targets and an exit plan for wrong trades (plan, written before the results)

The user's questions:
1. A target that follows the chart (swing highs/lows, support and resistance, patterns) instead of the fixed 1.5R, so
   that a move that runs further is not cut short.
2. An exit plan: leave a trade early when the chart shows it is wrong.
3. ML may help. Check the repo https://github.com/mfrdixon/ML_Finance_Codes.

Already tested and failed (not retested): break-even at 1R and 1.25R, partial exits at 0.75R and 1R, fixed targets
1.25R / 1.75R / 2R, a Supertrend trailing exit and a Supertrend runner after 1.5R, the opposite-signal exit, a 12 h time
exit, wider stops.

## Samples

- **4 years:** the design's trades (journal-news.db v0-e78944, XRP/SOL/ETH, 2022-10 to 2026-10-18). Each trade is walked
  on 1m candles with the tracker's rules (wide_stop_4y.run, which matched the tracker on 3263/3263 exits). v4 = without
  the trades against a 2%+ BTC 12 h move. Tier A as in factor_compare.
- **Since 2026-08-01:** v4's 128 trades from the agent's own engine on its TradingView data (stop_dip_replay.py).
- Halves: 2022-10 to 2024-09 and 2024-10 to 2026-10.

## Versions (fixed before the results; no tuning)

**Support/resistance targets.**
- The levels are swing highs and lows on 15m (5 candles each side) or 1h (3 each side).
- A level counts only if it was known at the fill, was not yet broken, and is at most 10 days old.
- The target sits 0.1 x the 15m ATR before the level.
- Three ways to use it:
  - **front:** take the level when it lies between 0.8R and the planned target.
  - **extend:** when nothing lies in the way, take the next level beyond the plan, up to 3R.
  - **both:** the nearest level between 0.8R and 3R.

**Runners.** At the target touch the trade stays open. The stop moves to +1R (or +1.25R) and then trails at every 15m
close. Three ways to trail:
- 2 x the 15m ATR from the best price
- 3 x the ATR, with the stop at +1.25R
- beyond the last four 15m candles

Each is tried with the whole position and with half.

**Early exits for wrong trades.** Checked at every 15m close; a market exit at the next minute's open, paying taker fee
and slippage. A trade exits when:
- Q-Trend has turned against it (also tried: only when the trade is in a loss)
- after 2 h, 4 h or 8 h it has not reached +0.5R and is in a loss
- BTC has moved 1% against it and it is in a loss
- Q-Trend and Klinger are both against it and it is at -0.3R or worse
- it is at -0.5R or worse and fell 0.3R in the last hour

**ML** (scikit-learn gradient boosting, settings fixed in advance, in a separate venv; the agent's venv is untouched):
- **Exit model.** At every 15m close while a trade is open, it predicts holding to the plan minus exiting now. Exit when
  the prediction is below 0 (also tried: below -0.1R).
- **Runner model.** At the target touch, run when the predicted runner gain is above 0.
- **Target model.** At the fill, choose the target from 1R, 1.25R, 1.5R, 2R, 2.5R, 3R or the plan by the predicted result.
- **Training and testing:** train on 2022-24 and test on 2024-26, train on 2024-26 and test on 2022-24, train on
  everything before 2026-08-01 and test since 2026-08-01.

## Pass rule (the same bar as before)

**A rule version passes when:**
- On v4's 4-year trades it is better per trade than the fixed plan in both halves.
- The paired difference has t >= 2 on all 4 years.
- It is not worse since 1 Aug.
- The 4-year account (the user's rules) ends higher without a clearly deeper drawdown.

**An ML policy passes when:**
- It beats the plan on both test halves.
- It does not lose since 1 Aug.

Anything that passes is proposed for a shadow forward test, never straight to the demo.

## Results (written after the run)

Tools:
- research/tools/exit_tp_data.py (the data and the rule versions)
- research/tools/exit_tp_ml.py (scikit-learn in a separate venv in the scratchpad; the agent's venv is untouched)
- research/tools/exit_tp_report.py

Outputs: data/research/exit_tp/ and data/research/exit_tp_report.txt.

Checks:
- The 1m walk matches the agent's tracker on 3263/3263 design trades and on 128/128 trades since Aug (same R, same exit
  reason).
- v4 has 3,054 trades over 4 years (+0.039R, funding left out) and 128 since Aug (+0.330R).

**Nothing passes.** No version beats the fixed plan in both halves, and no paired difference reaches t >= 2 in its favour.

| version | 4 years | 2022-24 | 2024-26 | diff (t) | since Aug | account 4y / since Aug |
|---|---|---|---|---|---|---|
| **plan (now)** | +0.039 | +0.040 | +0.038 | | +0.330 | $1,675 DD 60% / $394 |
| fixed 2R / 3R | +0.017 / +0.013 | | | -0.022 / -0.027 | +0.247 / +0.108 | $426 / $194 |
| S/R 15m front / extend / both | +0.020 / +0.030 / +0.011 | | | -0.019 / -0.009 / -0.029 | +0.268 / +0.303 / +0.241 | $221 / $1,391 / $192 |
| S/R 1h front / extend / both | +0.021 / +0.023 / +0.005 | | | -0.018 / -0.016 / -0.034 | +0.266 / +0.293 / +0.229 | $276 / $907 / $156 |
| runner +1R, 2 ATR (all / half) | +0.036 / +0.038 | | | -0.003 / -0.002 | +0.280 / +0.305 | $1,157 / $1,463 |
| runner +1.25R, 3 ATR (all / half) | +0.040 / +0.040 | +0.046 / +0.043 | +0.035 / +0.037 | +0.001 / +0.000 | +0.257 / +0.293 | $1,575 / $1,661 |
| exit: Q-Trend against | +0.003 | | | -0.037 (-2.5) | +0.215 | $113 |
| exit: no progress at 4 h | +0.030 | +0.033 | +0.027 | -0.010 | +0.273 | $1,619 DD 46% / $309 |
| exit: no progress at 8 h | +0.033 | +0.045 | +0.024 | -0.006 | +0.334 | $2,030 DD 49% / $408 |
| exit: BTC 1% against | +0.027 | | | -0.012 | +0.307 | $607 |
| ML exit (pred < 0 / < -0.1R) | -0.029 / -0.007 | | | -0.069 / -0.047 | +0.130 / +0.239 | $24 / $117 |
| ML runner (best of three) | +0.037 to +0.038 | | | -0.001 to -0.002 | +0.274 to +0.306 | $1,274 to $1,893 |
| ML target 1R..3R | +0.031 | +0.039 | +0.025 | -0.008 | +0.116 | $751 / $250 |

**Why early exits lose.** The table shows v4's 4-year trades at the first 15m close after the hour. Holding beats exiting at
every state.

| after 2 h | trades | still hit the target | final if held | exit now |
|---|---|---|---|---|
| -0.5R or worse | 204 | 16% | -0.61R | -0.69R |
| -0.5R..0 | 1,150 | 30% | -0.19R | -0.25R |
| 0..+0.5R | 1,031 | 46% | +0.25R | +0.17R |
| +0.5R or better | 310 | 69% | +0.86R | +0.74R |

It is the same after 1 h, 4 h and 8 h:
- A trade that looks wrong still keeps a cheap chance at +1.5R. One in six recovers, and those recoveries pay for the
  rest.
- An exit also costs the taker fee and slippage. A target is a maker order.

**The user's observation about the target is right, but it cannot be used.**
- After v4's 1,196 target touches over 4 years, the price reached 2R within 24 h in 72% of them, 2.5R in 53% and 3R in 39%.
- But it came back to +1R within 24 h in 75%.
- It reached 2R before +1R in only 54%, and 3R in 27%: about a fair coin around the touch.
- Since Aug: 2R in 66%, but back to +1R in 79%.
- Every runner ends near the plan over 4 years and is worse since Aug.

**Support/resistance targets lose.**
- The nearest unbroken 15m swing level lies before the planned target in about a third of the trades. The median is 1.24R
  away on 15m and 1.46R on 1h.
- Taking profit there cuts winners more than it adds wins.
- Extending to the next level loses on the reversals.

**ML:**
- **Exit model.**
  - Its test R2 is negative in all three tests (-0.10, -0.14, -0.08).
  - In its own "exit" bucket, holding still beat exiting: +0.009R, +0.204R and +0.096R.
  - It mostly learned trade-level averages (stop %, target R, tier, side), not the timing.
  - A noisy model checked at about 80 closes a trade fires sooner or later. It closes 70% of the trades early, which costs
    a lot: the account ends at $24.
- **Runner and target models.**
  - The hindsight ceilings are large: +0.18 to +0.26R a touch, and +0.60R a trade for the best target.
  - The models capture none of it out of sample.

**The repo** (mfrdixon/ML_Finance_Codes; cloned into the scratchpad, not run):
- It is the 2020 code for the textbook "Machine Learning in Finance" (Dixon, Halperin, Bilokon): teaching notebooks for
  Python 3.6, TensorFlow 2.0 and PyMC3, on toy or old data.
- It contains no trading strategy, exit rule or cost-aware backtest. The Bitcoin RNN predicts the price 4 minutes ahead,
  scored by MSE.
- Useful only as ideas:
  - Bayesian Beta-Bernoulli estimation for the factor scoreboard of the probability-learning plan
  - an HMM/Viterbi regime model
  - RL/LSPI for optimal stopping, which is what the exit model above did with a regression

**Conclusions:**
- Keep the fixed 1.5R target and the swing stop. The stop is the exit plan for a wrong trade.
- Do not propose again: support/resistance targets, runners after the target (whole or half, +1R/+1.25R lock, ATR or
  candle trail), early exits on Q-Trend, Klinger, BTC, no-progress or fast moves, or ML exit/runner/target models on
  these inputs.
- The 8 h no-progress exit is the closest:
  - In the 4-year account it frees slots for about 130 more trades: $2,030 (DD 49%) vs $1,675 (DD 60%).
  - It is worse per trade in 2024-26 (+0.024R vs +0.038R), and that half's account ends lower ($517 vs $649).
  - It fails.
- Big moves are better caught by a separate trend engine: the daily Donchian, additive in every window
  (research/notes/2026-10-29-engines.md).
- Wrong trades are better handled before the entry, by tiering and sizing (the probability-learning plan), than after it.

## Later: is the ML runner's $1,893 skill or luck? (the user asked whether to use it for a smart target)

The test: run the runner on a random 44-47% of the target touches (the model's own rate), 300 times, in the 4-year
account (scratchpad script runner_luck.py).

| runner | the model's account | coin-flip accounts, 5% / median / 95% | coin flips at or above the model | R a touch: model vs coin flip |
|---|---|---|---|---|
| last 4 candles, +1R | $1,893 | $976 / $1,570 / $2,506 | 23% | -0.006 vs -0.006 |
| 2 ATR, +1R | $1,559 | $1,004 / $1,418 / $2,157 | 34% | -0.002 vs -0.004 |
| 3 ATR, +1.25R | $1,274 | $1,112 / $1,657 / $2,427 | 86% | -0.004 vs -0.000 |

- The model has no skill: it gains the same per touch as a coin flip.
- Which touches run moves a 4-year account between about $1,000 and $2,500 by luck alone. Judge by the R a trade in both
  halves, not by the account total of one run.
- Do not use the ML runner.
