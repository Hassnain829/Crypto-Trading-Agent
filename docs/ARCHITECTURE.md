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
Shadow Simulator ◄── trading venue prices (1m / 5m / 15m / 1h, public API; venues.py)
        │
        ├──► Exploration book (unlimited, never stops)
        ├──► Paper account (live rules)
        └──► Live broker (Phase 6, real orders on the trading venue)
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
| Signal Reader (`tv/reader.py`) | Reads every closed candle on schedule, validates it, stores snapshots | 1 ✓ |
| Watchdog (`tv/watchdog.py`) | Restarts TradingView in debug mode, opens missing AGENT tabs, reloads stuck tabs | 1 ✓ |
| Market Data (`market/`) | The trading venue's candles, contract sizes and funding rates (no API key needed) | 2 ✓ |
| Venues (`venues.py`) | Registry of exchanges (Binance, Coinbase US, Kraken Futures, Coinbase International, Bitget, MEXC): ccxt class, who may use it, fees, quiet minutes, server time; `venue-replay` compares the strategy on another venue | 4.5 ✓ |
| Setup Engine (`setups/engine.py`) | Applies the setup rules (`config/setups.yaml`) to snapshots for every variant | 2 ✓ |
| Shadow Simulator + Tracker (`sim/`) | Simulates trades on 1m candles with real prices, fees, slippage and funding | 2 ✓ |
| Agent (`agent.py`) | One process: reader, market data, setup engine, tracker and paper account at every candle close | 2 ✓ |
| Paper account + Risk Engine (`account/`) | Live-like ledger with all live rules; `PaperBroker` behind the broker interface | 3 ✓ |
| Dashboard (`dashboard/`) | Monitoring and control in the browser: six pages, settings with an audit log, exchange keys, live preview | 4 ✓ |
| Settings store (`settings_store.py`) | Dashboard overrides of settings.yaml, validated and audited; the agent applies them every cycle | 4 ✓ |
| Research pack + Experiment Manager | Builds reports for Claude; validates and runs experiments | 5 |
| TradingView MCP server (optional) | Lets Claude Code look at charts during research sessions (needs Node.js) | 5 |
| Live Broker | Real orders on the trading venue and reconciliation | 6 |

## 3. Processes on the host (PC now, VPS later)

| Process | How it runs | Recovery |
|---|---|---|
| TradingView Desktop | GUI app in a logged-in Windows session, started with the debug port (`scripts/launch_tradingview_debug.ps1`) | Watchdog restarts it; on the VPS, Windows auto-logon brings it back after a reboot |
| `agent` (Python) | Windows service or startup task | Auto-restart on crash |
| `dashboard` (Python) | Windows service or startup task, `127.0.0.1:8080` | Auto-restart on crash |
| Research (optional) | Task Scheduler runs Claude Code once a day | Next scheduled run |

TradingView Desktop is a GUI app, so it needs a logged-in user session. On the VPS, enable Windows auto-logon and **disconnect** RDP instead of signing out.

## 4. Timing of one cycle

1. `t` = candle close (for example 10:05:00, measured in the venue's server time, or the synced computer clock).
2. About `t + 3s`: the Signal Reader reads the closed 5m candle on the 3 coin tabs. At 15m closes it also reads the 15m charts.
3. The HTF tab reads 1h at every hour close and 4h at every 4h close.
4. The Setup Engine evaluates every variant. The Shadow Simulator opens shadow trades.
5. Simulated entry price = the venue's 1m open right after the candle close. A market entry adds slippage. A limit entry (baseline v2) fills only if that minute trades through the price. The trade is recorded once that 1m candle has closed, so normally in the next cycle.
6. Outcome tracking runs on every new 1m candle.
7. The paper account takes the baseline's new trades under the live rules and settles the ones that closed.

## 5. Data model

Tables are added by migrations when each phase designs them.

| Table | Holds | Added in |
|---|---|---|
| `events` | Logs, doctor runs, watchdog events, data gaps | 0 ✓ |
| `settings`, `settings_audit` | Dashboard settings and their change history | 0 ✓ |
| `snapshots` | Per coin / timeframe / closed candle: all indicator values, signal version, read latency | 1 ✓ |
| `indicator_settings` | Indicator inputs for each signal version | 1 ✓ |
| `candles`, `funding`, `market_info` | The trading venue's OHLCV (1m, 5m, 15m, 1h), funding rates, step sizes, minimum orders and contract sizes; one venue at a time (`engine_state` key `market:venue`) | 2 ✓, 4.5 ✓ |
| `setups` | Trigger events and their evaluation per variant | 2 ✓ |
| `trades` | Exploration book: variant, entry / stop / target, fills, fees, net R, MFE / MAE, status, reason, simulator state | 2 ✓ |
| `variants` | Parameters, role (baseline / challenger / retired), parent | 2 ✓ |
| `engine_state` | Where the setup engine stopped, per coin and timeframe (restart-safe catch-up) | 2 ✓ |
| `account_state`, `account_trades` | Paper account (live in Phase 6): balance, daily stop, every signal opened or rejected and why, USDT PnL | 3 ✓ |
| `agent_status`, `baseline_history` | The agent's heartbeat for the dashboard; every strategy version the paper account followed | 4 ✓ |
| `experiments` | Hypothesis, variable, old and new value, results, decision, lesson | 5 |
| `lessons` | Research memory | 5 |

## 6. Tech stack

| Area | Choice |
|---|---|
| Language | Python 3.12+ (tested on 3.14.6) |
| Exchange access | ccxt, one class per venue (`binanceusdm`, `coinbase`, `krakenfutures`, `coinbaseinternational`, `bitget`, `mexc`) |
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
├── config/                  settings.yaml (no secrets), indicators.yaml (catalog), setups.yaml (rules)
├── scripts/                 launch_tradingview_debug.ps1
├── src/tradeagent/
│   ├── cli.py, doctor.py    command line and health checks
│   ├── config.py, paths.py  settings loading and validation
│   ├── logging_setup.py     rotating log file, UTC
│   ├── journal/             SQLite connection and migrations
│   ├── agent.py             the 24/7 agent: reader + market data + shadow engine + paper account
│   ├── tv/                  CDP client, signal reader, watchdog, coverage, repaint audit
│   ├── market/              the venue's candles, funding, market info and server clock (through venues.py)
│   ├── setups/              setup rules, variants, engine, reports, independent trade check
│   ├── sim/                 shadow simulator and tracker
│   ├── account/             paper account: rules, kill switch, broker interface, engine, report
│   ├── learning/  dashboard/   (added in Phases 4–5)
├── tests/
├── docs/
└── data/                    journal.db, logs (created at runtime, not in git)
```
