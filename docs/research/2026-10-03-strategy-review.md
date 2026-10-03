# Strategy review — 2026-10-03

**Why:** After Phase 3, the paper account lost 5.35%. The user asked:
- Are the indicators used well, and are fake signals the problem?
- Did the position limit make the agent miss the good signals?
- Should higher timeframes (1h, 4h, 1D) count when they disagree with 5m and 15m?
- Are the stops too tight? Would cross margin and a stop beyond higher-timeframe support or resistance help?
- How do we get to fewer trades with higher confidence?

**Approach:** Answer with data, one change at a time, as in [Phase 5](../phases/phase-5-learning-loop.md):
1. Check the first two weeks of shadow trades.
2. Load much more history.
3. Test each idea as its own variant.
4. Accept an idea only if it also holds on data it was not drawn from.

## 1. The video's rules are implemented exactly

The baseline v0 is the Q-Trend + Klinger video's checklist, with the video's settings:

| Video rule | Baseline v0 |
|---|---|
| Q-Trend buy / sell arrow (ATR period 32, EMA smoother 10) | Trigger: Q-Trend BUY / SELL alert flag (normal and strong) |
| Klinger histogram green / red (fast 38, slow 60) | Klinger histogram ≥ 0 for longs, < 0 for shorts |
| Bullish / bearish candle | Candle closes up / down |
| Stop below the recent swing low | Lowest low (highest high) of the last 10 candles |
| Target 1.5 × risk | Fixed take-profit at 1.5R |

The video showed two or three hand-picked wins and no statistics.

## 2. First look: two weeks of data (2026-09-19 to 10-02)

Baseline: 135 closed trades, 40% wins, −0.115R per trade. Break-even needs about 44% wins after costs.

| Finding | Trades | Win | Avg R |
|---|---|---|---|
| Signal against its own chart's Zero Lag trend | 26 | 15% | −0.78 |
| Signal with its own chart's Zero Lag trend | 109 | 46% | +0.04 |
| Entry 21:00–07:00 UTC | 52 | 29% | −0.43 |
| Entry 07:00–21:00 UTC | 83 | 47% | +0.09 |
| Swing stop closer than 1% | 38 | 29% | −0.47 |
| Swing stop 1% or more | 97 | 44% | +0.03 |
| Shorts (the market rose in these weeks) | 66 | 29% | −0.39 |
| Same rule on the 1h chart, Q-Trend + candle (35 days) | 55 | 47% | +0.17 |

More from the same two weeks:
- **Paper account:** the signals it skipped (positions full) averaged −0.136R. The ones it took averaged −0.061R. The limit did not cause the loss.
- **Wider stops:** moving the stop 1.5–3× further with a 1.5R target was worse (−0.19 to −0.26R). Moving it 2× with the target unchanged was slightly better (−0.06R).
- **Break-even at +1R:** −0.095R, a small improvement.

These patterns were found by looking at this sample. They are hypotheses until they hold on other data.

## 3. More history

