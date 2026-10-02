# Phase 2 — Market Data and Shadow Engine

**Goal:** Turn every signal into shadow trades, with real Binance prices and all costs, for many variants in parallel.
**Depends on:** [Phase 1](phase-1-tradingview-reader.md). **Estimated time:** about 1 week, including a 7-day run.

## Build tasks

### Market data (Binance public API, no keys)

1. 1m, 5m and 15m candles for the XRP, LINK and SOL perpetuals: a 35-day backfill plus live updates, closed candles only.
2. Exchange info: tick size, step size, minimum order size.
3. Funding rate history.
4. Gap detection and repair.

### Setup engine

Rules live in `config/setups/*.yaml`, not in code. A setup is: trigger → confirmation → filters → HTF context → stop → exit.

**Baseline V0** (the first hypothesis, based on the Q-Trend + Klinger idea):

| Part | V0 rule |
|---|---|
| Trigger | Q-Trend Buy / Sell arrow (normal or strong) on 5m or 15m |
| Confirmation | Within 3 candles from the trigger (the trigger candle included): Klinger histogram green (long) / red (short) **and** a bullish (long) / bearish (short) candle |
| Filters | None |
| Stop | Lowest low (long) / highest high (short) of the last 10 candles |
| Exit | Fixed take-profit at 1.5R |
| Entry price | The Binance 1m open right after the confirming candle closes, plus slippage |

### Variants (each one changes a single thing from V0)

| # | Variable | Values to test |
|---|---|---|
| 1 | Take-profit | 1.0R, 2.0R |
| 2 | Exit mode | Hybrid: 50% at 1R, stop to break-even, trail the rest |
| 3 | Exit mode | HTF rule: hybrid if 1h/4h confirm, otherwise fixed 1.5R |
| 4 | Confirmation window | 0, 1, 2 candles |
| 5 | VWAP filter | Long only above VWAP, short only below |
| 6 | MACD filter | ATP MACD trend filter (long only when MACD > 0, short only when < 0) |
| 7 | HTF filter | Trade only with the 1h trend / with the 1h + 4h trend |
| 8 | Trigger | Zero Lag trend flip instead of Q-Trend |
| 9 | Trigger | Zero Lag entry arrows (pullbacks inside a trend) |
| 10 | Stop lookback | 5, 20 candles |
| 11 | Minimum stop distance | 0.25% (skip tighter stops because of fees) |

### Shadow simulator

1. Every setup of every variant becomes a shadow trade in the exploration book. There are no limits.
2. Filtered-out signals are also simulated as counterfactuals ("what if we had taken it").
3. Outcomes are tracked on 1m candles. If the stop and the target are both touched inside the same 1m candle, assume the stop was hit first.
4. Costs (all configurable):

   | Cost | Default |
   |---|---|
   | Market entries and stops | Taker fee, 0.05% |
   | Limit take-profits | Maker fee, 0.02% |
   | Slippage | 0.02% on market fills |
   | Funding | Charged if a trade crosses a funding time |

5. Hybrid exit:
   - Close 50% at 1R.
   - Move the stop to break-even plus fees.
   - Trail the rest behind the low (long) / high (short) of the last 3 closed candles.
6. Each trade stores:
   - the indicator snapshot, the signal version, and why it was taken or filtered
   - entry / stop / target, fills and fees
   - net PnL, R, MFE / MAE and duration

### Reliability

- Idempotent processing: a restart never creates duplicate trades.
- Catch-up: after downtime, missed candles are processed in order.
- CLI report: trades and metrics per variant.

## Deliverables

- Market data service
- Setup engine with YAML rules
- Shadow simulator with all variants
- Journal tables filled 24/7

## Exit criteria

- [ ] 7 days of continuous running; ≥ 99% of candles processed
- [ ] 20 random shadow trades checked by hand on TradingView: entry, stop, target and outcome correct
- [ ] Restart test: stop the agent mid-run and start it again. No duplicates, and catch-up works.
- [ ] Fees and slippage match the formulas in [GOALS-AND-METRICS.md](../GOALS-AND-METRICS.md)

## Risks

| Risk | Mitigation |
|---|---|
| Too few signals | Add the Zero Lag entry-arrow trigger, or lower timeframes later |
| Same-candle ambiguity hides real results | 1m resolution; count ambiguous trades in reports |
| Many variants produce a lucky winner | Re-confirmation on fresh data ([Phase 5](phase-5-learning-loop.md)) |
