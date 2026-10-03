# Phase 2 — Market Data and Shadow Engine

**Goal:** Turn every signal into shadow trades, with real Binance prices and all costs, for many variants in parallel.
**Depends on:** [Phase 1](phase-1-tradingview-reader.md). **Estimated time:** about 1 week, including a 7-day run.

> **Status (2026-10-02): built; the 7-day run is next.**
> - Stored candles match Binance exactly.
> - `verify-trades`: 20 of 20 random trades match an independent re-computation from raw candles.
> - Restart test passed: replaying the history gave the same 2,433 trades with 0 duplicates. A second run added nothing.
> - The full agent ran a live cycle: snapshots read, shadow step done, no errors.
> - What remains: the 7-day run. One `agent` run covers it, together with the Phase 1 48-hour test and the Phase 3 run.

## Build tasks

### Market data (Binance public API, no keys)

1. 1m, 5m and 15m candles for the XRP, LINK and SOL perpetuals: a 35-day backfill plus live updates, closed candles only.
2. Exchange info: tick size, step size, minimum order size.
3. Funding rate history.
4. Gap detection and repair.

### Setup engine

Rules live in `config/setups.yaml`, not in code. A setup is: trigger → confirmation → filters → HTF context → stop → exit.

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

## How it works (as built)

| Part | Implementation |
|---|---|
| Market data | `market/candles.py`: closed 1m/5m/15m candles, 35 days back, then only new ones. Gaps are found and repaired. Funding rates are stored too. Market info (tick size, step size, minimum order) is refreshed every hour. |
| Server clock | `market/clock.py` measures the offset to Binance server time; candle closes are scheduled in server time |
| Setup rules | `config/setups.yaml`: the baseline and 16 variants. A variant's id is its name plus a hash of its rules, so a rule change gets a new id automatically. Signal flags are checked against the catalog at start. |
| Setup engine | `setups/engine.py` processes each coin and timeframe in candle order, one transaction per candle. `engine_state` remembers where it stopped. |
| Entry timing | The engine waits until the Binance 1m entry candle has closed, so a trade is recorded one cycle after its signal. Its entry time and price stay correct. |
| HTF context | Zero Lag trend of the newest closed 1h / 4h snapshot. Missing or stale data counts as no trend. |
| Simulator | `sim/simulator.py`, pure logic: the rules above, plus a gap through the stop fills at the candle's open, and a 72-hour time limit |
| Tracker | `sim/tracker.py` moves open trades forward on new 1m candles, 500 candles at a time |
| Counterfactuals | Signals that a variant's filters reject are simulated with `taken = 0` |
| History | `backfill-snapshots` stored snapshots for the history already loaded in TradingView (`source = backfill`). A live read replaces a backfilled row. Coverage counts only live reads. |
| Independent check | `verify-trades` re-computes random closed trades from raw candles with separate code |
| Journal | Migration 3: `candles`, `funding`, `market_info`, `variants`, `setups`, `trades`, `engine_state` |

## Commands

| Command | Use |
|---|---|
| `python -m tradeagent agent` | Run everything 24/7: reader, Binance data, setup engine, tracker and paper account (Ctrl+C to stop) |
| `python -m tradeagent market-sync` | Sync Binance candles, funding and market info now |
| `python -m tradeagent backfill-snapshots --bars 10000` | Load that much history on every chart (Essential allows 10,000 bars) and store its snapshots; without `--bars`, only what is loaded. TradingView must run in debug mode, and the agent must be stopped, because this switches the HTF chart. |
| `python -m tradeagent shadow-run` | Process new snapshots and move open trades forward once. Not needed while the agent runs, because it does this every cycle. |
| `python -m tradeagent shadow-report --halves` | Results per variant: closed, taken trades; R after fees, slippage and funding; counterfactuals. `--halves` adds each half of the history, to see whether a result holds over time. |
| `python -m tradeagent trades --variant v0 --last 20` | List trades. `--id N` shows one trade in detail. |
| `python -m tradeagent verify-trades --count 20` | Re-compute random closed trades independently |
| `python -m tradeagent shadow-reset --yes` | Delete exploration trades, and the paper account that follows them, so the history can be replayed |

## Strategy review (2026-10-03)

The history was extended to 10,000 bars per chart, and more than 20 variants and two other strategy families were tested over ~100 days. See [the review](../research/2026-10-03-strategy-review.md). In short:
- The video's rules lose 0.16R per trade after costs.
- Baseline v2 (stops of at least 1.5%, limit-order entries) made +0.12R per trade and was positive in all four sub-periods.
- The paper account went $150 → $179 on that history. A fresh forward run decides next.
- New engine options: limit entries (unfilled ones are stored as `missed`), session filter, own-chart trend filter, counter-4h filter, moved stops, break-even, opposite-signal exit, time stop, and ATP MACD triggers.

## First results (history backfill, 2026-09-19 to 10-02)

The sample is small, so these are not conclusions yet.

- **Baseline v0:** 135 closed trades, 40% wins, −0.115R per trade, profit factor 0.83. Fees cost 0.08R per trade.
- **Best:** `stop_20` (−0.061R) and `confirm_0` (−0.094R).
- **Worst:** `trigger_zl_entry` (−0.317R) and `tp_2r` (−0.221R).
- **VWAP filter:** the signals it rejected averaged +0.104R (24 trades), so it removed winners.
- **Overall:** no variant is positive yet. Phase 5 decides with more data and re-confirmation on fresh data.

## Exit criteria

- [ ] 7 days of continuous running; ≥ 99% of candles processed
- [x] 20 random shadow trades checked. `verify-trades`: 20/20. An independent re-computation from raw candles replaced the hand check on TradingView. Candles match Binance exactly.
- [x] Restart test: the same 2,433 trades after a replay, 0 duplicates, and catch-up works
- [x] Fees and slippage match the formulas in [GOALS-AND-METRICS.md](../GOALS-AND-METRICS.md) (unit tests in `tests/test_simulator.py`)

## Changes from the original plan

- The rules are in one file, `config/setups.yaml`, instead of `config/setups/*.yaml`.
- The 11 variables became 16 variants, one per tested value.
- The history was backfilled from TradingView's loaded bars, so the first results came before the 7-day run.
- A trade is recorded once its 1m entry candle has closed, normally in the next cycle. The simulated entry time and price do not change.
- An independent re-computation (`verify-trades`) and the candle check against Binance replaced the hand check on TradingView.

## Risks

| Risk | Mitigation |
|---|---|
| Too few signals | Add the Zero Lag entry-arrow trigger, or lower timeframes later |
| Same-candle ambiguity hides real results | 1m resolution; count ambiguous trades in reports |
| Many variants produce a lucky winner | Re-confirmation on fresh data ([Phase 5](phase-5-learning-loop.md)) |
| Backfilled snapshots differ from live reads (repainting) | Live reads replace them; `repaint-audit` checks stored values; coverage counts only live reads |
