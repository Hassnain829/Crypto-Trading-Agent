# 2026-10-29: today's tests split by coin (the user asked: were these tests checked on each coin?)

Tool: research/tools/per_coin_check.py. Output: data/research/per_coin_check.txt.

**Background:**
- The tests of 2026-10-29 pooled XRP, SOL and ETH.
- Their pass rules checked the two halves and since Aug, but did not show each coin.
- Since Aug a coin has only 30-52 trades, so per-coin numbers there are noisy.

## 1. Smart targets, runners, early exits, ML

R a trade minus the fixed plan's.
- **The plan itself:** 4 years XRP +0.054R, SOL +0.012R, ETH +0.070R; since Aug +0.288R, +0.376R, +0.330R.
- **No version beats the plan on a coin both over 4 years and since Aug.** Most versions are better on 0 or 1 of the 3
  coins.
- The few one-coin gains reverse in the other window:
  - XRP with a 3R target: +0.021R over 4 years, -0.165R since Aug.
  - XRP with the ML target model: +0.029R / -0.188R.
  - ETH with S/R front: +0.004R / +0.110R. It is about 0 over 4 years.
  - SOL with the 4 h no-progress exit: +0.008R / -0.070R.

## 2. Regime and volatility factors

High minus low, 4 years (2022-24 / 2024-26) | since Aug.

| factor | XRP | SOL | ETH |
|---|---|---|---|
| F1 HMM daily | +0.144 (+0.124 / +0.178) \| -0.991 | +0.215 (+0.135 / +0.358) \| n/a | +0.054 (-0.071 / +0.151) \| n/a |
| F4 BTC volatility | -0.158 (-0.050 / -0.231) | -0.005 | -0.024 |
| F5 coin volatility | -0.146 (-0.151 / -0.150) \| +0.008 | -0.040 (-0.115 / +0.021) \| +0.504 | -0.148 (+0.085 / -0.313) |
| F6 coin 24h/30d | -0.022 (+0.078 / -0.078) \| -0.156 | +0.166 (+0.193 / +0.134) \| -0.283 | +0.042 (-0.023 / +0.070) \| -0.272 |

- A few coin-and-factor pairs have the same sign in both 4-year halves: F1 on XRP and SOL, F5 on XRP, F6 on SOL, F4 on
  XRP.
- Each one fails since Aug, or on the other coins (regime_replicate.py).
- There are 18 coin-and-factor pairs. If the sign were random, about 1 in 4 would agree in both halves by chance (4-5
  pairs), and about that many do. Per-coin rules from these would be curve-fitting.
- F1's gain is mostly the BTC 12 h factor that tier A already uses (regime-plan note).

## 3. Tier A per coin, and the scoreboard's picks

| coin | tier A vs B, 4 years | tier A vs B, since Aug | scoreboard's 3% picks vs tier A, 4 years |
|---|---|---|---|
| XRP | +0.195 vs +0.018 | +0.583 vs +0.158 | +0.201 vs +0.195 |
| SOL | +0.124 vs -0.010 | +0.841 vs +0.212 | -0.084 vs +0.124 |
| ETH | +0.143 vs +0.052 | +0.093 (7 trades) vs +0.401 | -0.005 vs +0.143 |

- **Tier A is better on every coin over 4 years**, and on XRP and SOL since Aug.
- ETH's reversal since Aug rests on only 7 tier-A trades.
- The scoreboard's picks matched tier A on XRP and were much worse on SOL and ETH.

## Conclusion

- Split by coin, every conclusion of the day holds.
- Nothing works on one coin in both windows.
- Do not make per-coin exit, target or sizing rules from these tests.
