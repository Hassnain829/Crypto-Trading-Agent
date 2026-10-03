# Phase 4 — Dashboard v1

**Goal:** See and control the agent from a browser.
**Depends on:** [Phase 2](phase-2-shadow-engine.md) (can be built beside Phase 3). **Estimated time:** about 1 week.

## Principles

- Python only: NiceGUI (runs on FastAPI). All UI text in English.
- Runs as a separate process from the agent. If the dashboard stops, trading does not.
- Every number comes from the journal. The UI calculates nothing on its own.
- No login (personal use).
  - It listens on `127.0.0.1:8080` by default; open it in a browser on the VPS.
  - Binding to `0.0.0.0` makes it reachable from your PC or phone, but with no password anyone who finds the address can open it.
- No TradingView charts (TradingView Essential covers that). Simple line charts for equity and metrics only.
- No notifications for now.

## Pages

### Overview

- Mode badge: SHADOW / LIVE
- Paper account balance; today's net PnL ($ and %)
- Daily loss stop usage bar (for example "4.2% of 10%")
- Open positions (paper now, live later)
- Exploration today: snapshots read, shadow trades opened and closed
- System health:
  - TradingView MCP status and the last snapshot age per chart
  - Binance API status
  - Last candle processed
  - Last research run
- Kill switch

### Trades

- Tabs: Exploration, Paper, Live
- Filters: coin, timeframe, variant, setup, result, date range, taken vs counterfactual
- Trade details:
  - entry, stop, target, exit, fees
  - net PnL, R, MFE / MAE, duration
  - indicator snapshot at the signal (all 5 indicators plus the HTF state)
  - why the trade was taken or filtered
  - signal version

### Performance

- KPI cards: net PnL, account %, win rate, expectancy, profit factor, max drawdown, fees paid
- Tables by variant, coin, timeframe, hour of day, HTF aligned vs not, and exit mode
- Equity curve (paper now, live later)
- Go-live gate checklist with progress

### Learning

- Current baseline and its parameters
- Active challengers with progress (trades so far / trades needed)
- Experiment timeline: hypothesis → result → decision → lesson
- Lessons (research memory)
- Latest research pack and proposals
- "Approve for live" button (active in Phase 6)

### Settings

| Section | Fields |
|---|---|
| Account | Paper starting balance |
| Risk | Risk %, leverage cap. Demo: no limits by default. Live: max positions, per coin, daily loss stop % (set before going live). |
| Markets | Coins on/off, timeframes on/off |
| Setups | Baseline parameters (an edit creates a new variant version) |
| Costs | Maker fee, taker fee, slippage |
| Exchange connection | Paste a Binance API key and secret, then "Test connection" (a read-only call). Saved to the local `.env` and shown masked afterwards. Keys can also be written to `.env` directly. |
| TradingView | MCP server path, debug port, tab mapping |
| Research | Daily research time, on/off |
| Goal | Go-live gate thresholds |

Every change is written to an audit log (time, field, old → new).

**Live preview** (added 2026-10-03): when live limits are edited, the dashboard shows a replay of the forward baseline trades through those limits. It shows the result, the drawdown, trades per day and skipped signals, and the go-live gate's money checks use this replay.

### System

- Logs with a level filter
- Watchdog events and restarts
- Missed snapshots and data gaps
- Indicator settings changes
- CPU and RAM usage

## Deliverables

- Dashboard with all six pages
- Settings service with an audit log
- Windows service / startup task for the dashboard

## Exit criteria

- [ ] All pages show live data and refresh every few seconds
- [ ] Settings changes take effect without restarting the agent and appear in the audit log
- [ ] API key paste and "Test connection" work; the key is never shown in full again
- [ ] The kill switch pauses the paper account
- [ ] The dashboard runs as a service on the VPS and restarts on crash
