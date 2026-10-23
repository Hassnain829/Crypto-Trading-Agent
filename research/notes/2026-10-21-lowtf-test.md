# 2026-10-21: the current strategy on 1m and 3m charts

Tool: `research/tools/lowtf_test.py`; output in data/research/lowtf_result.txt.

Setup:
- XRP/SOL/ETH, 2025-10-20 to 2026-10-20.
- Python copies of Q-Trend, Klinger and Squeeze on 1m and 3m candles.
- The agent's engine with the baseline rules: stop at least 1.5%, limit entry, 1.5R.

| Chart | Taken trades | A day | Won | R a trade | Skipped by the 1.5% stop (if taken) | Fees + slippage |
|---|---|---|---|---|---|---|
| 1m | 293 | 0.8 | 34% | **-0.189** | 30,458 at -0.335R | 0.30R a trade |
| 3m | 558 | 1.5 | 42% | **+0.008** | 8,977 at -0.188R | 0.16R a trade |
| 5m (same year) | 737 | 2.0 | 42% | -0.014 | | |
| 15m (same year) | 767 | 2.1 | 45% | **+0.058** | | |

What the test shows:
- The lower the chart, the worse the strategy.
- On 1m, costs alone take about 0.3R a trade.
- Only 15m is positive. 1m and 3m are not worth trading with these rules.
