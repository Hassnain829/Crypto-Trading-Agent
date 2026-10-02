# TradingView Setup — Signal Version 1

Verified directly on TradingView Desktop (v3.4.1, Microsoft Store build) on 2026-10-02. Every result in the journal will be tagged with this signal version. If any setting below changes, create "Signal Version 2" in a new section and log it in [REQUIREMENTS.md](REQUIREMENTS.md).

## 1. Saved layouts (Essential: 4 of 5 slots used)

| Layout | Chart 1 | Chart 2 | Template | Sync |
|---|---|---|---|---|
| AGENT-XRP | `BINANCE:XRPUSDT.P` 5m | `BINANCE:XRPUSDT.P` 15m | Scalp | Symbol on, Interval off |
| AGENT-LINK | `BINANCE:LINKUSDT.P` 5m | `BINANCE:LINKUSDT.P` 15m | Scalp | Symbol on, Interval off |
| AGENT-SOL | `BINANCE:SOLUSDT.P` 5m | `BINANCE:SOLUSDT.P` 15m | Scalp | Symbol on, Interval off |
| AGENT-HTF | `BINANCE:XRPUSDT.P` 1h | `BINANCE:XRPUSDT.P` 4h | Trend | Symbol on, Interval off |

- All charts: Candles, timezone UTC, autosave on, no Volume indicator.
- The 5th layout slot is free for personal analysis. Do not analyse inside the AGENT layouts; autosave syncs every change.

## 2. Indicator templates

| Template | Indicators | Remember symbol / interval |
|---|---|---|
| Scalp | Zero Lag, VWAP, Q-Trend, ATP MACD, KVO | Off / Off |
| Trend | Zero Lag, Q-Trend | Off / Off |

The older `SCALP_` template was deleted on 2026-10-02 because it no longer matched this setup. "Countdown to bar close" is on for every chart.

## 3. Indicator settings

### Q-Trend (tarasenko_) — `Script$PUB;57f29d2df9cc4d25b8c5511e95cfaac5`

| Input | Value |
|---|---|
| Source | close |
| Trend period | 200 |
| ATR Period | 32 |
| ATR Multiplier | 1 |
| Signal mode | Type A |
| Smooth source with EMA? | Yes |
| EMA Smoother period | 10 |
| Color bars? | false |
| Show trend line? | true |
| Signals to show | All |
| Signal's shape | Labels (visual only) |

### Klinger Volume Oscillator (everget, short title KVO) — `Script$PUB;tKmDB7iBEKvaDMTd7l6QHlkROfjRNOjf`

| Input | Value |
|---|---|
| Fast Length | 38 |
| Slow Length | 60 |
| Show Signal ? | true |
| Signal Smoothing Type | EMA |
| Signal Smoothing Length | 13 |
| Show Histogram ? | true |
| Highlight KVO/Signal Crossovers ? | false |
| Highlight Zero Line Crossovers ? | false |
| Apply Ribbon Filling ? | false |

### VWAP (TradingView built-in) — `Script$STD;VWAP`

| Input | Value |
|---|---|
| Hide VWAP on 1D or Above | true |
| Anchor Period | Session (resets 00:00 UTC) |
| Source | hlc3 |
| Offset | 0 |
| Bands Calculation Mode | Standard Deviation |
| Bands #1 / #2 / #3 | 1 (on) / 2 (on) / 3 (off) |

### Zero Lag Trend Signals (MTF) [AlgoAlpha] — `Script$PUB;d7eefaf9a1ea4811bb0cbc0c1d9a7334`

| Input | Value |
|---|---|
| Length | 70 |
| Band Multiplier | 1.2 |
| Time frames 1–5 | 5, 15, 60, 240, 1D (MTF table is not used: it repaints) |

### ATP MACD Signal System (AlgoTrade_Pro) — `Script$PUB;499fed8d88604d33a7e06d588d8fe976`

| Input | Value |
|---|---|
| MACD Preset | Custom |
| Fast / Slow / Signal Length | 12 / 26 / 9 |
| Source | close |
| Oscillator / Signal MA Type | EMA / EMA |
| Show Buy/Sell Signals | true |
| Show Histogram | true |
| Show Signal Counter | false |
| Show Momentum Background | false |
| Minimum Bars Between Signals | 3 |
| Trade Direction | Both (Long & Short) |
| Signal Filter Mode | No Filter |
| Show Divergences | true (pivot 5/5: divergences are confirmed 5 bars late) |

## 4. Data-window fields (input for the Phase 1 output catalog)

Read live through the Chrome DevTools Protocol on 2026-10-02. These values belong to the **forming** candle. Phase 1 must read the last **closed** candle instead.

| Indicator | Fields |
|---|---|
| Q-Trend | `trend line`, `Buy signal`, `Sell signal`, `Strong Buy signal`, `Strong Sell signal` (0 when no signal) |
| KVO | `Histogram`, `KVO`, `Signal` |
| VWAP | `VWAP`, `Upper Band #1`, `Lower Band #1`, `Upper Band #2`, `Lower Band #2` |
| Zero Lag | `Zero Lag Basis`, `Upper Deviation Band` (bearish trend) or `Lower Deviation Band` (bullish trend); arrows `Bullish/Bearish Trend` and `Bullish/Bearish Entry` when present |
| ATP MACD | `Histogram`, `MACD Line`, `Signal Line`, `Buy Signal`, `Sell Signal`, divergence labels/markers |

## 5. Technical findings for Phase 0/1

- **Debug-port launch on the Microsoft Store build.** The MCP repo's launch scripts do not handle the MSIX install. What works: close TradingView, then start it through Windows AppX activation (`IApplicationActivationManager.ActivateApplication`) with the argument `--remote-debugging-port=9222`.
  - App ID: `TradingView.Desktop_n534cwy3pjxzj!TradingView.Desktop`
  - The port listens on localhost only. It closes when TradingView is restarted normally.
- **Python can talk to TradingView directly.** A small Python CDP client (aiohttp WebSocket + `Runtime.evaluate`) did everything the Node MCP server does: read studies, inputs and data-window values; change layouts and inputs; save layouts and templates. The agent may not need Node.js at all. The MCP server stays useful for Claude Code research sessions.
- **Useful internal API paths** (undocumented; may change with TradingView updates):

  | Path | Use |
  |---|---|
  | `window.TradingViewApi.chart(i)` | Chart API for the i-th chart in the layout |
  | `chart.getAllStudies()`, `getStudyById(id).getInputValues()` | Studies and their inputs |
  | `_chartWidgetCollection.getAll()[i].model().model().dataSourceForId(id)` | Internal study object |
  | `.properties().childs().inputs.childs()` | Reliable input values |
  | `.dataWindowView().items()` | Live data-window values |
  | `TradingViewApi.symbolSync()`, `intervalSync()` | Layout sync settings |
  | `getSaveChartService()._renameController._doSaveCurrentLayout(name)` | Rename and save the layout |
  | `getSaveChartService()._saveAsController._doCloneCurrentLayout(name)` | Save the layout as a new copy |
- **Careful with `setInputValues`.** Passing the full input array back made `getInputValues()` return an empty list for ATP MACD, although the study kept its values and kept calculating. Prefer setting single properties: `inputs.childs()[id].setValue(v)`.
- **Node.js** is not installed on the PC yet.
