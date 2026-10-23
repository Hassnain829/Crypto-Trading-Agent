# 2026-10-21: up to two same-direction positions per coin (the user's question)

The question:
- No opposite trades on a coin.
- A new signal in the same direction may open a second position, at most 2 per coin.
- The second position's target is either smaller, or the same price as the first trade's target.
- Should 5m signals be allowed to add too?

Tool: `research/tools/addon_test.py`; output in data/research/long4/addon.txt.

How it was run:
- The 15m signal always opens the first position.
- Opposite signals are skipped while the coin has a position.
- Changed targets were re-simulated on 1m candles with the agent's simulator. A check on 200 trades with their own target gave 0.0000R difference.
- Risk and budget as today: A 3% / B 2%, 12%.

## Main coins: XRP, SOL, ETH, 2022-10 to 2026-10

| Policy | Trades (add-ons) | R a trade | 2024-25 R | $150 over 4 years | DD | In-sample | Out-of-sample | Stops (rate) | Double stops | Worst losing streak |
|---|---|---|---|---|---|---|---|---|---|---|
| now | 7,193 | +0.008 | -0.022 | -58% | 92% | +77% | -88%, DD 96% | 4,042 (56%) | 563 | 22 |
| **C6 15m only, one per coin** | 2,093 | **+0.061** | **+0.045** | +519% | **59%** | +87% | **+232%, DD 39%** | 1,094 (52%) | **1** | **13** |
| A1 15m add-on, own 1.5R | 2,479 (455) | +0.060 | +0.023 | **+617%** | 64% | +176% | +160%, DD 52% | 1,299 (52%) | 27 | 15 |
| A2 15m add-on, 1.0R | 2,519 (471) | +0.055 | +0.017 | +543% | 66% | +152% | +155%, DD 46% | 1,285 (51%) | 23 | 15 |
| A3 15m add-on, the first trade's target | 2,485 (436) | +0.042 | +0.003 | +201% | 74% | +49% | +103%, DD 58% | 1,309 (53%) | 31 | 15 |
| B1 15m or 5m add-on, 1.5R | 2,990 (968) | +0.032 | +0.013 | +63% | 75% | +129% | -29%, DD 75% | 1,619 (54%) | 71 | 17 |
| B2 15m or 5m add-on, 1.0R | 3,081 (1,034) | +0.032 | +0.001 | +113% | 69% | +102% | +6% | 1,576 | 63 | 17 |
| B3 15m or 5m add-on, first target | 2,887 (838) | +0.031 | -0.020 | +18% | 85% | +99% | -41% | 1,578 | 78 | 17 |

"Double stops" counts a coin's second stop within the hour, i.e. both positions stopped in one move.

## Replication ($150)

| Sample | now | C6 | A1 | B1 |
|---|---|---|---|---|
| BTC, 4 years | -78% | -53% | -62% | -61% |
| 10 check coins, 1.5 years | -96% | -61% | -68% | -89% |

## What the test shows

- **A second 15m position (A1)** adds money over the whole 4 years: +617% vs +519%. But:
  - it is worse in the last two years: +160% vs +232%, DD 52% vs 39%
  - it is worse in 2024-25
  - it is worse on BTC and on the check coins
  - it has 27 double stops instead of 1
- **A smaller target (1.0R) or the first trade's target for the second position is worse** than its own 1.5R.
- **5m add-ons hurt everywhere**, as 5m signals do on their own: out-of-sample -29%.
- **C6 stays the best and safest:** one position per coin, 15m only. It has the lowest drawdown, every year positive, and a worst losing streak of 13 trades (about 23% at 2% risk).

## More one-position designs (research/tools/c6_variants.py; output in data/research/long4/c6_variants.txt)

All use 15m only, and never hold long and short together.

| Design | Trades | R a trade | Stop rate | $150 over 4 years | DD | 2022-24 | 2024-26 | BTC | Check coins |
|---|---|---|---|---|---|---|---|---|---|
| **C6 skip while a position is open** | 2,093 | **+0.061** | 52% | **+519%** | 59% | +87% | **+232%** | -53% | -61% |
| V1 C6 + B only with a squeeze release | 1,333 | +0.053 | 53% | +186% | 51% | +37% | +110% | -28% | -56% |
| V2 an opposite signal only closes | 2,424 | +0.040 | **37%** | +229% | 53% | +79% | +84% | -57% | -74% |
| V3 an opposite signal reverses | 3,042 | +0.024 | 38% | +69% | 75% | +104% | -17% | -67% | -89% |

- **C6 stays the best.**
- **V2** cuts the stop rate (37% vs 52%) and the drawdown a little, but earns less than half.
- **Reversing (V3) fails.**
