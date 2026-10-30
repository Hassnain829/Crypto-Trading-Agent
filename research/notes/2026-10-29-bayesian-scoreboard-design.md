# 2026-10-29: the Bayesian factor scoreboard (design only, not built)

The user asked (2026-10-29) for a design of the "probability learning" idea, using the Bayesian chapters (2-3) of the ML
repo mfrdixon/ML_Finance_Codes. **Nothing is built until the user says yes.** The repo's code is not used: it needs
Python 3.6 / PyMC3, and the maths below is about 100 lines of numpy.

## The problem it solves

Today the agent and the research judge a factor by its raw average, and that misleads on small samples:
- "4h chart breakout: 6 trades, +1.10R" looks great, but 6 trades say almost nothing.
- Tier A is sized at 3% because research found it better, but nothing tracks forward whether that still holds.
- The gate and the challengers use a cluster bootstrap (account/report.py edge_lower_bound) for one number per variant.
  They do not report how sure they are that one group beats another.

The scoreboard gives every group of trades three numbers that already account for the sample size:
- the best estimate of its R a trade and win rate
- the 90% range of the true value
- P(better than the rest)

## What it measures

The groups come from what every trade already records in `trades.context_json`, so no new data is needed:
- Tier A or B, and each tier-A reason: trendline, open interest +1% in 4 h, 4h chart breakout, BTC 12 h move
  (`quality`, `quality_reason`, `chart_4h`, `oi_change_4h`, `btc_change`).
- Long or short; XRP, SOL or ETH; 5m dip found or the 60-minute fallback (`dip_entry`).
- Squeeze fired (`sqz_fire`); the 4h trend with or against the trade (`htf`); the fear & greed zone (`fear_greed`).
- Each shadow challenger against the baseline, on the same signals.
- Later, if the regime test finds anything: the volatility regime (research/notes/2026-10-29-regime-plan.md).

The trades are the baseline's forward trades, one per signal, as the gate counts them (`forward_trades`).

## The maths (per group)

- **Independent moves, not trades.** Trades entered within 30 minutes of each other count as one move
  (CLUSTER_GAP_MS, the gate's rule; 2026-10-19: 43 trades were 22 moves). n_eff = the number of moves.
- **Mean R.**
  - Normal prior N(mu0, tau^2): mu0 = all forward trades' mean R (partial pooling), tau = how far groups usually sit from
    the average.
  - tau is estimated from the 4-year history (empirical Bayes); about 0.10-0.15R.
  - Data: the group's mean R with variance sigma^2 / n_eff, where sigma = the spread of R, about 1.2R.
  - Posterior: precision = n_eff / sigma^2 + 1 / tau^2, and the mean is the precision-weighted average of the group's
    mean and mu0.
  - With sigma 1.2 and tau 0.15, a group needs about 64 moves before its own average weighs as much as the prior. Small
    groups stay near the average by themselves.
- **Win rate.** A Beta prior at the overall win rate, worth 20 trades, updated with the group's wins and losses scaled to
  n_eff. This is the repo's Beta-Bernoulli example (chapter 2).
- **P(better than the rest)** = Phi((m_group - m_rest) / sqrt(v_group + v_rest)) from the two posteriors.
  **P(R > 0)** = Phi(m / sd).
- **Optional time decay** (off at first): weigh old trades less, with a half-life of about 120 days, so a regime change
  shows up. The report shows both.

## Example: what it would show today (v4 since 2026-08-01)

From the scratchpad script scoreboard_example.py: 128 trades, 89 independent moves, +0.328R overall.

| group | trades | raw R | estimate | 90% range | P(better than the rest) |
|---|---|---|---|---|---|
| tier A | 35 | +0.57 | +0.40 | +0.19..+0.61 | 77% |
| tier B | 93 | +0.24 | +0.28 | +0.11..+0.45 | 23% |
| A: 4h chart breakout | 6 | +1.10 | +0.39 | +0.16..+0.63 | 69% |
| A: open interest | 18 | +0.44 | +0.35 | +0.13..+0.57 | 58% |
| A: trendline | 11 | +0.56 | +0.35 | +0.11..+0.58 | 57% |
| long / short | 65 / 63 | +0.45 / +0.21 | +0.37 / +0.28 | | 72% / 28% |
| squeeze fired | 5 | -0.49 | +0.29 | +0.05..+0.53 | 38% |
| 4h trend against the trade | 74 | +0.42 | +0.37 | +0.18..+0.55 | 70% |

How to read it:
- "4h chart breakout +1.10R" becomes +0.39R and 69%: promising, not proven.
- Tier A is probably better than B (77%), but not yet at the 90% that a sizing decision should need.

## How the agent would use it (advisory first)

1. **Reports:** a scoreboard table after every daily research run (learning/pack.py adds a section), on the dashboard,
   and in `paper-report`.
2. **Flags, never automatic changes:**
   - A tier-A reason with P(better) below 50% after at least 50 moves is flagged as "not earning its 3%".
   - A non-tier factor with P(better) of at least 90% after at least 50 moves (for example the squeeze) is flagged as a
     tier-A candidate.
   - The user decides, as today.
3. **Challengers:** P(challenger > baseline) is shown next to the gate's `beats()` checks. It does not replace them.
4. **Later, only after its own backtest and the user's yes:** continuous sizing. The risk would follow the estimated R,
   clipped to 1-3% within the 12% budget.

## Code sketch (when approved)

- `src/tradeagent/learning/scoreboard.py`:
  - `factor_flags(trade) -> dict[str, bool]` from context_json
  - `posterior(rs, times, mu0, sigma, tau) -> dict`
  - `scoreboard(conn, settings, since) -> list[dict]`
- A journal migration for a `factor_scores` table (day, group, n, n_eff, est_r, lo, hi, est_win, p_better, p_pos), so
  the history of each estimate can be charted.
- CLI `python -m tradeagent scoreboard`; a call in the daily research run; a dashboard panel.
- Unit tests:
  - the Beta and normal updates against hand-computed values
  - the clusters against edge_lower_bound's grouping
  - a fixture journal
- About a day of work, plus the validation below.

## Validation before building (research, about half a day)

Walk forward through the 4 years. At each trade, use only the trades closed before it.
- **Calibration:** when the scoreboard says P = 80%, is the group better over the next 100 trades about 80% of the time?
- **Sizing:** does sizing by the scoreboard beat today's fixed A 3% / B 2% at the same average risk, in both halves and
  since Aug?

Propose building only if both pass. If calibration passes and sizing does not, build the advisory scoreboard without
the sizing.

## Risks and guardrails

- **Many groups:** some look good by chance. The shrinkage and the 90% / 50-move bars are the guard.
- **Regime change:** the optional decay, and the halves in research.
- **No live risk change without the user.** Research results serve only as the starting belief (they are in-sample),
  never as forward evidence.
