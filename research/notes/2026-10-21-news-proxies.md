# 2026-10-21: daily news, measured through price shocks and the Fear & Greed Index

Tool: `research/tools/news_proxy_test.py`; output in data/research/news_proxy_result.txt.

Sample: the planned design's 2,461 demo trades (XRP/SOL/ETH, 4 years), $150 at A 3% / B 2%, 12% budget. Replication: the 10 other coins over 1.5 years (15m, max 2 a coin, opposite skipped).

## A. Price shocks

- **Coin shock:** a 15m candle at least 3x the day's median. XRP 4,925, SOL 4,005, ETH 6,195.
- **BTC shock:** BTC moving 2% or more within one 5m candle. 69 in 4 years.

| Trades | Count | R a trade |
|---|---|---|
| entered within 1 h after a coin shock | 819 | +0.021 |
| entered within 1 h after a BTC 2% move | 39 | **-0.216** (replication: 22 at **-0.836**) |
| entered after no shock | 1,639 | +0.084 |

| Rule | Half 1 | Half 2 | $150 over 4 years | DD |
|---|---|---|---|---|
| now | +63.1R | +95.6R | +783% | 62.7% |
| wait 1 h after a coin shock | +42.9R | +99.0R | +847% | 48.1% |
| **wait 1 h after a BTC 2% move** | **+65.0R** | **+102.1R** | **+985%** | **55.3%** |
| wait after either | +39.1R | +99.0R | +782% | 48.1% |

## B. Fear & Greed (alternative.me, daily since 2018)

| Index at entry | Main: R a trade (count) | Main: longs | Replication: R a trade (count) |
|---|---|---|---|
| extreme fear < 25 | +0.133 (455) | +0.114 | -0.081 (1,170) |
| fear 25-44 | +0.159 (466) | +0.152 | +0.049 (685) |
| neutral 45-55 | -0.022 (421) | -0.051 | +0.101 (432) |
| greed 56-75 | +0.076 (890) | +0.071 | +0.047 (1,135) |
| **extreme greed > 75** | **-0.149 (229)** | **-0.409** (101) | **-0.479** (25) |

| Rule | Half 1 | Half 2 | $150 over 4 years | DD | Replication R a trade |
|---|---|---|---|---|---|
| now | +63.1R | +95.6R | +783% | 62.7% | +0.007 |
| **F1 no trades below 20 or above 80** | **+74.1R** | **+99.7R** | **+1,272%** | 62.7% | **+0.034** |
| F2 contrarian | +69.8R | +37.5R | +327% | 63.2% | |
| F3 with the crowd | -5.6R | +54.9R | +85% | 74.1% | |

## Verdict

- **"Wait 1 h after a BTC 2% move"** is better in both halves and holds on the other coins. It affects few trades (39 in 4 years).
- **"F1, no trades in Fear & Greed extremes"** is better in both halves and holds on the other coins, though not for the same reason:
  - Main coins: the bad trades are the extreme-greed longs.
  - Other coins: the bad trades are the extreme-fear ones.
- **The coin-shock wait** cuts the drawdown but loses in half 1. Not proven.

**Next:** both candidates should run through the agent's own engine on 4 years before any change. Fear & Greed is new external data (alternative.me) and needs the user's approval, as open interest did.
