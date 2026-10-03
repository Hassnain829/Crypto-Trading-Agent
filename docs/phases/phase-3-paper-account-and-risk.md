# Phase 3 — Paper Account and Risk Engine

**Goal:** A live-like account that follows the live rules exactly, so we know what real trading would look like.
**Depends on:** [Phase 2](phase-2-shadow-engine.md). **Estimated time:** 3–5 days.

> **Status (2026-10-02): built; the 7-day run is next.** It is the same `agent` run as for Phases 1 and 2.
> - 14 unit tests pass. They cover sizing, rounding, minimum order size, the leverage cap, free margin, position caps, conflicts, the daily stop, the kill switch, event order, restarts, late signals and baseline changes.
> - Replay over the history: of 142 baseline signals, 39 were opened and 103 were skipped by the position limits.
> - Result: balance $150.00 → $141.98 (−5.35%), 38 closed trades, −0.061R per trade, profit factor 0.89, max drawdown 11.4%, fees $7.50.
> - Consistency: all 39 paper trades match their exploration trades (same exit, same R).

## Rules (defaults, all editable in Settings)

> **Since 2026-10-03 the paper account has no trade limits.** `max_positions`, `max_positions_per_coin` and `daily_loss_stop` are `null`, so it takes every baseline signal. The user wants as many demo trades as possible. The limits below stay in the code and are set for live trading in the dashboard.

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

Until the dashboard exists (Phase 4), the rules are in `config/settings.yaml` under `paper_account`. To change them: stop the agent, edit the file, run `paper-reset --yes`, and start the agent again. Its first cycle replays the history with the new rules.

## Build tasks

1. **Broker interface.** `PaperBroker` now and `BinanceBroker` in Phase 6, with the same interface, so paper and live share one code path.
2. **Account ledger.** Balance, open positions, realized and unrealized PnL, fees.
3. **Position sizing.** Risk ÷ stop distance, then the leverage cap, then exchange rounding.
4. **Risk engine.** Position caps, daily loss stop, conflict rules.
5. **Kill switch.** Pause new entries or close everything (paper mode now, live later).
6. **Unit tests** for every rule.

## How it works (as built)

| Part | Implementation |
|---|---|
| Which trades | The baseline's taken exploration trades. A paper position uses the same fills, fees, slippage and funding, so its R equals the exploration R. |
| Event order | Signals are handled in entry-time order. Before each entry, positions that closed earlier are settled first. The balance, the open positions and the daily stop are then exactly what they were at that moment. |
| Sizing (`account/rules.py`) | 1. 2% of the current balance ÷ the stop distance. 2. Capped at 10x the balance. 3. Capped at 10x the free margin (isolated margin). 4. Rounded down to Binance's step size. 5. Skipped if below the minimum order: 20 USDT for LINK, 5 USDT for XRP and SOL. |
| Caps and conflicts | Max 2 positions, 1 per coin. The first signal wins, also between 5m and 15m. No opposite trade while a coin has a position. |
| Daily loss stop | Triggers at 10% of the day's starting balance, counting realized losses. It blocks new entries until 00:00 UTC; open positions keep running. Exploration never stops. |
| Kill switch (`account/kill_switch.py`) | Three modes. `off`: normal trading. `pause`: no new entries. `close_all`: close every position at the last 1m price (slippage and taker fee included), then switch to `pause`. The mode is stored in the journal's settings with an audit trail, so the dashboard can use it later. |
| Broker interface (`account/broker.py`) | `entry_fill`, `exit_report` and `close_now`. `PaperBroker` now; `BinanceBroker` in Phase 6 implements the same three calls. |
| Limit entries | When the baseline uses limit entries (v2), the paper position pays the maker fee and no entry slippage, exactly like the exploration trade it follows |
| Every decision stored | `account_trades` stores every signal, opened or rejected with the reason. It also stores size, leverage, risk, PnL in USDT, fees, funding, R and account %. |
| Late signal | A signal that arrives after a later signal was already handled is stored as rejected, not traded |
| New baseline | Followed from its promotion on. Its earlier trades stay in the exploration history. |
| Open positions | `paper-report` values them at the last 1m close, exit costs included (equity) |
| In the agent | Runs after the tracker in every cycle; the log line shows paper opened / rejected / settled |
| Trades on the chart (`tv/drawings.py`) | Each paper trade is drawn on the AGENT chart its signal came from, as a locked long/short position tool. It shows entry, stop, target, the account size and 2% risk. When the trade closes it is redrawn with its real length and a label such as `TP +1.49R (+5.18$)`. Drawings are synced globally, so they also appear in another layout (for example Market_check) when it shows that coin. Drawing ids are kept in `trade_drawings`; switch it off with `tradingview.draw_trades: false`. |
| Journal | Migrations 4–6: `account_state`, `account_trades`, `trade_drawings` |

## Commands

| Command | Use |
|---|---|
| `python -m tradeagent paper-report` | Shows the account and its checks: balance and equity, open positions, skipped signals by reason, the consistency check and the go-live gate |
| `python -m tradeagent kill-switch` | Show the kill switch. Change it with `kill-switch pause`, `kill-switch close_all` or `kill-switch off`. The agent applies it in its next cycle. |
| `python -m tradeagent paper-reset --yes` | Delete the paper account history. The next `shadow-run` or agent cycle replays it with the current rules. |
| `python -m tradeagent draw-trades` | Draw any paper trades that are not on the charts yet (the agent does this every cycle). `--clear` removes every drawing the agent made. |
| `python -m tradeagent paper-reset --yes --from-now` | Start a fresh forward test: $150 again, only signals from now on. Used on 2026-10-03 to start the forward run with baseline v2. |

## Deliverables

- Paper account running beside the exploration book
- Risk engine with tests
- Broker interface ready for live trading

## Exit criteria

- [x] All risk-rule tests pass: daily stop, caps, rounding, leverage cap, conflicts (`tests/test_account.py`, 14 tests)
- [ ] 7 days running beside exploration
- [x] Every paper trade also exists in the exploration book for the same variant. `paper-report` checks this on every run; on the history, 39/39 matched.
- [x] When the daily stop hits, only the paper account pauses and exploration keeps trading. A test verifies this, and the account never writes to the exploration book.

## Changes from the original plan

- A second position that does not fit the free margin is made smaller instead of being skipped. This follows the rule "if a trade needs more leverage, its size is reduced".
- The daily loss stop counts realized losses only and does not close open positions.
- Hybrid partial exits are booked when the whole trade closes, so the balance updates at the final exit. The current baseline uses a fixed exit.
- Unrealized PnL is calculated for the report and not stored.

## First observation

Most baseline signals (103 of 142) were skipped because positions were already open. The median baseline trade lasts 3.4 hours, but 30 of 135 lasted over 12 hours, up to the 72-hour limit. With max 2 positions, long trades block new ones.

This is a topic for Phase 5: test a shorter time limit or a tighter stop as one-change variants.

## Risks

| Risk | Mitigation |
|---|---|
| Paper results look better than live will be | Conservative fill rules; live slippage tracking in Phase 6 |
| Paper and exploration drift apart | Same fills by design; `paper-report` checks every trade's exit and R |
