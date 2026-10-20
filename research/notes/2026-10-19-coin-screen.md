# Coin screen: which coins suit the strategy? Plan written before any result (2026-10-19)

The user wants to try more volatile coins. One or two good coins would replace ETH and take the Market_check layout (free for now). Only past data is used.

## Candidates

The candidates are liquid Binance USDT-M perpetuals (24 h volume above $100M and spread at most 0.02% on 2026-10-19) that were not tested before:

ZEC, NEAR, 1000PEPE, ENA, INJ, TIA, ARB, TAO

Not retested: SUI, LINK, ADA, DOGE, AVAX, BNB and BTC. They lost in the 2026-10-04 screen, and testing them again until one passes would be data snooping.

## Method

1. **TradingView history on Market_check (qteGoFhV).** The layout carries the AGENT charts' six studies, with the same script versions and inputs, read from AGENT-XRP:
   - Q-Trend v15.0
   - Klinger v2.0
   - VWAP v47.0
   - Zero Lag v4.0
   - ATP MACD v2.0
   - Dynamic Trendline Breakout v1.0

   Each coin loads 10,000 bars of 5m (about 35 days) and of 15m (about 104 days). Snapshots are read with the agent's own `read_history` and the catalog templates (scalp on 5m, scalp15 on 15m). The first 300 bars are skipped for warm-up. The Market_check layout's own studies and symbol are saved first and restored after.
2. **Binance candles** (1m, 5m, 15m, 1h) and funding are stored in data/research/coin_screen.db, never in the live journal.
3. **Replay** with the agent's SetupEngine and Tracker, the baseline rules (v0-773ea9) unchanged, and the same fees and slippage.

## Decision rule (fixed now)

A candidate qualifies only if, on its baseline taken trades, all of these hold:
- at least 40 trades
- positive expectancy in **both halves**, split by entry time
- profit factor at least 1.3
- the 1.5R target is hit in at least 42% of trades: the follow-through that LINK, ADA and SUI lacked (35–37%)
- expectancy at least that of the weakest current coin (XRP, SOL or ETH) over the same windows

At most two coins are chosen, the best by expectancy. The 5m and 15m results are reported separately as well. Coins that qualify start on the demo only after the user's approval; the forward test decides from then on.

## Results (2026-10-19)

**Windows:** 5m from 2026-09-16 and 15m from 2026-07-10, both to 2026-10-19. Baseline rules unchanged.

**Pipeline check:** XRP replayed through this pipeline gave +0.203R (79 trades, PF 1.41, target hit 46%). The live journal over the same windows has +0.231R (81 trades, PF 1.48, 46%). The screen reproduces the agent.

| Coin | Trades | Won | R / trade | PF | Target hit | Halves | Verdict |
|---|---|---|---|---|---|---|---|
| ETH (current) | 40 | 60% | **+0.401** | 2.06 | 50% | – | best current coin |
| SOL (current) | 71 | 55% | +0.321 | 1.72 | 51% | – | |
| XRP (current) | 81 | 52% | +0.231 | 1.48 | 46% | – | the weakest current coin sets the bar |
| ZEC | 193 | 45% | +0.075 | 1.13 | 44% | +0.10 / +0.05 | no: PF and expectancy below the bar |
| NEAR | 225 | 40% | -0.019 | 0.97 | 40% | -0.05 / +0.01 | no |
| TIA | 217 | 41% | -0.027 | 0.96 | 39% | -0.10 / +0.04 | no |
| ARB | 242 | 39% | -0.049 | 0.92 | 38% | +0.11 / -0.21 | no |
| 1000PEPE | 171 | 39% | -0.063 | 0.90 | 37% | -0.16 / +0.03 | no |
| ENA | 236 | 39% | -0.075 | 0.88 | 37% | -0.14 / -0.01 | no |
| TAO | 192 | 36% | -0.117 | 0.82 | 36% | -0.01 / -0.22 | no |
| INJ | 211 | 36% | -0.154 | 0.77 | 34% | -0.17 / -0.14 | no |

**No candidate qualifies.**
- The volatile coins give 2–5 times more trades, but their signals do not follow through: the target is hit 34–44% of the time, against 46–51% on the current coins.
- On them, almost every swing is wider than 1.5%, so the minimum-stop filter (the core of the edge on XRP, SOL and ETH) no longer separates the good signals from the chop. This is the same as LINK, ADA and SUI on 2026-10-04.
- ZEC is the only one positive in both halves. It is still a third of XRP's expectancy.
- **ETH is the best coin per trade. Keep it.**

**Possible next test, a new hypothesis not in this plan:** a minimum stop scaled to each coin's volatility, for example 1.5% × the coin's median 15m range divided by XRP's. It needs its own pre-registration and a single run.
