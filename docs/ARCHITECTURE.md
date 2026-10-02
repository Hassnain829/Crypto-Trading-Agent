# Architecture

## 1. Data flow

```
TradingView Desktop (Essential): charts + 5 indicators
        │  Chrome DevTools Protocol (Python client, no Node.js needed)
        ▼
Signal Reader ─────► snapshots (closed candles only)
        │
        ▼
Setup Engine ──────► setups for every variant
        │
        ▼
Shadow Simulator ◄── Binance prices (1m / 5m / 15m, public API)
        │
        ├──► Exploration book (unlimited, never stops)
        ├──► Paper account (live rules)
        └──► Live broker (Phase 6, real Binance orders)
        │
        ▼
SQLite journal ◄───► Dashboard (NiceGUI, English UI)
        │
        ▼
Research pack ──► Claude Code (Pro) ──► proposals
                                            │
                                            ▼
                                  Experiment Manager ──► new challengers ──► Setup Engine
```

## 2. Components

| Component | Job | Phase |
|---|---|---|
| TradingView Desktop | Shows the charts and the 5 indicators; the source of all signals | 0 |
| CDP client (`tv/cdp.py`) | Lets Python read and control TradingView Desktop directly | 0 (minimal), 1 (full) |
| Signal Reader | Reads every closed candle on schedule, validates it, stores snapshots | 1 |
| Watchdog | Restarts TradingView in debug mode and reconnects when something fails | 1 |
| Market Data | Binance candles, exchange info and funding rates (no API key needed) | 2 |
| Setup Engine | Applies the setup rules (YAML) to snapshots for every variant | 2 |
| Shadow Simulator | Simulates trades with real prices, fees, slippage and funding | 2 |
| Paper account + Risk Engine | Live-like ledger with all live rules | 3 |
| Dashboard | Monitoring and settings | 4 |
| Research pack + Experiment Manager | Builds reports for Claude; validates and runs experiments | 5 |
| TradingView MCP server (optional) | Lets Claude Code look at charts during research sessions (needs Node.js) | 5 |
| Live Broker | Real Binance orders and reconciliation | 6 |

## 3. Processes on the host (PC now, VPS later)

| Process | How it runs | Recovery |
|---|---|---|
| TradingView Desktop | GUI app in a logged-in Windows session, started with the debug port (`scripts/launch_tradingview_debug.ps1`) | Watchdog restarts it; on the VPS, Windows auto-logon brings it back after a reboot |
| `agent` (Python) | Windows service or startup task | Auto-restart on crash |
| `dashboard` (Python) | Windows service or startup task, `127.0.0.1:8080` | Auto-restart on crash |
| Research (optional) | Task Scheduler runs Claude Code once a day | Next scheduled run |

TradingView Desktop is a GUI app, so it needs a logged-in user session. On the VPS, enable Windows auto-logon and **disconnect** RDP instead of signing out.

## 4. Timing of one cycle

1. `t` = candle close (for example 10:05:00, measured in Binance server time).
2. About `t + 3s`: the Signal Reader reads the closed 5m candle on the 3 coin tabs. At 15m closes it also reads the 15m charts.
3. The HTF tab reads 1h at every hour close and 4h at every 4h close.
4. The Setup Engine evaluates every variant. The Shadow Simulator opens shadow trades.
5. Simulated entry price = the Binance 1m open right after the candle close, plus slippage.
6. Outcome tracking runs on every new 1m candle.

## 5. Data model

Tables are added by migrations when each phase designs them.

| Table | Holds | Added in |
|---|---|---|
| `events` | Logs, doctor runs, watchdog events, data gaps | 0 ✓ |
| `settings`, `settings_audit` | Dashboard settings and their change history | 0 ✓ |
| `snapshots` | Per coin / timeframe / closed candle: all indicator values, signal version, read latency | 1 |
| `indicator_settings` | Indicator inputs for each signal version | 1 |
| `candles` | Binance OHLCV (1m, 5m, 15m) | 2 |
| `setups` | Trigger events and their evaluation per variant | 2 |
| `trades` | Book (exploration / paper / live), variant, entry / stop / target, fills, fees, net PnL, R, MFE / MAE, status, reason | 2 |
| `variants` | Parameters, role (baseline / challenger / retired), parent | 2 |
| `experiments` | Hypothesis, variable, old and new value, results, decision, lesson | 5 |
| `lessons` | Research memory | 5 |

## 6. Tech stack

| Area | Choice |
|---|---|
| Language | Python 3.12+ (tested on 3.14.6) |
| Exchange access | ccxt (`binanceusdm`, Binance USDT-M) |
| Statistics | pandas, numpy (statistics only, never indicators) |
| Storage | SQLite in WAL mode, versioned migrations |
| Config and validation | YAML + pydantic; secrets in `.env` |
| TradingView access | Own Python CDP client (aiohttp WebSocket + `Runtime.evaluate`) |
| Debug-port launch | `scripts/launch_tradingview_debug.ps1` (Windows app activation for the Store build) |
| Dashboard | NiceGUI (runs on FastAPI) |
| Research | Claude Code with the Pro plan; TradingView MCP optional |
| Tests | pytest |

## 7. Design rules

1. Trade decisions come from deterministic rules, never from an LLM.
2. Closed candles only.
3. Exploration, paper and live share one code path; only the broker changes.
4. Every number in the dashboard comes from the journal. The UI calculates nothing on its own.
5. Restart-safe: every step is idempotent, and the agent catches up after downtime.
6. Settings changes are versioned and written to an audit log.
7. Live trading needs your explicit approval.

## 8. Repository layout

```
Crypt-Ai-Trading/
├── config/settings.yaml     all settings (no secrets)
├── scripts/                 launch_tradingview_debug.ps1
├── src/tradeagent/
│   ├── cli.py, doctor.py    command line and health checks
│   ├── config.py, paths.py  settings loading and validation
│   ├── logging_setup.py     rotating log file, UTC
│   ├── journal/             SQLite connection and migrations
│   ├── tv/                  CDP client (Phase 1: signal reader, watchdog)
│   ├── market/              Binance through ccxt
│   ├── setups/  sim/  account/  learning/  dashboard/   (added in Phases 2–5)
├── tests/
├── docs/
└── data/                    journal.db, logs (created at runtime, not in git)
```
