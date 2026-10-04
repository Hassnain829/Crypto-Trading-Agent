# Phase 6 — Live Trading

**Goal:** Trade the baseline on the trading venue (`exchange.venue`; the user plans Coinbase or Kraken with US KYC) with small capital, with every safety rule active.
**Starts only when:** the go-live gate is met ([GOALS-AND-METRICS.md](../GOALS-AND-METRICS.md)) **and** you approve it in the dashboard.
**Estimated time:** 2–4 weeks of closely monitored trading.

> **2026-10-04, Phase 4.5:** live orders go to the same venue the demo is filled on.
> - **Coinbase US** has XRP, SOL and LINK and an API, but its contracts are large: 500 XRP, 5 SOL and 50 LINK, about $600–740 each. At 2% risk the account needs roughly $900–1,200 so that one contract fits the risk.
> - **Kraken US** has small contracts (100 XRP, 1 SOL, 10 LINK) but no public trading API was found. Ask Kraken support whether Kraken Derivatives US offers API access.

## Your tasks before starting

1. Create an API key on the venue (Settings → Exchanges shows the steps):
   - read + futures trading only
   - withdrawals / transfers disabled
   - IP allow-list: the VPS IP only
2. Paste it in Settings → Exchanges (it is saved to `.env`, never committed).
3. Fund the futures account with the balance the go-live gate was checked with.

## Build tasks

1. **Venue broker** (ccxt, one implementation with per-venue details): margin mode and leverage per symbol where the venue has them, whole contracts, the venue's order types.
2. **Same entries as the paper account.** The live account must trade exactly what was tested:
   - same signals and sizing
   - same stop and target
   - the same entry type: since baseline v2 (2026-10-03), a post-only limit order at the entry price that is cancelled if it is not filled within the first minute
3. **Protected entries.** The entry order is followed immediately by the stop-loss and take-profit as reduce-only orders on the venue. If the protective stop cannot be placed, the position is closed at once.
4. **Hybrid exit management.** Partial close at 1R, stop moved to break-even, trailing stop updates.
5. **Unique client order IDs**, so retries never create double orders.
6. **Reconciliation** at startup and every cycle:
   - compare the venue's positions and orders with the journal
   - cancel orphan orders
   - make sure every position has a stop
7. **Error handling:** rate limits, rejections, partial fills, network failures.
8. **Safety rails:**
   - daily loss stop (10–12%), max 2 positions, leverage cap
   - no new entries if TradingView snapshots are late or the venue's data has gaps
   - kill switch: cancel all orders and close all positions
   - switching to live needs an explicit confirmation in the dashboard
9. **Slippage and fill tracking:**
   - live fill vs paper fill for the same signal
   - live limit fill rate vs the simulated rate (about 86–93% in the first minute)

## Rollout

- 2% risk, $100–150
- Shadow exploration and the paper account keep running beside live
- Daily review for the first 2 weeks

## Exit criteria

- [ ] 2 weeks live with no operational errors
- [ ] Every live trade reconciled with the venue
- [ ] Average live slippage ≤ 2 × the paper assumption
- [ ] Live results within the expected range of the paper account

## Risks

| Risk | Mitigation |
|---|---|
| The agent or VPS goes down with an open position | Stop-loss and take-profit already sit on Binance |
| An exchange API change | ccxt updates; reconciliation detects mismatches |
| Larger losses than on paper | Daily stop, kill switch, small capital |
