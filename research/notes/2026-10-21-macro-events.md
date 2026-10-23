# 2026-10-21: FOMC and 8:30 New York news days, 4 years

Tool: `research/tools/events_test.py`; output in data/research/events_result.txt.

## Events

- **FOMC:** 32 statement days (2022-11 to 2026-09), at 14:00 New York time.
- **8:30 news days, found in the data:** 156 (CPI, jobs data, PPI, GDP, PCE). A day counts when BTC's 1m candle at 8:30 New York time was at least 4x that minute's 30-day median.

| Year | 8:30 news days |
|---|---|
| 2022 (from October) | 14 |
| 2023 | 34 |
| 2024 | 36 |
| 2025 | 42 |
| 2026 (to October) | 31 |

## The hour after the event (median)

"Normal" is the same hour on 10 quiet weekdays before the event.

| Event | Coin | 1-hour range | Normal | Both ways 0.5%+ | First 15 min wrong way | 4-hour move |
|---|---|---|---|---|---|---|
| FOMC | BTC | 1.77% | 0.60% (x3.0) | 38% | 16% | 0.91% |
| FOMC | XRP | 2.33% | 0.85% (x2.7) | 38% | 22% | 1.18% |
| FOMC | SOL | 2.98% | 1.14% (x2.6) | 41% | 16% | 2.42% |
| FOMC | ETH | 2.36% | 0.80% (x3.0) | 38% | 16% | 1.39% |
| 8:30 news | BTC | 1.33% | 0.64% (x2.1) | 18% | 25% | 1.04% |
| 8:30 news | XRP | 1.61% | 0.91% (x1.8) | 25% | 25% | 1.11% |
| 8:30 news | SOL | 2.23% | 1.15% (x1.9) | 37% | 29% | 1.83% |
| 8:30 news | ETH | 1.73% | 0.83% (x2.1) | 31% | 28% | 1.31% |

## The planned design's trades

2,461 demo trades (XRP/SOL/ETH, the user's rules):

| Trades | Count | Won | Stopped | R a trade |
|---|---|---|---|---|
| all | 2,461 | 45% | 53% | +0.064 |
| open over an FOMC statement | 54 | 54% | 43% | **+0.191** |
| open over an 8:30 release | 209 | 49% | 40% | **+0.164** |
| open over no event | 2,198 | 44% | 54% | +0.052 |
| entered within 1 h of FOMC | 7 | 71% | 14% | +1.152 |

## Rules ($150, A 3% / B 2%, 12% budget)

| Rule | 4 years | Max DD |
|---|---|---|
| **R0 none** | **+783%** | 62.7% |
| R1 no entry ±1 h around FOMC | +647% | 62.5% |
| R2 no entry ±1 h around FOMC and 8:30 news | +540% | 63.0% |
| R3 R1 + close open trades 15 min before FOMC | +610% | 62.9% |
| R4 R2 + close before every event | +560% | 65.6% |
| R5 no entry 4 h before to 2 h after FOMC | +560% | 61.7% |

## What this means

- Events triple the hourly range. On FOMC, about 4 in 10 hours sweep 0.5% both ways.
- **The design's wide swing stops (at least 1.5%) are rarely reached by those wicks.** The bigger moves reach the 1.5R targets more often.
- **Trades open over events did better, not worse.** Every keep-away rule lost money without cutting the drawdown.
- **For live trading,** the risk is fills, not direction: stop slippage in a spike can exceed the 0.02% the backtest assumes. Use exchange-side stops, and measure the slippage in the demo and on the testnet.
