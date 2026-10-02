# Phase 6 — Live Trading

**Goal:** Trade the baseline on Binance with small capital, with every safety rule active.
**Starts only when:** the go-live gate is met ([GOALS-AND-METRICS.md](../GOALS-AND-METRICS.md)) **and** you approve it in the dashboard.
**Estimated time:** 2–4 weeks of closely monitored trading.

## Your tasks before starting

1. Create a Binance API key:
   - Futures trading enabled only
   - Withdrawals disabled
   - IP whitelist: the VPS IP only
2. Put the key in `.env`, or paste it in Settings → Exchange connection.
3. Fund the futures wallet with $100–150.

## Build tasks

1. **BinanceBroker** (ccxt, USDT-M): isolated margin and leverage per symbol.
2. **Protected entries.** The entry order is followed immediately by the stop-loss and take-profit as reduce-only orders on Binance. If the protective stop cannot be placed, the position is closed at once.
3. **Hybrid exit management.** Partial close at 1R, stop moved to break-even, trailing stop updates.
4. **Unique client order IDs**, so retries never create double orders.
5. **Reconciliation** at startup and every cycle:
   - compare Binance positions and orders with the journal
   - cancel orphan orders
   - make sure every position has a stop
6. **Error handling:** rate limits, rejections, partial fills, network failures.
7. **Safety rails:**
   - daily loss stop (10–12%), max 2 positions, leverage cap
   - no new entries if TradingView snapshots are late or Binance data has gaps
   - kill switch: cancel all orders and close all positions
   - switching to live needs an explicit confirmation in the dashboard
8. **Slippage tracking:** live fill vs paper fill for the same signal.

## Rollout

- 2% risk, $100–150
- Shadow exploration and the paper account keep running beside live
- Daily review for the first 2 weeks

## Exit criteria

- [ ] 2 weeks live with no operational errors
- [ ] Every live trade reconciled with Binance
- [ ] Average live slippage ≤ 2 × the paper assumption
- [ ] Live results within the expected range of the paper account

## Risks

| Risk | Mitigation |
|---|---|
| The agent or VPS goes down with an open position | Stop-loss and take-profit already sit on Binance |
| An exchange API change | ccxt updates; reconciliation detects mismatches |
| Larger losses than on paper | Daily stop, kill switch, small capital |
