# Crypt-AI-Trading

A self-improving crypto scalping agent. It reads signals from TradingView indicators, practices on shadow (paper) trades, learns from the results one change at a time, and later trades live on Binance with small capital.

> **Status (2026-10-03):** Phase 0 complete. Phases 1–3 are built: the TradingView signal reader, the shadow engine and the paper account.
> A strategy review replaced the video's rules (−0.16R per trade over ~100 days) with baseline v2: stops of at least 1.5% and limit-order entries, +0.12R per trade on the same history ([review](docs/research/2026-10-03-strategy-review.md)).
> Next: the forward run with `agent` (7+ days); the paper account starts fresh at $150.

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

# 5. Run the agent 24/7: reader + Binance data + shadow engine + paper account (Ctrl+C to stop)
.venv\Scripts\python -m tradeagent agent

# 6. Results
.venv\Scripts\python -m tradeagent shadow-report   # every variant in the exploration book
.venv\Scripts\python -m tradeagent paper-report    # paper account and the go-live gate

# Tests (add -m network to include the Binance test)
.venv\Scripts\python -m pytest
```

Other commands:

- Reader: `reader`, `snapshot`, `tv-status`, `show`, `verify-candles`, `coverage`, `repaint-audit`. See [Phase 1](docs/phases/phase-1-tradingview-reader.md#commands).
- Shadow engine: `market-sync`, `backfill-snapshots --bars 10000`, `shadow-run`, `shadow-report --halves`, `trades`, `verify-trades`, `shadow-reset`. See [Phase 2](docs/phases/phase-2-shadow-engine.md#commands).
- Paper account: `paper-report`, `kill-switch`, `paper-reset`. See [Phase 3](docs/phases/phase-3-paper-account-and-risk.md#commands).

## How it works

1. TradingView Desktop shows five indicators (Q-Trend, Klinger, VWAP, Zero Lag, ATP MACD) on Binance perpetual charts.
2. The agent reads every **closed** candle over the Chrome DevTools Protocol (CDP).
3. Python turns those readings into setups and simulates shadow trades with real Binance prices, fees included.
4. A paper account follows the baseline's trades under the live rules ($150, 2% risk, max 2 positions, daily loss stop).
5. Claude (Pro plan) reviews the journal, forms a hypothesis, and proposes one change at a time.
6. Changes that hold up on fresh data become the new baseline.
7. Live trading starts only after the go-live gate is met **and** you approve it.

## Key facts

| Item | Decision |
|---|---|
| Exchange | Binance USDT-M perpetual futures |
| Coins | XRP, LINK, SOL |
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
