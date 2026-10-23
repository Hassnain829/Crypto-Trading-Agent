# 2026-10-20: every idea on 1.5 years and 13 coins (plan)

The user asked for every idea (P3 included) on the last 1.5 years, on all coins, before deciding.

## Data

- Binance USDT-M candles (1m, 5m, 15m) and funding, 2025-04-08 to 2026-10-20. Trades are counted from 2025-04-20.
- **Main coins:** XRP, SOL, ETH.
- **Check coins:** BTC, BNB, DOGE, LTC, ADA, LINK, AVAX, NEAR, SUI, ZEC.

## Indicators

Q-Trend, Klinger and Squeeze are computed in Python from their open Pine code (`research/tools/long_indicators.py`). This is a research-only exception the user approved on 2026-10-20; the agent keeps reading TradingView.

Validation against TradingView's own v6 history:

| Check | Result |
|---|---|
| candles | identical |
| Klinger sign | 99.4–99.7% |
| Squeeze state | 100% |
| Q-Trend signals | about 75% on the same bar, about 85% within one bar |

Q-Trend's trend line is path-dependent: it starts where the loaded history starts. Python runs with different start dates also agree only 80–100% with each other, so the TradingView chart itself has the same property.

On the trade level (XRP pilot, the v6 window):

| Chart | Same trades | TradingView | Python |
|---|---|---|---|
| 15m | 51 of 56 | +0.24R | +0.35R |
| 5m | 17 of 23 | | |

## Tiers

The Dynamic Trendline Breakout [RFX] is closed-source, so **quality A = open interest up more than 1% in the 4 h before**. The OI comes from TradingView's 1h `_OI` symbols, about 14 months.

## Engine, rules and judgement

The agent's own SetupEngine and Tracker run with the baseline v0-773ea9 rules.

The rules are the ones fixed earlier today (S0–S4, B1, B2, B4, D1, D2, P1–P4, and the risk variants), unchanged. B3 is left out because there is no 1h trend data.

How they are judged:
- R a trade, total R in each third (about 6 months each), max drawdown in R, and double stops.
- $150 at today's rules.
- A paired day-block bootstrap against "now".
- The main coins decide. The check coins show whether a result holds on other coins.

## Results

Validation on the v6 window (2026-07-13 to 10-18, XRP/SOL/ETH):

| | Trades | R a trade |
|---|---|---|
| TradingView | 188 | +0.285R |
| Python | 195 | +0.340R |

Same trades by chart:

| Chart | XRP | SOL | ETH |
|---|---|---|---|
| 15m | 51 of 56 | 45 of 47 | 19 of 33 |

The Python pipeline is not pessimistic.

### The current strategy over the long run (XRP, SOL, ETH)

| Period | Trades | R a trade | Gross R | $150 at today's rules | Max DD |
|---|---|---|---|---|---|
| 1.5 years (2025-04 to 2026-10) | 2,374 | +0.015 | +0.047 | $77 (-48%) | 89% |
| 4 years (2022-10 to 2026-10) | 7,193 | +0.008 | | $63 (-58%) | 92% |

The 4 years one at a time, each from $150:

| Year | Demo | Max DD |
|---|---|---|
| 2022-23 | -16% | 54% |
| 2023-24 | +104% | 53% |
| 2024-25 | -91% | 93% |
| 2025-26 | +6% | 72% |

- **5m signals lose in every year:** -0.004, -0.028, -0.015 and -0.009R.
- **15m signals:** +0.035R, positive in 3 of 4 years.
- **BTC:** -0.054R.
- **Check coins (1.5 years):** -0.023R; the demo falls 96%.
- **The +0.29R to +0.37R of 2026-07 to 10 was a good regime,** not the long-run edge.

### The ideas, 4 years, main coins (third 1 / 2 / 3 in R)

| Rule | R a trade | Thirds | Total | $150 | DD | P(beats now) |
|---|---|---|---|---|---|---|
| now | +0.008 | +29.4 / +4.9 / +23.1 | +57.4R | -58% | 91.8% | |
| **S1 15m decides** | **+0.039** | **+43.8 / +35.5 / +98.2** | **+177.5R** | **+719%** | 78.8% | **96%** |
| B4 skip B 5m against 15m | +0.037 | +43.8 / +35.5 / +92.9 | +172.2R | +610% | 79.5% | 96% |
| B2 skip B without squeeze | +0.030 | +16.4 / +52.8 / +41.5 | +110.7R | +197% | 61.8% | 74% |
| P3 the better wins | +0.008 | -29.4 / -11.7 / +80.5 | +39.4R | -27% | 90.4% | 41% |
| D1 no duplicates | -0.004 | | -16.6R | -69% | | 15% |
| S2 / S3 / D2 / P2 | about 0 or worse | | | -58% to -88% | | 5–22% |
| bigger risk (20% budget, 5%) | | | | -84% to -99% | | |

S1 is also the best rule on 1.5 years:
- Main coins: +0.059R vs +0.015R, $420 vs $77.
- Check coins: -0.002R vs -0.023R.

Lower risk on 4 years:

| Rules | 1% a trade | 0.5% a trade |
|---|---|---|
| S1 | +252%, DD 48% | +108%, DD 26% |
| 15m only | +125%, DD 43% | +61%, DD 23% |

The running challengers on 4 years:

| Challenger | Forward | 4 years |
|---|---|---|
| session_07_21 | +0.80R | -0.007R |
| session_13_21 | +0.76R | +0.010R |
| tf_15m | | +0.035R |
| trend15 (= S1) | +0.30R on 35 trades | +0.039R |

The forward leaders are regime artifacts. The learning loop's history screen (about 100 days) would not catch that.
