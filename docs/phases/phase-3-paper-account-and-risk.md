# Phase 3 — Paper Account and Risk Engine

**Goal:** A live-like account that follows the live rules exactly, so we know what real trading would look like.
**Depends on:** [Phase 2](phase-2-shadow-engine.md). **Estimated time:** 3–5 days.

## Rules (defaults, all editable in Settings)

| Rule | Default |
|---|---|
| Starting balance | $150 |
| Risk per trade | 2% of the current balance |
| Max open positions | 2 total, 1 per coin |
| Daily loss stop | 10% of the day's starting balance (range 10–12%); resets at 00:00 UTC |
| Leverage cap | 10x, isolated margin. If a trade needs more, its size is reduced. |
| Which trades | Only the current baseline variant |
| Conflicts | If 5m and 15m signal the same coin, the first signal wins. No opposite trade while a position is open. |
| Order sizes | Rounded to Binance's step size. Trades below the minimum order size are skipped and logged. |

## Build tasks

1. **Broker interface.** `PaperBroker` now and `BinanceBroker` in Phase 6, with the same interface, so paper and live share one code path.
2. **Account ledger.** Balance, open positions, realized and unrealized PnL, fees.
3. **Position sizing.** Risk ÷ stop distance, then the leverage cap, then exchange rounding.
4. **Risk engine.** Position caps, daily loss stop, conflict rules.
5. **Kill switch.** Pause new entries or close everything (paper mode now, live later).
6. **Unit tests** for every rule.

## Deliverables

- Paper account running beside the exploration book
- Risk engine with tests
- Broker interface ready for live trading

## Exit criteria

- [ ] All risk-rule tests pass: daily stop, caps, rounding, leverage cap, conflicts
- [ ] 7 days running beside exploration
- [ ] Every paper trade also exists in the exploration book for the same variant (consistency check)
- [ ] When the daily stop hits, only the paper account pauses; exploration keeps trading

## Risks

| Risk | Mitigation |
|---|---|
| Paper results look better than live will be | Conservative fill rules; live slippage tracking in Phase 6 |
