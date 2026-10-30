# 2026-10-29: walk-forward validation of the Bayesian scoreboard (plan, written before the results)

The user approved this research step for the design in research/notes/2026-10-29-bayesian-scoreboard-design.md. They
asked for it on the 4-year data and on the data since 1 Aug. Nothing is built.

## Samples

v4's trades with the fixed plan's R and exit time (data/research/exit_tp/trades.csv). Each trade's context
(`context_json`) comes from its own journal:
- 4 years: 3,054 trades, 2022-10 to 2026-10, from journal-news.db.
- Since Aug: 128 trades, from journal-stopdip-2026-08-01.db.

## The scoreboard, walking forward

At each trade's entry, it knows only the trades that have closed before that moment (exit time <= entry). Nothing from
the future is used.
- **Independent moves.** Trades entered within 30 minutes of each other belong to one move (the gate's rule). n_eff of a
  group = its number of moves.
- **Group means.** Each group's mean R gets a normal posterior with partial pooling. mu0 = all known trades' mean,
  sigma = their spread, tau = 0.15R (robustness: 0.10R).
- **P(group > rest)** = Phi of the posterior difference over its spread.
- **Groups** (fixed list): tier A; each tier-A reason (open interest/trendline, 4h chart breakout, BTC 12 h move with the
  trade); long; XRP; SOL; ETH; 5m dip found; 4h trend with the trade; squeeze fired; fear & greed outside 20-80; the
  coin's 24 h / 30 d volatility at 1.44 or more (F6 from regime_test.py).
- **Multi-factor model** (for sizing): a Bayesian linear regression of R on those flags (the ML repo's chapter 3). Each
  coefficient has a N(0, tau^2) prior and the intercept is mu0. Every move counts once (each trade is weighted
  1/size of its move). It is refitted every 25 closed trades.
- **Since Aug:** the scoreboard starts with the 4-year trades closed before 2026-08-01 as its history, at full weight,
  then learns from the trades since Aug as they close.

## Test 1: calibration (is what it says true?)

- **When:** every 30 days from 2023-01 to the end, for every group.
- **The forecast:** the predictive probability that the group beats the rest over the next 90 days. This is the
  posterior plus the noise of the coming trades, from the number of moves that actually came.
- **What is counted:** whether it then did.
- **Requirement:** at least 5 moves in the group and in the rest in those 90 days.
- **Report:**
  - a calibration table (forecast bins against how often it happened)
  - the Brier score against a coin flip (0.25)
  - the hit rate of confident forecasts (>= 80% or <= 20%)
- **Pass:** the Brier score is below 0.25 in both halves, and the confident forecasts come true at least about as often
  as they say.

## Test 2: sizing

The account uses the user's rules ($150, max 5 open, 2 a coin, opposite skipped, 12% budget, engine2_check.account).
- **S0 (now):** tier A 3%, B 2%.
- **S1 (adaptive tier):** a tier-A trade gets 3% only while the scoreboard says P(A > B) >= 80% at its entry; otherwise 2%.
- **S2 (the model picks the 3% trades):** a trade gets 3% when the regression's predicted R is in the top 18% of the
  previous 300 trades' predictions. That is about as many 3% trades as tier A has now; the rest get 2%.
- **Windows:** 4 years, 2022-24, 2024-26, since Aug.
- **Pass:** the account ends higher than S0 in both halves and since Aug, with the drawdown not more than 3 points worse.

**A caution for reading test 2:** tier A's factors were found on these same 4 years. The fixed S0 therefore has
hindsight there, and the fairer comparison is since Aug.

**How the result is used:**
- Calibration passes, sizing does not: the scoreboard is worth building as an advisory report only.
- Both pass: propose it, with sizing as a separate later step.
- Calibration fails: do not build it.

## Results (written after the run)

Tool: research/tools/scoreboard_validate.py. Output: data/research/scoreboard_validate.txt.

**Calibration fails.** The forecasts for the next 90 days are about as good as a coin flip.

| window | forecasts | Brier (coin flip 0.2500) | confident (posterior >= 80% or <= 20%) came true | estimate vs real difference |
|---|---|---|---|---|
| 2023-01 to 2024-09 | 224 | **0.2544** | 57% | +0.08 |
| 2024-10 to 2026-07 | 247 | 0.2477 | 58% | +0.16 |
| since Aug (every 15 days) | 37 | 0.2487 | 58% | +0.29 |

- **The calibration table (4 years):**
  - Forecasts of 55-65% and 65-80% came true 66% and 64% of the time; groups called better were a little better.
  - Forecasts of 20-45% came true 47-48%; "worse" calls were a coin flip.
- **Why:** the real differences between groups are small (about 0.1R). Three months of trades on one group are much
  noisier than that, so short-term outcomes cannot be called. A tau of 0.10R changes nothing.

**Learning tier A took two years.**
- Starting from no data in 2022-10, P(tier A beats B) was 50% at 2023-01, 53% at 2024-01, 90% at 2025-01 and 92% at
  2026-01.
- With the 4-year history it was 98-99% throughout since Aug.

**Sizing fails.**

| | 4 years | 2022-24 | 2024-26 | since Aug |
|---|---|---|---|---|
| S0 now (tier A 3%) | $1,675 DD 60% | $388 | $649 | $394 |
| S1 tier A 3% only while P(A>B) >= 80% | $1,501 DD 58% | $369 | $612 | $394 |
| S2 the model picks the 3% trades | $1,232 DD 62% | $348 | $534 | $366 |

- S1 holds tier A at 2% during the two learning years, so it gives up money that tier A would have earned.
- S2's picks made +0.031R a trade against tier A's +0.153R over 4 years, and +0.442R against +0.574R since Aug. The fixed
  tier rule chose better even since Aug.

**What the scoreboard showed at the end of the 4 years** (in-sample, a summary rather than a forecast):
- tier A +0.138R (P 98%)
- each tier-A reason P 87-93%
- the coin's busy last 24 h +0.102R (P 96%)
- longs worse than shorts (P 1%), the opposite of since Aug: the side is regime-dependent, as found before
- the 4h trend with the trade worse (P 16%)

**Conclusion, by the rule set in advance:**
- Calibration failed, so do not build the scoreboard.
- Keep the fixed tier A 3% / B 2%.
- The gate's cluster bootstrap and the research halves already give the "how sure are we" view.
