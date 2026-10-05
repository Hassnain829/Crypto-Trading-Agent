# Crypt-AI-Trading

A self-improving crypto scalping agent. It reads signals from TradingView indicators, practices on shadow (paper) trades, learns from the results one change at a time, and later trades live on Binance with small capital.

> **Status (2026-10-04):** Phase 0 complete. Phases 1–5 are built: the TradingView signal reader, the shadow engine, the paper account, the dashboard (http://127.0.0.1:8080), the exchange adapter and the learning loop.
> Strategy v3.1: the v2 rules (stops of at least 1.5%, limit-order entries) on XRP, SOL and ETH, +0.24R per trade on ~100 days of history ([research](docs/research/2026-10-04-v3-coins.md)).
> The demo account's forward test started on 2026-10-04 at $150. Claude's experiments are judged automatically (Learning page).

## Quick start (Windows, PowerShell)

```powershell
# 1. Python environment (first time only)
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt -e .

# 2. Secrets (only needed from Phase 6)
Copy-Item .env.example .env

# 3. Check that everything is installed and connected
.venv\Scripts\python -m tradeagent doctor

# 4. Start everything: the dashboard (http://127.0.0.1:8080) starts the agent, and the agent opens
#    TradingView Desktop in debug mode. The dashboard restarts the agent after a crash; Overview > Agent
#    has Start / Stop / Restart. (`tradeagent agent` alone runs the agent without the dashboard.)
.venv\Scripts\python -m tradeagent dashboard

# 5. Optional: start the dashboard (and so the agent) at every logon
powershell -ExecutionPolicy Bypass -File scripts\install_startup_tasks.ps1

# 6. Trading venues: who may use them, fees, and the strategy replayed on another venue's prices
.venv\Scripts\python -m tradeagent venues
.venv\Scripts\python -m tradeagent venue-replay coinbase-us --balance 1000

# 7. Results in the terminal
.venv\Scripts\python -m tradeagent shadow-report   # every variant in the exploration book
.venv\Scripts\python -m tradeagent paper-report    # paper account and the go-live gate

# Tests (add -m network to include the Binance test)
.venv\Scripts\python -m pytest
```

Other commands:

- Reader: `reader`, `snapshot`, `tv-status`, `show`, `verify-candles`, `coverage`, `repaint-audit`. See [Phase 1](docs/phases/phase-1-tradingview-reader.md#commands).
- Shadow engine: `market-sync`, `backfill-snapshots --bars 10000`, `shadow-run`, `shadow-report --halves`, `trades`, `verify-trades`, `shadow-reset`. See [Phase 2](docs/phases/phase-2-shadow-engine.md#commands).
- Paper account: `paper-report`, `kill-switch`, `paper-reset`. See [Phase 3](docs/phases/phase-3-paper-account-and-risk.md#commands).
- Learning loop: `research-pack`, `experiment list | propose | try | screen | evaluate | stop | lesson | promote`, and `/research` in Claude Code. See [Phase 5](docs/phases/phase-5-learning-loop.md#as-built-2026-10-04).

## How it works

1. TradingView Desktop shows five indicators (Q-Trend, Klinger, VWAP, Zero Lag, ATP MACD) on Binance perpetual charts.
2. The agent reads every **closed** candle over the Chrome DevTools Protocol (CDP).
3. Python turns those readings into setups and simulates shadow trades with real Binance prices, fees included.
4. A paper account follows the baseline's trades under the live rules ($150, 2% risk, max 2 positions, daily loss stop).
5. Claude (Pro plan) reads a daily research pack and proposes one rule change at a time.
6. A proposal must beat the baseline on the history, then on forward trades, then again on fresh trades; only then does it become the demo's new baseline.
7. Live trading starts only after the go-live gate is met **and** you approve it.

## Key facts

| Item | Decision |
|---|---|
| Exchange | Binance USDT-M perpetual futures |
| Coins | XRP, SOL, ETH (strategy v3.1, 2026-10-04; LINK was dropped) |
| Timeframes | Trade on 5m and 15m; overview on 1h and 4h |
| Signals | TradingView Essential, read over CDP (no webhook alerts) |
| Indicators in Python | None. Python only reads TradingView. |
| Shadow trading | Unlimited exploration + a live-like paper account |
| Live start | $100–150, 2% risk per trade, max 2 positions, daily loss stop 10–12% |
| Dashboard | Python (NiceGUI),  |

## Documents

| Document | What it covers |
|---|---|
| [docs/ROADMAP.md](docs/ROADMAP.md) | All phases, their order, dependencies and timeline |
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | Every agreed decision, what is out of scope, decision log |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, data flow, processes on the VPS, tech stack |
| [docs/GOALS-AND-METRICS.md](docs/GOALS-AND-METRICS.md) | The three books, metrics, fee math, go-live gate |
| [docs/TRADINGVIEW-SETUP.md](docs/TRADINGVIEW-SETUP.md) | Verified layouts, templates and indicator settings (Signal Version 1) |
| [docs/phases/](docs/phases/) | One file per phase: tasks, deliverables, exit criteria, risks |
