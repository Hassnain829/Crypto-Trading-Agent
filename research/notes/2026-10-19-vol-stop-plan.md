# Volatility-scaled minimum stop: plan written before any result (2026-10-19)

The user asked for a test only, with no change to the agent.

## Hypothesis

The 1.5% minimum stop works on XRP, SOL and ETH because it skips signals whose swing is small compared with the coin's noise. On volatile coins almost every swing is wider than 1.5%, so the filter stops filtering. Scaling the minimum stop with each coin's volatility could bring the edge back on them.

## Rule

- **Volatility at the decision:** the median 15m candle range ((high - low) / close) over the 672 closed 15m candles (7 days) before the decision, from the venue's candles.
- **Minimum stop** = 1.5% × volatility / 0.53%. 0.53% is XRP's median 15m range in the 30-day pre-screen of 2026-10-19, where 1.5% is the tuned value.
  - XRP at its typical volatility keeps about 1.5%. ZEC (about 0.72%) needs about 2.0%. NEAR (about 1.32%) needs about 3.7%.
- **A signal qualifies** when its swing stop (the distance from the order price to the 10-candle stop) is at least this minimum.
- **Outcomes:** the trades already simulated by the screen (taken, plus the signals skipped by the 1.5% rule, which are simulated too). A limit order that did not fill stays out.

## Samples

- The eight candidates in data/research/coin_screen.db (ZEC, NEAR, 1000PEPE, ENA, INJ, TIA, ARB, TAO), over the same windows as the coin screen.
- XRP, SOL and ETH from the live journal, for comparison only; their rule is not being changed.

## Decision rule (the same as the coin screen)

A candidate qualifies only if it has:
- at least 40 trades
- positive expectancy in both halves
- profit factor at least 1.3
- target hit at least 42%
- expectancy at least +0.231R (XRP's, the weakest current coin with the 1.5% rule over these windows)

One run only. Nothing is tuned after seeing the results.

## Results (2026-10-19, one run)

| Coin | 1.5% rule | Scaled minimum stop (its median) | Halves | Verdict |
|---|---|---|---|---|
| **ZEC** | +0.075R (193, PF 1.13, target 44%) | **+0.211R** (136, 50% won, PF 1.41, target 49%; 1.89%) | +0.13 / +0.30 | **Near miss:** every check passes except expectancy ≥ +0.231R (by 0.02R). For reference, XRP through the same screen pipeline: +0.203R |
| ENA | -0.075R | +0.027R (152; 2.18%) | +0.02 / +0.04 | no (PF, target) |
| NEAR | -0.019R | +0.008R (130; 2.59%) | +0.01 / +0.01 | no |
| ARB | -0.049R | +0.043R (168; 1.96%) | +0.10 / -0.02 | no |
| TAO | -0.117R | -0.015R (163; 1.63%) | – | no |
| INJ | -0.154R | -0.090R (136; 2.15%) | – | no |
| TIA | -0.027R | -0.121R (149; 2.22%) | – | no |
| 1000PEPE | -0.063R | -0.160R (161; 1.49%) | – | no |
| XRP (current) | +0.231R (81) | +0.075R (151; 0.95%) | – | the scaled rule is worse |
| SOL (current) | +0.321R (71) | -0.084R (156; 0.96%) | – | the scaled rule is worse |
| ETH (current) | +0.401R (40) | -0.036R (158; 0.73%) | – | the scaled rule is worse |

**Conclusions:**
- Scaling the minimum stop up helps the volatile coins, most of all ZEC, which becomes about as good as XRP. Nothing passes the pre-set bar.
- On the current coins the scaled minimum falls below 1.5%, and that destroys the edge (the same as min_stop_1pct on 2026-10-04): **the 1.5% floor itself matters.**
- So the sensible form would be **max(1.5%, scaled)**: the current coins unchanged, volatile coins stricter. That is a new hypothesis and was not run here.
- No change to the agent (the user asked for a test only).
