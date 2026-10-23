# 2026-10-21: other ways to trade the same coins (plan, written before the results)

The user asked: "think out of the box". If Claude traded 4+ years of data itself, without the agent's strategy or architecture, how would it find trades and make a good return?

They also asked: what does the current v6 strategy do with one trade per coin?

## Why look elsewhere

- **5m and 15m signals after costs are close to random.** The baseline made +0.008R over 4 years, and costs are about 0.03R a trade.
- **Crypto's best-known edges are slower:**
  - Time-series momentum, i.e. trend following on daily or 4h bars: few trades, long holds, catching the big moves.
  - The funding-rate premium, a market-neutral carry.

## Candidates (textbook settings, not tuned)

Data: Binance USDT-M 1d and 4h candles and funding from 2020-01 for XRP, SOL, ETH and BTC.

| # | Candidate | Rules |
|---|---|---|
| T1-L | Daily Donchian (Turtle), long only | Enter at the next open after a close above the prior 20-day high. Exit at the next open after a close below the prior 10-day low. Hard stop 2×ATR(20) below the entry, which is also 1R. |
| T1-LS | The same, long and short | |
| T2-L | Daily 100-day average, long only | Long after a close above the 100-day SMA, out after a close below it; 2×ATR(20) hard stop as 1R |
| T2-LS | The same, long and short | |
| T3-LS | 4h Donchian, long and short | Prior 20-bar high/low breakout, 10-bar exit, 2×ATR(20, 4h) stop |
| T4 | Funding carry | Short the perp and hold spot (delta-neutral, 1x) while the average funding of the last 3 days is positive. Funding is earned every 8 h. Switching in or out costs 4 taker fees plus slippage. The basis between spot and perp is ignored, so this is optimistic. |
| T5 | C6 (reference) | 15m only, one position per coin |
| T6 | C6 + the daily 100-day trend | C6 longs only above the daily SMA100, shorts only below |
| T7 | v6 with one trade per coin | every 5m and 15m signal, one position per coin, the first wins (the user's last question) |

## Costs and sizing

- Taker fee 0.05% and slippage 0.02% on every market fill.
- Funding is paid or received on every open trend position.
- Today's risk: 2% a trade (the tiers do not exist in these systems), 12% open-risk budget, $150.

## Judgement

Periods:
- 6 years: 2020-10 to 2026-10, with halves at 2023-10.
- The common 4 years: 2022-10 to 2026-10.

Shown for each candidate:
- trades a year
- R a trade
- each year in R
- max drawdown
- $150 at 2% / 12%

Shorts and longs are shown separately where both are traded.

## Results (research/tools/outside_test.py; output in data/research/outside.txt)

### 6 years, 2020-10 to 2026-10 (XRP, SOL, ETH, BTC; $150 at 2% a trade, 12% budget)

| System | Trades a year | Won | R a trade | $150 → | Max DD | 2020-23 | 2023-26 |
|---|---|---|---|---|---|---|---|
| **T1-L daily Donchian 20/10, long only** | 22 | 36% | **+1.71** | **+1,256%** | **30%** | +433% (DD 30%) | +155% (DD 26%) |
| T1-LS the same, long + short | 42 | 34% | +0.86 | +873% | 38% | +393% | +97% |
| T2-L daily SMA100, long only | 36 | 15% | +1.12 | +955% | 44% | +246% | +205% |
| T2-LS SMA100, long + short | 70 | 17% | +0.55 | +789% | 49% | +202% | +195% |
| T3-LS 4h Donchian, long + short | 248 | 31% | +0.21 | +1,139% | 71% | +252% | +252% |

- **Shorts lose in every trend system:** -0.12R daily Donchian, -0.07R SMA, -0.03R 4h.
- **T1-L is positive on every coin over the 6 years:** XRP +38.8R, SOL +65.2R, ETH +44.1R, BTC +78.8R.
- Its bad years are 2021-22 (-12R) and 2025-26 (-7.5R).
- T1-L on the common 4 years (2022-10 to 2026-10): +161%, DD 26%, 98 trades.

### Funding carry (optimistic, the basis ignored)

| Coin | 6 years, a year | Last 3 years, a year |
|---|---|---|
| ETH | +3.6% | +1.4% |
| BTC | +3.5% | +1.9% |
| XRP | +2.5% | -0.5% |
| SOL | +0.3% | -1.9% |

Not worth it.

### The agent's signals, 4 years (A 3% / B 2%, 12%)

| Rules | $150 → | DD | 2022-24 | 2024-26 |
|---|---|---|---|---|
| v6 now | -58% | 92% | +77% | -88% |
| **T7 v6 + one trade per coin (5m and 15m, first wins)** | **-57%** | 86% | -38% | -29% |
| C6 15m only + one per coin | +519% | 59% | +87% | +232% (DD 39%) |
| T6 C6 + the daily SMA100 trend | +126% | 58% | +3% | +119% |

One trade per coin does not fix v6 on its own: the first signal is often a 5m one (5m loses every year), and it blocks the 15m signals.

### A portfolio: half C6, half the daily trend system

| Period | C6 alone | Daily trend alone | Both, $75 each |
|---|---|---|---|
| 4 years | +519%, DD 59% | +161%, DD 26% | +340%, DD 44% |
| 2022-24 | +87%, DD 59% | +45%, DD 17% | +66%, DD 44% |
| 2024-26 | +232%, DD 39% | +80%, DD 26% | +156%, DD 30% |
