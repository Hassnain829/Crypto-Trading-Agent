# 2026-10-29: market regime (HMM) and volatility sizing for v4 (plan, written before the results)

The user asked to test two ideas from the ML repo (mfrdixon/ML_Finance_Codes, chapter 7): a hidden Markov model regime
and a Kalman-filter volatility estimate, as risk-size factors. Research only; nothing is built.

## Samples

v4's trades from research/tools/exit_tp_data.py (data/research/exit_tp/trades.csv), with the fixed plan's R and exit time:
- 3,054 trades over 4 years: 2022-10 to 2026-10, halves split at 2024-10-01.
- 128 trades since 2026-08-01, from the agent's own data.

Candles: Binance 1d and 4h since 2020 (data/research/outside.db, refreshed to 2026-10-29).

## Factors (each read at the last candle closed before the fill)

The HMM and Kalman code is written here in numpy. The repo's code does not run on Python 3.14.

The HMMs:
- **F1. HMM, 2 states, BTC daily.** Inputs are the daily log return and the log high/low range. Bucket: P(volatile
  state) > 0.5.
- **F2. HMM, 3 states, BTC daily.** Bucket: the most likely state (calm, middle, volatile).
- **F3. HMM, 2 states, BTC 4h.** Bucket: P(volatile) > 0.5.

How the HMMs are fitted:
- Fitted by Baum-Welch (5 starts, the best likelihood kept) on BTC data from 2020-01 to 2022-09 only, before the trades.
- The parameters are then fixed.
- Only the filtered probability P(state | data so far) is used. Viterbi and smoothed paths look into the future and are
  not used.
- Robustness: a refit on data up to 2024-09, used for 2024-26 and since Aug.

The volatility factors:
- **F4. BTC volatility percentile.** A Kalman local-level filter runs on the log daily realized variance (from 4h
  returns); its noise variances are fitted on 2020-01 to 2022-09. The filtered level's percentile against the previous
  365 days gives the bucket: thirds at 1/3 and 2/3.
- **F5. The coin's own volatility percentile.** The same filter on the coin's daily realized variance.
- **F6. The coin's 24 h volatility against its last 30 days.** The realized volatility of the last six 4h candles,
  divided by its median over the 180 candles before. Thirds, with the cut points taken from the 2022-24 trades.

## Tests

1. **Each factor as a group split.** R a trade per bucket, for 4 years, each half and since Aug. A factor passes when the
   high-minus-low difference has the same sign in 2022-24, 2024-26 and since Aug, and the day-clustered t on 4 years
   is at least 2.
2. **Sizing in the account.** The account uses the user's rules ($150, max 5 open, 2 a coin, opposite skipped, 12%
   budget, A 3% / B 2%).
   - The risk is multiplied by 1.25 in the most volatile bucket and by 0.75 in the calmest (the middle bucket x1).
   - The multipliers are rescaled so that the average risk equals today's.
   - The direction is fixed in advance from earlier findings: volatile days paid better, and trades after a +-3% BTC
     day did better.
   - Sizing passes when the account ends higher than today's in both halves and since Aug, and the drawdown is not more
     than 3 points worse.
3. The account code is checked: with all multipliers at 1 it must equal engine2_check.account.

Trades are never skipped (the user's rule). The regime only changes the size.

## Added after the first results (before running it): a replication on coins the factors were not found on

- F5 (the coin's volatility percentile) came out the same way in all three windows, but in the OPPOSITE direction to the
  plan: calm coins gave better trades. Its t was only -1.6.
- F6 (24 h against 30 days) was good over 4 years but not since Aug.

Both are checked on data not used so far, with the same definitions and F6's cut points from 2022-24 (0.87, 1.44):
- **AVAX:** the design's trades over 4 years (journal-avax.db). 4h candles come from the 15m candles; the Kalman filter is
  fitted on the first year.
- **BTC:** the old baseline v0's trades over 4 years (research journal), with the same BTC filter as F4.
- **Ten other coins:** the design's trades on 2025-04 to 2026-10 (journal-other.db). There is only 1.5 years of data, so
  the percentile uses 180 days and the filter is fitted on the first 6 months.

**Replication rule:** the high-minus-low difference has the same sign as on XRP/SOL/ETH in each of the three samples.

## Results (written after the runs)

Tools: research/tools/regime_test.py and regime_replicate.py. Outputs: data/research/regime_test.txt and
regime_replicate.txt. The account check (all multipliers 1 = engine2_check.account) holds.

**The HMMs find sensible states, but they do not help.**
- BTC daily, 2 states: calm days with a 3.8% high-low range, volatile days with 12.8%. Fitted on 2020-22.
- The volatile state covers only 7% of the trades (14% with the 2024 refit). The 3-state model's top state covers 2%.

| factor (high minus low, R a trade) | 4 years (t) | 2022-24 | 2024-26 | since Aug |
|---|---|---|---|---|
| F1 HMM 2 states daily | +0.146 (+1.5) | +0.081 | +0.227 | -1.223 (6 trades) |
| F1 refit 2024 | +0.076 (+1.0) | +0.064 | +0.089 | -0.809 (10) |
| F2 HMM 3 states daily | +0.091 (+0.4) | +0.166 | -0.036 | none |
| F3 HMM 2 states 4h | +0.035 (+0.4) | +0.158 | -0.074 | +0.042 |
| F4 BTC volatility percentile | -0.055 (-0.9) | -0.027 | -0.085 | none |
| F5 coin volatility percentile | -0.092 (-1.6) | -0.074 | -0.108 | -0.021 |
| F6 coin 24 h / 30 days | +0.075 (+1.2) | +0.113 | +0.045 | -0.224 |

- None passes.
- F1's 4-year gain mostly disappears inside tier B (+0.051R, and -0.044R with the refit). It is the "BTC 12 h move with
  the trade" factor that tier A already uses.

**Sizing in the account** (x1.25 in the most volatile bucket, x0.75 in the calmest, the same average risk; 4 years |
2022-24 | 2024-26 | since Aug):

| | 4 years | 2022-24 | 2024-26 | since Aug |
|---|---|---|---|---|
| now | $1,675 | $388 | $649 | $394 |
| F1 | $1,809 | $372 | $732 | $371 |
| F3 | $1,968 | $554 | $542 | $398 |
| F4 | $1,084 | $349 | $474 | $391 |
| F5 | $1,003 | $344 | $438 | $400 |
| F6 | $2,635 | $480 | $831 | $377 (DD 15% vs 12%) |

Every row loses in at least one window.

**The replication on new coins** (high minus low):

| | XRP/SOL/ETH (found) | AVAX design, 4 years | BTC v0, 4 years | ten coins, 1.5 years |
|---|---|---|---|---|
| F5 coin volatility percentile | -0.092 | -0.073 (t -0.8) | +0.013 | +0.040 |
| F6 coin 24 h / 30 days | +0.075 | +0.150 (t +1.9) | -0.093 | +0.033 |

- F5's "calm coins are better" does not replicate. It was chance.
- F6 points the right way on AVAX and weakly on the ten coins, but the other way on BTC and since Aug. It is too weak to
  change the sizing.

**Conclusions:**
- Keep today's sizing (A 3% / B 2%).
- The volatile-market effect that is real is already in tier A: BTC's 12 h move with the trade is a direction-aware
  volatility signal.
- Do not propose HMM regimes or volatility percentiles as size factors again.
- F6 (the coin's last 24 h against 30 days) can be one of the groups the Bayesian scoreboard follows forward, at no risk
  (research/notes/2026-10-29-bayesian-scoreboard-design.md).
