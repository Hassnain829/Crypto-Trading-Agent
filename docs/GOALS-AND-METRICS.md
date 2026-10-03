# Goals and Metrics

## 1. Three books

The agent keeps three separate records. Each one answers a different question.

| Book | Question it answers | Limits |
|---|---|---|
| Exploration | "What happens if we take every signal?" This is the training data. | None. Unlimited trades, no daily stop, no drawdown stop. It never pauses. |
| Paper account (demo) | "What would my money do if every baseline signal were traded?" | $150 start and 2% risk per trade, each position sized down to the free margin at 10x. Since 2026-10-03 there are no position limits and no daily stop (the user's choice). |
| Live | Real money on Binance (Phase 6) | The same entries and exits as the paper account. The limits (max positions, daily loss stop 10–12%) are set in the dashboard before going live. |

**Why losses never slow down training:** the paper account and live trading are separate ledgers on top of the same signals. Limits and pauses there never stop exploration from trading and recording. Goals and failure flags are used to decide things (promotion, go-live). They never stop data collection.

## 2. Metric definitions

| Metric | Formula | Notes |
|---|---|---|
| Net PnL | Gross PnL − fees − slippage − funding | Shown in the dashboard in $ |
| Account % | Net PnL ÷ balance before the trade | Shown in the dashboard |
| R | Net PnL ÷ planned risk ($ distance from entry to stop × size) | Used for learning; leverage does not distort it |
| Win rate | Winning trades ÷ closed trades | |
| Expectancy | Average R per trade (net) | Main learning metric |
| Profit factor | Sum of wins ÷ sum of losses | Above 1 means profitable |
| Max drawdown | Largest drop from a balance peak | Paper and live only |
| Fees paid | Sum of all fees | Shown separately so their cost is visible |
| MFE / MAE | Best / worst move during a trade, in R | Helps tune targets and stops |
| Slippage | Fill price vs expected price | Live vs paper comparison |

**Why R and not the exchange's ROI:** the exchange measures ROI on margin, so it grows with leverage. A 0.5% price move at 10x leverage shows 5% ROI, but the result for your account is the same. R and account % do not change with leverage.

## 3. Fee math (why fees matter in scalping)

Example: $150 account, 2% risk = $3. Stop 0.3% away → position size $3 ÷ 0.3% = **$1,000** (about 7x leverage).

- Round-trip taker fee on Binance: 0.05% × 2 = 0.10% of $1,000 = **$1.00 = 0.33R**
- Target 1.5R: a win is +1.5R − 0.33R = **+1.17R**; a loss is −1R − 0.33R = **−1.33R**
- Breakeven win rate rises from **40%** (no fees) to **53%**

The tighter the stop, the bigger the fee share. With a 0.5% stop, fees are only 0.2R. The agent must learn the smallest stop that stays profitable after fees. Maker (limit) orders cost 0.02% and can reduce this.

## 4. Go-live gate (proposed, editable in Settings)

Live trading can start only when all of these are true. They are counted from the start of the forward test (`paper-reset --from-now`).

| Check | Measured on | Target |
|---|---|---|
| Sample size | The baseline's forward shadow trades (every signal it takes, ~6 a day) | ≥ 100 closed trades and ≥ 14 days |
| Expectancy | Same | ≥ +0.10R per trade |
| Profit factor | Same | ≥ 1.3 |
| Net result | Paper account (live limits) | Net PnL > 0 after all costs |
| Max drawdown | Paper account | ≤ 15% |
| Data quality | ≥ 99% of expected candle snapshots captured in the last 7 days |
| Explainability | Every trade has its indicator snapshot and reason recorded |

When all checks pass, the dashboard shows "Gate met". You still decide. The gate never turns live trading on by itself.

Why the sample is the shadow trades: the paper account takes only about 2 of the ~6 daily signals because of its position limits, so 150 paper trades would take about 70 days. The shadow trades follow the same rules and fills, so they test the strategy faster (decided 2026-10-03: 100 trades in about 16–17 days). The paper account still shows what the money would have done.

The paper account has no limits, so its drawdown is deeper than a limited live account's. On ~100 days of history, v2 with no limits made +59.5% with a 30% max drawdown; with 2 positions and a 10% daily stop it made +19.5% with 17.9%. Before going live, the dashboard will replay the forward trades with the chosen live limits (Phase 4). The 15% drawdown target applies to that replay.

## 5. Research flags (warnings, not brakes)

These never stop anything. They tell Claude where to focus.

| Flag | Trigger |
|---|---|
| Negative edge | A variant's expectancy < 0 after 150 trades |
| Deep drawdown | Paper account drawdown > 30% |
| Fee drag | Fees > 40% of gross profit |
| Data issue | Missed snapshots > 1% in a day |

## 6. Glossary

| Term | Meaning |
|---|---|
| Setup | A rule set: trigger + confirmation + filters + stop + exit |
| Variant | A setup with specific parameter values |
| Baseline | The current best variant; the paper account trades it |
| Challenger | A variant that differs from the baseline in exactly one variable |
| Counterfactual | A signal that was filtered out but is still simulated ("what if we had taken it") |
| HTF | Higher timeframe (1h, 4h) |
| Signal version | A fixed set of indicator settings. Results are compared only within the same version. |
| Snapshot | All indicator values for one coin, timeframe and closed candle |
