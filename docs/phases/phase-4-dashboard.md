# Phase 4 — Dashboard v1

**Goal:** See and control the agent from a browser.
**Depends on:** [Phase 2](phase-2-shadow-engine.md) (can be built beside Phase 3). **Estimated time:** about 1 week.

> **Status (2026-10-03): built.** Start it with `python -m tradeagent dashboard`; it opens http://127.0.0.1:8080.
> - All six pages work in dark and light mode.
> - Settings save to the journal with an audit log. Fields marked "next cycle" apply without restarting the agent.
> - API keys can be pasted for Binance, Bitget and MEXC.
> - The live preview replays trades through the live limits.
> - 100 tests pass.
> - What remains: install it as a startup task on the VPS (the scripts are ready).

## As built

| Part | Implementation |
|---|---|
| App | `src/tradeagent/dashboard/` (NiceGUI 3.17). `app.py` builds the header, the navigation and client-side routes. Each page has its own module under `pages/`. |
| Data | `dashboard/data.py` reads everything from the journal over its own connection (WAL); the UI does no math of its own. It writes only settings, the kill switch and the audit log. |
| Agent status | The agent writes a heartbeat to `agent_status` after every cycle (migration 8). The header shows Running / Starting / Stalled / Stopped from it and the process id. |
| Agent control | `supervisor.py`: the dashboard starts the agent as its own background process (so trading continues if the dashboard closes) and starts it again after a crash, at most once a minute. Start / Stop / Restart on the Overview; Resume on the kill switch also starts it. A stopped agent stays stopped until Start, also after a dashboard restart (state `agent_wanted` in the journal). Stop is a request the agent sees within 3 s; it finishes its step first and is ended after 90 s if it does not stop. Only one agent runs: it holds `data/agent.lock`. The agent opens TradingView in debug mode itself. `dashboard --no-agent` turns the automatic start off. |
| Time zone | Setting `tradingview.timezone` (Settings > TradingView): "Same as this computer" (default) or a fixed zone. The agent sets the time axis of every AGENT chart to it (never the user's own layout) and the dashboard shows times in it; daily figures stay on UTC days, as the demo account's day does. Display only: candles, signals and stored times (UTC) do not change. The agent uses Binance's server time for every read, so a VPS clock that is off does not matter; the Overview shows the difference. |
| Settings | `settings_store.py`: overrides of settings.yaml saved in the journal's `settings` table and validated with the same models. Every change goes to `settings_audit`. The agent re-applies them at the start of every cycle. Costs apply on restart. |
| Live limits | New `live_account` section: exchange, balance, risk, positions, per coin, daily stop, leverage. `account/preview.py` replays the baseline's shadow trades through them in memory. The go-live gate's money checks use this replay. |
| Exchanges | `exchanges.py` lists what each exchange needs: Binance key + secret; Bitget key + secret + passphrase; MEXC access key + secret. Keys are saved to `.env`, shown masked, and checked with a read-only balance call. |
| Strategy versions | `baseline_history` (migration 8) records each baseline: v0, v1, v2 with their evidence. The Learning page charts them. |
| Charts | ECharts with the data-viz palette: one axis per chart, thin lines, hover tooltips, profit and loss with a sign (not color alone). Empty charts show a message until there is data. |
| Startup | `scripts/run_forever.ps1` restarts a command after a crash. `scripts/install_startup_tasks.ps1` registers the dashboard as a logon task; the dashboard runs the agent. |

## Pages as built

| Page | What it shows |
|---|---|
| Overview | KPI tiles (demo balance, today, open positions, strategy edge, go-live readiness), demo equity, agent status, open positions, today's counts, kill switch, activity feed, data-feed freshness |
| Trades | Demo account and shadow book tabs with filters. Each trade opens a detail view: price chart with entry/stop/target, indicator values of all 5 indicators, HTF state, filters, the variant's rules, exit legs. It is also a page: `/trade/<id>`. |
| Performance | Demo KPIs, equity, drawdown and daily PnL. Strategy stats with a 95% range and cumulative R. Result histogram, breakdowns (variant, coin, timeframe, side, hour, 1h/4h trend, exit). Go-live gate with progress bars. |
| Learning | How the agent learns (with live counts), strategy versions chart and history, current rules in plain English. Strength scorecard: edge, consistency, data quality, reliability, risk. Challengers with verdicts, research notes, decision log, lessons. "Approve for live" (Phase 6). |
| Settings | Demo account, live limits with live preview, exchanges, costs, go-live gate, strategy rules editor (validated, backed up), markets, TradingView, research, audit log. Each section has a link: `/settings/<section>`. |
| System | Agent log (level filter, search, newest first), events, TradingView coverage and Binance gaps, RAM and TradingView memory, indicator settings versions |

## How to use

```powershell
.venv\Scripts\python -m tradeagent dashboard              # opens the browser, starts the agent (and TradingView)
.venv\Scripts\python -m tradeagent dashboard --no-browser # e.g. as a service
.venv\Scripts\python -m tradeagent dashboard --no-agent   # do not start the agent automatically
# Start the dashboard (and so the agent) at every logon, restarted after a crash (run once):
powershell -ExecutionPolicy Bypass -File scripts\install_startup_tasks.ps1
```

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

- [x] All pages show live data and refresh every few seconds: Overview every 5 s, the others every 5–30 s.
- [x] Settings changes take effect without restarting the agent and appear in the audit log. Fields marked "on restart" (costs, starting balance) apply when the agent starts.
- [x] API key paste and "Test connection" work for Binance, Bitget and MEXC; the key is never shown in full again. A test with real keys needs your keys.
- [x] The kill switch pauses the paper account (Overview > Kill switch, the same setting as `kill-switch pause`).
- [ ] The dashboard runs as a service on the VPS and restarts on crash. The scripts are ready; install them on the VPS.
