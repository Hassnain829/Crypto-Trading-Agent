# Requirements and Decisions

This file is the single source of truth for what we agreed. If a decision changes, update it here and add a line to the decision log at the bottom.

## 1. Vision

Build an agent that gets better at scalping by itself. It follows four rules:

| Rule | What it means in this project |
|---|---|
| Accurate | Decisions use closed candles only. Trade outcomes use real Binance prices. Fees and slippage are always included. |
| Reliable | Runs 24/7 on a Windows VPS. A watchdog restarts TradingView if it fails. A restart never loses or duplicates data. |
| Clear goal | Success is defined in numbers (see [GOALS-AND-METRICS.md](GOALS-AND-METRICS.md)). The agent always knows whether it is moving toward the goal or away from it. |
| Self-improving | Claude reviews results, forms a hypothesis and changes one variable at a time. Only changes that hold up on fresh data are kept. |

The YouTube strategies (4H range, Q-Trend + Klinger, Zero Lag) are references only. The agent is not bound to their exact rules.

## 2. Agreed decisions

### Market

| Topic | Decision |
|---|---|
| Exchange | Binance, USDT-M perpetual futures |
| Coins | XRP, LINK, SOL (more later) |
| TradingView symbols | `BINANCE:XRPUSDT.P`, `BINANCE:LINKUSDT.P`, `BINANCE:SOLUSDT.P` (same exchange as execution) |
| Trading timeframes | 5m and 15m |
| Overview timeframes | 1h and 4h (trend context and exit choice) |
| Style | Scalping, many trades |

### Signals and indicators

| Topic | Decision |
|---|---|
| Signal source | TradingView Desktop (Essential plan), read through the TradingView MCP (`tradingview-mcp-jackson`) |
| Webhook alerts | Not used. The agent reads the chart directly. Alerts may be added later only as a backup. |
| Indicators | Max 5 per chart (Essential limit): Q-Trend, Klinger, VWAP, AlgoAlpha Zero Lag Signals, ATP MACD Signal System |
| Indicator settings | Signal Version 1, verified on TradingView. Full list in [TRADINGVIEW-SETUP.md](TRADINGVIEW-SETUP.md). Q-Trend: ATR period 32, EMA smoother 10. Klinger (everget): fast 38, slow 60, histogram. Zero Lag: length 70, multiplier 1.2. ATP MACD: Custom 12/26/9, No Filter. VWAP: Session, bands 1 and 2. |
| Layouts | AGENT-XRP, AGENT-LINK, AGENT-SOL (5m + 15m), AGENT-HTF (1h + 4h); templates "Scalp" and "Trend" |
| Indicators in Python | None. Python never calculates indicators. It only reads TradingView values. |
| Candles | Only closed candles are used for decisions. |
| Settings tracking | Indicator settings are saved with every trade. A change creates a new "signal version". |
| Confirmation | A confirming candle may come up to 3 candles after the trigger. |

### Shadow trading

| Topic | Decision |
|---|---|
| Exploration book | Unlimited trades. No daily loss limit and no drawdown stop. It never stops learning. |
| Paper account | Live-like simulation: $150, 2% risk, max 2 positions, daily loss stop 10–12%. Runs beside exploration and never blocks it. |
| Costs | Fees and slippage always included (Binance VIP0: 0.02% maker, 0.05% taker). |
| Variants | Many variants are tested in parallel on the same signals. |
| History | TradingView Strategy Tester (~35 days of 5m data with Essential) plus forward shadow trading is enough. |

### Exits

| Topic | Decision |
|---|---|
| Fixed take-profit | Used when the higher timeframes do not confirm the trend |
| Hybrid exit | When 1h/4h confirm the trend: close 50% at 1R, move the stop to break-even, trail the rest |
| Testing | Fixed, hybrid and the HTF rule all run as parallel variants, so the data confirms whether the rule helps |

### Learning

| Topic | Decision |
|---|---|
| Research model | Claude through the Claude Pro plan (Claude Code). Using Pro usage for research is fine. |
| Method | One variable at a time. Winners are re-checked on fresh data before they become the baseline. |
| Live changes | Nothing reaches live trading without your approval in the dashboard. |

### Reporting

| Topic | Decision |
|---|---|
| What you see | Net PnL (after fees) and account % |
| What the agent learns from | R (net profit ÷ planned risk) |

### Live trading (later)

| Topic | Decision |
|---|---|
| Capital | $100–150 |
| Risk per trade | 2% |
| Max positions | 2 total (1 per coin) |
| Daily loss stop | 10–12% |
| Orders | Stop-loss and take-profit placed on Binance as orders right after entry |

### Dashboard

| Topic | Decision |
|---|---|
| Stack | Python: NiceGUI (runs on FastAPI) |
| Language | English UI |
| Security | No login for now (personal use). Listens on localhost by default. |
| API keys | Stored in the local `.env`. A user can also paste keys in Settings for a quick setup. |
| TradingView chart in the dashboard | No. TradingView Essential is used for charts. |
| Notifications | None for now (no Telegram) |

### Infrastructure

| Topic | Decision |
|---|---|
| Host for now | Your Windows PC runs everything: TradingView Desktop (debug mode) and the project. |
| Server later | Windows VPS (DatabaseMart), 8 GB RAM, 2 GPU (as reported). You will set it up yourself: install TradingView, log in to the same account (layouts sync), run the project through VS Code. Ask Claude for the steps when moving. The location must be allowed by Binance. |
| TradingView | Desktop app on the PC now; on the VPS later |

## 3. Out of scope for now

- Webhook alerts
- Indicators written in Python
- TradingView charts inside the dashboard
- Telegram or other notifications
- Dashboard login / security
- Claude API (the Pro plan is used instead)
- Coins other than XRP, LINK, SOL

## 4. Open items

| Item | Status |
|---|---|
| Go-live gate numbers | Proposed in [GOALS-AND-METRICS.md](GOALS-AND-METRICS.md), editable in Settings |
| Definition of "HTF confirmed" | 1h only vs 1h + 4h. Decided by shadow data. |
| VWAP vs Smith VWAP | Standard VWAP first. Smith VWAP if you share its Pine source. |
| VPS capacity | Measure RAM/CPU in Phase 1 |

## 5. Decision log

| Date | Decision |
|---|---|
| 2026-10-02 | The LLM does not make trade decisions. Rules plus TradingView signals do. Claude only researches. |
| 2026-10-02 | Exchange data is used only to track outcomes and size positions, never to calculate indicators. |
| 2026-10-02 | Coins limited to XRP, LINK, SOL. |
| 2026-10-02 | Read the chart through the MCP instead of using webhook alerts. |
| 2026-10-02 | Binance chosen. Live starts at 2% risk, max 2 positions. |
| 2026-10-02 | Dashboard in Python with an English UI. No login, no TradingView chart, no Telegram. |
| 2026-10-02 | Shadow exploration never stops for losses or drawdown. |
| 2026-10-02 | TradingView Essential set up and verified as Signal Version 1 (4 AGENT layouts, Scalp/Trend templates). ATP MACD uses Custom 12/26/9 with No Filter. |
| 2026-10-02 | Everything runs on the user's PC for now. The user will move it to the VPS later, setting it up himself with Claude's instructions. |
| 2026-10-02 | Phase 0 complete. The agent talks to TradingView Desktop directly from Python over CDP. Node.js and the MCP server are optional, used only for Claude Code research sessions. |
