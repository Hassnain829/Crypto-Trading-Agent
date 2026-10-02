# Phase 1 — TradingView Signal Reader

**Goal:** Read the values of all 5 indicators for every closed candle, on all coins and timeframes, 24/7.
**Depends on:** [Phase 0](phase-0-foundation.md). **Estimated time:** 3–5 days, including a 48-hour test.

This is the riskiest part of the project, so it comes first.

**Already proven (2026-10-02):** the Python CDP client reads live data-window values of all 5 indicators on the PC. What is still missing is reading the **closed** candle reliably, on schedule, for every coin and timeframe.

## Chart layout

| Layout | Chart 1 | Chart 2 | Template |
|---|---|---|---|
| AGENT-XRP | XRP 5m | XRP 15m | Scalp |
| AGENT-LINK | LINK 5m | LINK 15m | Scalp |
| AGENT-SOL | SOL 5m | SOL 15m | Scalp |
| AGENT-HTF | HTF 1h (cycles XRP → LINK → SOL) | HTF 4h (cycles) | Trend |

- Essential allows 2 charts per layout. Each open tab counts as one chart connection.
- Fallback: switch the layout in a tab on demand, or open one HTF tab per coin, if cycling is too slow.

## Build tasks

1. **CDP client.** Extend `tv/cdp.py`:
   - one long-lived connection per chart tab
   - reconnect on failure
   - open the 4 AGENT layouts in tabs and keep them open

   No Node.js or MCP server is needed.
2. **Indicator output catalog.** For each indicator, list the data-window fields we use and what they mean. The field names are in [TRADINGVIEW-SETUP.md](../TRADINGVIEW-SETUP.md). Store the catalog in config so a renamed field does not break the code.
3. **Closed-candle reading.** The data window shows the forming candle, and an arrow on a forming candle can disappear before it closes. Read the indicator values of the last **closed** candle from the study's internal data series instead. This uses the same internal method TradingView uses for OHLCV bars, in our own JavaScript evaluated over CDP.
4. **Read schedule.** Aligned to candle closes in **Binance server time**, because the PC clock can drift:

   | When | What is read |
   |---|---|
   | Every 5m close | The 5m charts of the 3 coins |
   | Every 15m close | Also the 15m charts |
   | Every 1h close | HTF tab, 1h, for the 3 coins |
   | Every 4h close | Also 4h |

5. **Snapshot validation.** Check symbol, timeframe and bar time, and that no fields are missing. Record the read latency.
6. **Settings capture.** Read the indicator inputs and hash them into a "signal version". Flag any change against Signal Version 1.
7. **Watchdog.**
   - Run a health check every cycle.
   - If TradingView is down, frozen or running without the debug port, restart it with `scripts/launch_tradingview_debug.ps1`.
   - Reconnect and log the event.
8. **Repaint audit.** Re-read past candles later and compare them with the values read at close. Fields that change are marked as repainting. Expected:
   - the Zero Lag multi-timeframe table
   - ATP MACD divergence markers, which are confirmed 5 bars late
9. **Journal migration 2:** `snapshots` and `indicator_settings` tables.
10. **Resource log.** RAM and CPU of TradingView and the agent.

## Deliverables

- `snapshots` table filling 24/7
- Indicator output catalog (config)
- Repaint audit report
- Watchdog with automatic restart

## Exit criteria

- [ ] 48 hours of continuous running on the PC
- [ ] ≥ 99% of expected snapshots captured (3 coins × 4 timeframes)
- [ ] Snapshots available ≤ 30 seconds after the candle closes
- [ ] 20 random snapshots match TradingView's data window when checked by hand
- [ ] The watchdog recovered from at least one forced TradingView restart
- [ ] RAM usage below 80% of the machine's memory

## Risks and fallbacks

| Risk | Fallback |
|---|---|
| Closed-candle values cannot be read from the internal series | A small Pine "combiner" table that shows the previous candle's values, read from its table cells |
| Reading is unstable | Add 1–2 TradingView alerts as a backup trigger |
| Tab or layout switching is too slow | Keep one tab per layout open permanently |
| A TradingView update changes the internal API | Update our JavaScript; pause new shadow trades until fixed (the watchdog flags it) |
| You use the AGENT tabs while the agent reads them | The reader checks symbol and timeframe before every read; do your own analysis in the 5th layout |
| Account risk (unofficial access) | Personal, read-only use; you are responsible for following TradingView's terms |