| Data | Before | After |
|---|---|---|
| TradingView snapshots | 1,500 bars per chart (5m: 4 days, 15m: 13 days) | 10,010 bars per chart (Essential's limit): 5m ~34 days, 15m ~101 days, 1h ~14 months, 4h ~4.5 years |
| Binance candles | 35 days of 1m / 5m / 15m | 120 days of 1m / 5m / 15m / 1h |

## 4. Variants added (each changes one thing from v0)

| Variant | Change | Idea from |
|---|---|---|
| `filter_zl_own` | The signal must agree with its own chart's Zero Lag trend | Two-week sample |
| `session_07_21` | Only entries 07:00–21:00 UTC (12:00–02:00 Pakistan time) | Two-week sample |
| `min_stop_1pct` | Skip setups whose swing stop is closer than 1% | Two-week sample |
| `confirm_no_klinger` | No Klinger confirmation (to compare with `tf_1h`) | Reference |
| `tf_1h` | Trade the 1h chart instead (it has no Klinger, so Q-Trend + candle) | The user's chart reading |
| `stop_1h_swing` | Stop beyond the last 10 1h candles; target unchanged | The user's support/resistance idea |
| `stop_wide_2x` | Stop twice as far; target unchanged | Two-week sample |
| `breakeven_1r` | Stop to break-even once the price reached +1R | Two-week sample |
| `exit_opposite` | Close when the opposite Q-Trend arrow appears | Signals on both sides in scalping |

## 5. Results on the full history

Replay: 26 variants, 28,072 closed trades. `verify-trades`: 150/150 random trades match an independent re-computation, including the new stop and exit rules.

The baseline has 1,104 closed trades from 2026-06-24 to 10-02. The tables split them into two periods:
- **Older data** (before 09-19): data none of the ideas came from, so it is a fair test.
- **Since 09-19**: the two weeks the ideas came from.

### 5.1 The baseline loses, and costs are why

| | Trades | Win | Avg R | PF |
|---|---|---|---|---|
| Baseline v0, all | 1,104 | 39.4% | −0.159 | 0.77 |
| Older data | 815 | 40.1% | −0.146 | 0.79 |
| Since 09-19 | 289 | 37.4% | −0.195 | 0.73 |

- **Costs:** before costs the edge is about zero (−0.018R per trade). Slippage costs 0.038R and fees 0.103R, which gives −0.159R net. Costs are a fixed share of the price, so they weigh most on tight stops.
- **Paper account** (live rules: $150, 2% risk, max 2 positions, about 100 days): $150 → $70.93 (−52.7%), max drawdown 58%, $55.76 in fees, daily loss stop hit on 5 days.

### 5.2 Variants (net R per trade)

| Variant | Trades | All | Older data | Since 09-19 | Paper account |
|---|---|---|---|---|---|
| v0 (video rules) | 1,104 | −0.159 | −0.146 | −0.195 | −52.7% |
| `min_stop_1pct` | 590 | **−0.030** | **+0.009** | −0.125 | −18.6% |
| `stop_1h_swing` | 1,104 | −0.065 | −0.055 | −0.092 | **−10.2%** |
| `stop_wide_2x` | 1,102 | −0.071 | −0.056 | −0.113 | −41.1% |
| `session_07_21` | 643 | −0.093 | −0.114 | −0.026 | −49.1% |
| `stop_20` | 1,104 | −0.106 | −0.093 | −0.144 | |
| `filter_zl_own` | 871 | −0.126 | −0.139 | −0.089 | |
| `confirm_0` | 859 | −0.129 | −0.127 | −0.136 | |
| `filter_vwap` | 879 | −0.137 | −0.118 | −0.193 | |
| `filter_htf_1h` (with the 1h trend) | 472 | −0.143 | −0.124 | −0.198 | |
| `breakeven_1r` | 1,104 | −0.174 | −0.168 | −0.191 | |
| `confirm_no_klinger` | 1,168 | −0.181 | −0.170 | −0.211 | |
| `exit_opposite` | 1,106 | −0.215 | −0.237 | −0.154 | |
| `filter_htf_1h4h` (with 1h and 4h) | 233 | −0.222 | −0.169 | −0.375 | |
| `stop_5` | 1,104 | −0.290 | −0.300 | −0.263 | |
| `tf_1h` (1h chart, Q-Trend + candle) | 167 | +0.026 | −0.001 | +0.222 | **+9.4%** (102 trades) |

Paper-account figures were replayed on a copy of the journal, with that variant as the baseline.

### 5.3 What held and what did not

- **Stop distance matters most.** Baseline trades whose swing stop was under 1% lost 0.31R in both periods (514 trades). Stops of 2% or more made +0.12R (136 trades: +0.17 older, +0.02 recent). The stop variants (`min_stop_1pct`, `stop_1h_swing`, `stop_wide_2x`, `stop_20`) beat the baseline in both periods; `stop_5` was much worse. Part of the reason is costs: a wider stop makes fees a smaller share of R.
- **Higher timeframe: trading with it did not help.** The 1h and 1h+4h trend filters did not improve results. Baseline trades *with* the 4h Zero Lag trend lost more than trades against it (−0.24R vs −0.08R). The gap held for longs and shorts, on 5m and 15m, and in both periods.
- **Time of day:** 13:00–21:00 UTC was best and 00:00–07:00 UTC worst, in both periods. The 07–21 filter helped less in the older data (+0.03R) than in the recent weeks.
- **15m beat 5m** in both periods (−0.10R vs −0.21R). 5m stops are tighter.
- **No exit change helped:** break-even at +1R, opposite-arrow exit, hybrid exit and 1R / 2R targets were all equal or worse.
- **The own-chart Zero Lag filter did not hold.** It looked strong in the two weeks (−0.78R against vs +0.04R with). In the older data it made no difference (−0.139 vs −0.146).
- **The idea combination was overfitted.** "Own trend + 07–21 + stop ≥ 1%" looked like +0.58R and +0.14R in the two weeks. It was −0.005R on the older data.
- **The 1h chart breaks even.** It made +0.026R with a median stop of 2.6% and a median hold of 24 hours. The older data was flat (−0.001R) and the recent 20 trades were good. It is a swing-trading pace, not scalping, and needs more data.
- **Klinger helps a little:** without it, results were 0.02R worse.

## 6. Round 1 decisions (approved by the user)

- **Not ready for live trading.** The video's rules alone would have halved the account.
- **Baseline v1 = `min_stop_1pct`:** the video rules, but setups whose swing stop is closer than 1% are skipped. On this history it met the [Phase 5](../phases/phase-5-learning-loop.md) criteria:
  - more than 100 trades
  - expectancy at least 0.05R above the old baseline (+0.13R)
  - higher profit factor and lower drawdown
  - better in both periods
- **Focus stays on scalping (5m/15m), the user decided.** `tf_1h` was retired with the other variants that lost in both periods.

## 7. Round 2: challengers on top of v1

| Variant (one change from v1) | Trades | All | Older data | Since 09-19 |
|---|---|---|---|---|
| v1 baseline (stop ≥ 1%) | 590 | −0.030 | +0.009 | −0.125 |
| `session_13_21` (US session) | 229 | **+0.115** | +0.062 | +0.258 |
| `min_stop_2pct` | 136 | **+0.122** | +0.165 | +0.022 |
| `htf_against_4h` | 314 | +0.021 | +0.041 | −0.033 |
| `session_07_21` | 359 | +0.016 | −0.022 | +0.114 |
| `confirm_0` | 475 | −0.011 | +0.005 | −0.052 |
| `trigger_strong` (strong Q-Trend arrows only) | 204 | −0.027 | +0.062 | −0.237 |
| `stop_1h_swing` | 590 | −0.035 | −0.012 | −0.091 |
| `filter_vwap` | 505 | −0.037 | +0.013 | −0.178 |
| `tf_15m` | 347 | −0.045 | −0.046 | −0.039 |
| `trigger_macd` (ATP MACD buy/sell) | 1,107 | −0.058 | −0.044 | −0.092 |
| `trigger_macd_div` (ATP MACD divergences) | 196 | −0.071 | −0.080 | −0.042 |
| `stop_20` | 801 | −0.083 | −0.080 | −0.092 |
| `time_stop_24` (close after 24 candles) | 592 | −0.146 | −0.175 | −0.075 |

## 8. Other strategy families tried (prototypes)

| Strategy | Sample | Result |
|---|---|---|
| 4-hour range fade (the user's first video): fade a close back inside the first New York 4h range, stop at the breakout extreme, 2R | 120 days of Binance candles | 5m: 2,051 trades, 33% win, −0.44R. 15m: 1,130 trades, −0.26R. With stops ≥ 1%: −0.13R / −0.09R. |
| VWAP band fade: fade a close back inside VWAP band 2 | TradingView snapshots | 5m: −0.35R. 15m: −0.38R. |

Both failed for the same reason as v0: their stops are tight (median 0.35–0.63%), so costs dominate. Neither was built into the engine.

## 9. Limit-order entries

Simulated rule:
- Place a limit order at the entry price when the signal candle closes.
- It fills only if the first minute trades **strictly through** that price. A resting order at that price is then certainly filled.
- A fill pays the maker fee (0.02%) instead of taker + slippage (0.07%).
- In the fill minute a stop counts, but a target does not.

| Rule | Market entry | Limit entry (first minute) | Filled |
|---|---|---|---|
| v1 | −0.030R | +0.018R | 89% |
| v1 + US session | +0.115R | +0.155R | 93% |
| stop ≥ 2% | +0.122R | +0.162R | 93% |
| v1 + against 4h | +0.021R | +0.081R | 90% |

- **The gain is about +0.04 to +0.06R per trade, and it held in both periods.**
- **No adverse selection:** the trades that did not fill averaged −0.15R to −0.21R. They were worse than the filled ones, not the winners that ran away.
- **Live caveat:** the agent places the order a few seconds after the candle close, not at its exact open. Phase 6 will compare live fill rates with this model.

## 10. Combinations → baseline v2

All signals of the video rules, limit entries. "Before/after 09-07" is a median split; "before/after 09-19" is the split from the idea sample.

| Rule | Trades | All | Before 09-07 | After 09-07 | Before 09-19 | After 09-19 |
|---|---|---|---|---|---|---|
| stop ≥ 1% | 527 | +0.018 | −0.044 | +0.076 | +0.035 | −0.021 |
| **stop ≥ 1.5%** | 260 | **+0.116** | **+0.067** | **+0.159** | **+0.162** | **+0.017** |
| **stop ≥ 1.5% + 13–21 UTC** | 131 | **+0.241** | **+0.021** | **+0.400** | **+0.199** | **+0.336** |
| stop ≥ 2% | 127 | +0.162 | −0.020 | +0.306 | +0.192 | +0.094 |
| stop ≥ 1% + against 4h | 283 | +0.081 | −0.119 | +0.268 | +0.092 | +0.053 |
| stop ≥ 1.5% + against 4h | 146 | +0.177 | −0.121 | +0.422 | +0.193 | +0.140 |

**Baseline v2 = the video's signals + stops of at least 1.5% + limit-order entries.** It is the rule that was positive in all four sub-periods with the most trades. Each part has a reason:
- Costs are a fixed share of the price, so they are a small part of R only when the stop has room.
- A wide swing means the market is moving rather than chopping.
- Limit entries cut the entry cost.

The US-session version is stronger but trades half as often. It runs as the leading challenger.

## 11. v2 on the full history

Replay with v2 as the baseline. `verify-trades`: 200/200 random trades match an independent re-computation, limit entries included.

| Variant (one change from v2) | Trades | All | Older data | Since 09-19 | Paper account (~100 days, live rules) |
|---|---|---|---|---|---|
| **v2 baseline** | 260 | **+0.116** | +0.161 | +0.018 | **$150 → $179 (+19.5%)**, max drawdown 17.9% |
| `session_13_21` | 131 | +0.240 | +0.198 | +0.336 | +8.9% (69 trades) |
| `tf_15m` | 180 | +0.159 | +0.142 | +0.218 | **+51.3%**, max drawdown 17.9% |
| `session_07_21` | 180 | +0.159 | +0.164 | +0.147 | |
| `htf_against_4h` | 146 | +0.177 | +0.192 | +0.141 | +12.8% |
| `min_stop_2pct` | 127 | +0.163 | +0.192 | +0.096 | +14.7% |
| `filter_vwap` | 222 | +0.133 | +0.187 | +0.003 | |
| `trigger_strong` | 105 | +0.152 | +0.296 | −0.162 | |
| `confirm_0` | 214 | +0.099 | +0.130 | +0.035 | |
| `stop_1h_swing` | 260 | +0.083 | +0.114 | +0.016 | |
| `market_entry` | 292 | +0.072 | +0.131 | −0.067 | +1.1% |
| `min_stop_1pct` | 527 | +0.018 | +0.034 | −0.021 | +4.5% |
| `video_original` (reference) | 1,104 | −0.159 | −0.146 | −0.195 | −52.7% |

**Caution:**
- These rules were chosen by looking at this history. Some of the gain may be luck from testing many ideas.
- The 13–21 UTC version has only 131 trades.
- The fresh forward run is the real test.

## 12. Forward test (from 2026-10-03)

- **Fresh start.** The paper account was reset to $150 (`paper-reset --yes --from-now`). It follows v2 and takes only new signals, so the go-live gate counts forward results only.
- **What runs.** The exploration book runs v2 and its 12 challengers on every new signal.
- **Promotion.** After at least 50 fresh trades, a challenger that beats v2 by the [Phase 5](../phases/phase-5-learning-loop.md) rules becomes the baseline. The first candidates are `session_13_21` and `tf_15m`.
- **Live parity.** Live trading (Phase 6) will place exactly the same orders as the paper account:
  - a post-only limit entry for one minute, cancelled if unfilled
  - the same stop and target
  - the same sizing

## 13. More trades per day? (asked by the user)

**Other signal sources under the v2 rules** (stop ≥ 1.5%, limit entry), replayed on a copy of the journal:

| Signal source | Trades | All | Older data | Since 09-19 |
|---|---|---|---|---|
| Q-Trend (v2) | 260 | +0.116 | +0.161 | +0.018 |
| Zero Lag trend flip | 353 | +0.043 | +0.079 | −0.052 |
| ATP MACD buy/sell | 383 | −0.070 | −0.052 | −0.120 |
| Zero Lag entry arrows | 92 | −0.071 | −0.038 | −0.170 |
| Q-Trend + Zero Lag flip together | 587 | +0.069 | | |

More signal sources add trades but lower the quality, so none was added. A wider confirmation window (5 candles) produced exactly the same trades as 3.

**Where the trades go.** v2 produced about 6.4 signals per day since 09-19 (3 coins, 5m and 15m), and the exploration book simulates all of them. The paper account takes about 2 per day because of its limits (max 2 open positions, 1 per coin) and because trades last hours.

**Paper account with other limits** (v2, ~100 days):

| Max positions / per coin | Result | Paper trades per day (last 34 days) | Max drawdown |
|---|---|---|---|
| 2 / 1 (current) | +19.5% | 2.1 | 17.9% |
| 3 / 1 | −11.9% | 2.5 | 26.4% |
| 4 / 2 | +34.2% | 3.3 | 26.6% |
| 6 / 2 | +34.0% | 3.6 | 28.3% |

The 3 / 1 result shows how much a small paper sample depends on which signals happen to be taken. The exploration book, with every signal, is the steadier measure.

**Ways to more trades without lowering quality:**
1. Count the go-live sample on the baseline's forward exploration trades (~6 per day) and keep the paper account as the money view.
2. Allow more paper/live positions (4 / 2): more trades, but a deeper drawdown.
3. Add coins. Each adds about 2 signals per day, but TradingView Essential's 5 layouts and 2 charts per layout are all in use. It would need symbol cycling on the AGENT tabs or a bigger plan.

The user decides.
