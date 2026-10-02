# Phase 1 — TradingView Signal Reader

**Goal:** Read the values of all 5 indicators for every closed candle, on all coins and timeframes, 24/7.
**Depends on:** [Phase 0](phase-0-foundation.md). **Estimated time:** 3–5 days, including a 48-hour test.

> **Status (2026-10-02): built; the 48-hour test is next.**
> - First live checks: 12/12 snapshots OK, and every candle matched Binance exactly.
> - In the reader loop, latency was 3.7 s after the candle close.
> - The watchdog was hardened after a test crash. It retries the debug port, waits for a page that has the TradingView API, and opens each missing layout separately. The reader retries its start every 60 s.
> - What remains: the 48-hour run and its exit criteria (below). Run it with `agent`, which also covers the Phase 2 and Phase 3 runs.

## Chart layout

| Layout | Chart 1 | Chart 2 | Template |
|---|---|---|---|
| AGENT-XRP | XRP 5m | XRP 15m | Scalp |
| AGENT-LINK | LINK 5m | LINK 15m | Scalp |
| AGENT-SOL | SOL 5m | SOL 15m | Scalp |
| AGENT-HTF | HTF 1h (cycles XRP → LINK → SOL) | HTF 4h (cycles) | Trend |

The watchdog opens any missing AGENT layout in its own tab. Symbol cycling on the HTF tab takes under 1 second per coin.

## How it works (as built)

| Part | Implementation |
|---|---|
| Connection | `tv/cdp.py`: one short CDP WebSocket per call (simple and robust at a 5-minute rhythm; no Node.js) |
| Catalog | `config/indicators.yaml`: plot id, expected title and kind for every field. A renamed or moved plot is reported as a problem; it is never read silently. |
| Closed candle | `tv/js.py` reads the study's internal data series at the candle's open time. The forming candle is never used. |
| Signals | Read from the scripts' alert conditions, as 0/1 flags that do not depend on display settings: Q-Trend BUY/SELL, Zero Lag Bullish/Bearish Trend and Entry, ATP MACD Buy/Sell. |
| History | Every chart keeps ≥ 1500 bars loaded with `requestMoreData`, because TradingView loads only 300 bars and Zero Lag needs ~280 to warm up. |
| Ready check | The series status is 3, it is not loading, and every study has recomputed over the full history. After a symbol switch, the reader waits for the reload. |
| Schedule | Candle closes in Binance server time, plus `read_delay_s` (3 s): every 5m; 15m at :00/:15/:30/:45; 1h on the hour; 4h at 00/04/08/12/16/20 UTC |
| Validation | Symbol, interval and candle time; chart ready; all catalog fields present. Problems are stored with the snapshot. |
| Signal version | Hash of all non-colour indicator inputs on every AGENT chart. A change creates a new signal version and a warning event. |
| Watchdog | Starts TradingView with the launcher if the debug port is closed, opens missing AGENT tabs, and reloads a tab stuck in "loading" for 240 s |
| Resources | RAM/CPU of the machine, TradingView and the agent, logged every hour |
| Journal | Migration 2: `snapshots`, `indicator_settings` |

## Commands

| Command | Use |
|---|---|
| `python -m tradeagent agent` | Run the reader together with the shadow engine and the paper account (Phases 2–3). Use this for the 24/7 runs. |
| `python -m tradeagent reader` | Run only the reader 24/7 (Ctrl+C to stop). Logs go to `data/logs/agent.log`. |
| `python -m tradeagent snapshot` | Read the last closed candle of every chart once and print it |
| `python -m tradeagent tv-status` | Show the AGENT tabs, charts, bars loaded and ready state |
| `python -m tradeagent show --symbol XRP --tf 5m --last 3` | Print stored snapshots with every value, to compare by hand with TradingView |
| `python -m tradeagent verify-candles --count 20` | Compare stored candles with Binance's candles |
| `python -m tradeagent coverage --hours 48` | Coverage and latency per coin and timeframe |
| `python -m tradeagent repaint-audit --hours 24` | Re-read stored snapshots and list values that changed later |

## The 48-hour test (your part)

1. Keep the PC on, with sleep disabled. Close Chrome tabs you do not need, because RAM was at 87–92% in the tests (TradingView itself uses ~2 GB).
2. Start TradingView in debug mode: `powershell -ExecutionPolicy Bypass -File scripts\launch_tradingview_debug.ps1`
3. In a terminal in the project folder: `.venv\Scripts\python -m tradeagent agent`. Leave it running. It includes the reader and also runs the 7-day tests of Phases 2 and 3.
4. Do your own analysis only in the 5th layout, not in the AGENT tabs.
5. After 48 hours, run these in a second terminal while the agent keeps running:
   - `coverage --hours 48`
   - `verify-candles --count 20`
6. `repaint-audit --hours 24` switches the HTF chart, so run it only while the agent is stopped. Stop the agent with Ctrl+C, run the audit, then start the agent again. A short stop is safe, because the agent catches up.
7. Hand-check 20 snapshots: `show --last 20`, then hover the same candles in TradingView.

## Exit criteria

- [ ] 48 hours of continuous running on the PC
- [ ] ≥ 99% of expected snapshots captured (3 coins × 4 timeframes): `coverage --hours 48`
- [ ] Snapshots available ≤ 30 seconds after the candle closes. The first loop showed 3.7 s.
- [ ] 20 random snapshots checked:
  - candles: `verify-candles` (12/12 already matched exactly)
  - indicator values: by hand with `show`
- [ ] The watchdog recovered from at least one forced TradingView restart (close TradingView once during the test)
- [ ] RAM usage below 80% of the machine's memory. **At risk:** 92% at the start, mostly Chrome.

## Changes from the original plan

- One short connection per call instead of long-lived connections. Simpler, and fast enough at a 5-minute rhythm.
- History loading and a strict ready check were added, because TradingView loads only 300 bars by default.
- Signal flags come from alert-condition plots instead of drawn arrows. They do not depend on display settings.

## Risks and fallbacks

| Risk | Fallback |
|---|---|
| A TradingView update changes the internal API | Title checks catch moved plots. Update `tv/js.py` or the catalog; the watchdog and the problems column flag the outage. |
| A chart tab gets stuck loading | The watchdog reloads the tab after 240 s |
| You use the AGENT tabs while the agent reads them | The reader checks symbol and interval on every read; do your own analysis in the 5th layout |
| RAM pressure (92% at start) | Close Chrome tabs during the test; on the VPS later, keep only TradingView and the agent running |
| Account risk (unofficial access) | Personal, read-only use; you are responsible for following TradingView's terms |
