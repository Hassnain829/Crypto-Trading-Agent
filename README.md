# Crypt-AI-Trading

A self-improving crypto scalping agent. It reads signals from TradingView indicators, practices on shadow (paper) trades, learns from the results one change at a time, and later trades live on Binance with small capital.

> **Status (2026-10-02):** Phase 0 (foundation) complete. Next: Phase 1, the TradingView signal reader.

## Quick start (Windows, PowerShell)

```powershell
# 1. Python environment (first time only)
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt -e .

# 2. Secrets (only needed from Phase 6)
Copy-Item .env.example .env

# 3. Start TradingView Desktop with the debug port the agent reads through
powershell -ExecutionPolicy Bypass -File scripts\launch_tradingview_debug.ps1

# 4. Check that everything is installed and connected
.venv\Scripts\python -m tradeagent doctor

# Tests (add -m network to include the Binance test)
.venv\Scripts\python -m pytest
```

## How it works

1. TradingView Desktop shows five indicators (Q-Trend, Klinger, VWAP, Zero Lag, ATP MACD) on Binance perpetual charts.
2. The agent reads every **closed** candle through the TradingView MCP.
3. Python turns those readings into setups and simulates shadow trades with real Binance prices, fees included.
4. Claude (Pro plan) reviews the journal, forms a hypothesis, and proposes one change at a time.
5. Changes that hold up on fresh data become the new baseline.
6. Live trading starts only after the go-live gate is met **and** you approve it.

## Key facts

| Item | Decision |
|---|---|
| Exchange | Binance USDT-M perpetual futures |
| Coins | XRP, LINK, SOL |
| Timeframes | Trade on 5m and 15m; overview on 1h and 4h |
| Signals | TradingView Essential + MCP (no webhook alerts) |
| Indicators in Python | None. Python only reads TradingView. |
| Shadow trading | Unlimited exploration + a live-like paper account |
| Live start | $100–150, 2% risk per trade, max 2 positions, daily loss stop 10–12% |
| Dashboard | Python (NiceGUI), English UI |

## Documents

| Document | What it covers |
|---|---|
| [docs/ROADMAP.md](docs/ROADMAP.md) | All phases, their order, dependencies and timeline |
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | Every agreed decision, what is out of scope, decision log |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, data flow, processes on the VPS, tech stack |
| [docs/GOALS-AND-METRICS.md](docs/GOALS-AND-METRICS.md) | The three books, metrics, fee math, go-live gate |
| [docs/TRADINGVIEW-SETUP.md](docs/TRADINGVIEW-SETUP.md) | Verified layouts, templates and indicator settings (Signal Version 1) |
| [docs/phases/](docs/phases/) | One file per phase: tasks, deliverables, exit criteria, risks |
