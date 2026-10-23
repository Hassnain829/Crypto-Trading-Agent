# 2026-10-21: the second entry on a 5m dip, and ways to cut the drawdown

Tool: `research/tools/addon2_test.py`; output in data/research/long4/addon2.txt.

Setup:
- XRP/SOL/ETH, 4 years, today's risk A 3% / B 2%, 12% budget.
- The 15m opens a coin's first position, and opposite signals are skipped.

A bug in the first run let F1 add a signal to its own first position. It was fixed and F1 was re-run.

## Designs

| Design | Trades (2nd) | 2nd R | $150 over 4 years | DD | 2022-24 | 2024-26 |
|---|---|---|---|---|---|---|
| C6 one per coin, entry now | 2,093 | | +519% | 59% | +87% | +232% (DD 39%) |
| C6+E3 one per coin, 5m dip entry | 2,103 | | +737% | 57% | +94% | +331% (DD 43%) |
| A1+E3 two per coin, both on a 5m dip | 2,488 (452) | +0.082 | +1,307% | 63% | +221% | +326% (DD 58%) |
| **F1 the user's design: first now, 2nd 15m signal on a 5m dip** | 2,473 (449) | +0.088 | +793% | 63% | +214% | +185% (DD 48%) |
| F3 2nd from a 5m signal on a dip | 2,699 (634) | -0.027 | +103% | 67% | +146% | -17% |
| F4 add at a 0.5R dip of the first, same SL/TP | 3,540 (1,468) | +0.066 | +137% | 95% | -56% | +433% |

On BTC, every design loses (-48% to -78%). The second positions there make -0.14R to -0.20R.

## Drawdown levers

| Design + lever | $150 over 4 years | DD | 2022-24 | 2024-26 |
|---|---|---|---|---|
| C6 + corr2 | +829% | 54% | +140% | +287% (DD 35%) |
| C6 + corr2 + brake | +352% | 36% | +107% | +118% (DD 28%) |
| **C6+E3 + corr2** | **+1,127%** | **46%** | **+106%** | **+349% (DD 36%)** |
| C6+E3 + brake | +364% | 38% | +62% | +206% (DD 28%) |
| **C6+E3 + corr2 + brake** | +457% | **30%** | +80% | +205% (DD 28%) |
| C6+E3 at 1% | +241% | 33% | +51% | +126% |
| **A1+E3 + corr2** | **+1,825%** | 50% | +210% | +310% (DD 48%) |
| A1+E3 + corr2 + brake | +921% | 33% | +151% | +179% (DD 33%) |
| F1 + corr2 | +771% | 57% | +197% | +193% (DD 40%) |
| F1 + corr2 + brake | +344% | 38% | +129% | +94% (DD 27%) |

- **corr2 (at most 2 same-direction positions across XRP/SOL/ETH) is the best lever.** It raises the return and cuts the drawdown, because the three coins move together and the third same-direction position adds risk without spreading it.
- **The brake (half risk while 10% below the peak)** cuts the drawdown to 30–38% and roughly halves the return.

## Findings

- **The user's design (F1) works** (+793%). Timing the first entry on the dip as well (A1+E3) is better: +1,307%, and 2024-26 +326% vs +185%.
- **A second position from a 5m signal (F3) or a 0.5R averaging dip (F4) fails.**

## Max 2 per coin, up to 6 open (research/tools/six_positions_test.py)

A1+E3 on XRP/SOL/ETH, 4 years, A 3% / B 2%, 12% budget.

How many positions were open at an entry:

| Open | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| Share of entries | 28% | 36% | 25% | 8% | 2% | 1% |

The 12% budget caps the loss if every stop is hit at once.

| Same-direction cap across coins | Brake | $150 over 4 years | DD | 2022-24 | 2024-26 |
|---|---|---|---|---|---|
| none (up to 6 open) | no | +1,307% | 62.5% | +221% | +326% (DD 58%) |
| none (up to 6 open) | yes | +559% | 41.7% | +96% | +235% (DD 39%) |
| 4 | no | +1,097% | 61.9% | +238% | +302% |
| 3 | no | +1,147% | 63.4% | +199% | +251% |
| **2 (up to 4 open)** | **no** | **+1,825%** | **49.5%** | +210% | +310% (DD 48%) |
| 2 (up to 4 open) | yes | +921% | 33.4% | +151% | +179% (DD 33%) |

Allowing all 6 adds drawdown without adding return. A cap of 2 same-direction positions (4 open at most) is best on both.

## When many same-direction positions are open together (research/tools/crowd_test.py)

### Max 2 per coin, up to 6 open

$150 to $2,110, max DD 62.5%.

| Worst days | Loss |
|---|---|
| 2025-01-10 | -12.8% |
| 2026-03-02 | -11.1% |
| 2024-12-15 | -10.7% |

Stretches with 3 or more same-direction positions open happened 15 times in 4 years:

| At most open together | Times | Won | Average | Best | Worst |
|---|---|---|---|---|---|
| 3 | 10 | 60% | +2.3% | | -8.1% |
| 4 | 3 | 33% | -3.4% | | -6.2% |
| 5 | 2 | | +1.0% | | -7.7% |

The worst was 2023-01-18: 3 shorts open, -8.1%.

### B (max 2 same-direction across coins)

$150 to $2,887, max DD 49.5%.
- Worst day: -10.4%.
- Never more than 2 same-direction positions open together.

### What this means

- The 12% budget keeps one move's loss near 12%.
- The big drawdowns come from losing streaks over weeks, not from one move.

## The user's constraints (research/tools/user_design_test.py; output in data/research/long4/user_design.txt)

The rules:
- Every coin may always hold its first position.
- Up to 2 per coin, same direction, with a total same-direction cap of 4–6.
- Optionally the second only when the first is in profit.
- 5m dip entries; A 3% / B 2%, 12% budget.

| Design | Trades (2nd) | 2nd R | $150 over 4 years | DD | Worst day | 2022-24 | 2024-26 |
|---|---|---|---|---|---|---|---|
| one per coin (C6+E3) | 2,103 | | +737% | 57% | -10.7% | +94% | +331% (DD 43%) |
| 1st always, 2nd any time, max 6 | 2,488 (452) | +0.082 | +1,307% | 62.5% | -12.8% | +221% | +326% |
| **1st always, 2nd any time, max 5** | 2,479 (441) | **+0.097** | **+1,368%** | 62.5% | -12.8% | +226% | **+341% (DD 59%)** |
| 1st always, 2nd any time, max 4 | 2,452 (406) | +0.081 | +1,069% | 62.5% | -12.8% | +215% | +264% |
| 1st always, 2nd only if the 1st is in profit, max 5 | 2,403 (363) | +0.083 | +1,167% | 62% | -12.8% | +251% | +257% |
| 1st always, 2nd only if the 1st is at +0.5R, max 5 | 2,249 (189) | -0.068 | +459% | 64% | -12.8% | +80% | +214% |
| **max 5, 2nd any time + brake** | | | +646% | **41.7%** | **-8.7%** | +111% | +254% (DD 40%) |
| for comparison: B (max 2 same direction across coins; the 3rd coin may be blocked) | 2,488 | | **+1,825%** | **49.5%** | -10.4% | +210% | +310% (DD 48%) |

- **Adding only into a winning first position does not help.** The +0.5R condition makes the second entries late (-0.07R).
- **The best design under the user's constraints:** max 5 same-direction positions, the second at any time. Add the brake for a drawdown near 42%.
- **Letting every coin open its first position in the same direction costs return and drawdown** against B (+1,368% / DD 62% vs +1,825% / DD 50%), because the three coins move together.

## The user's final rules: at most 5 open in total (research/tools/total5_test.py)

The rules:
- Every coin may always hold its first position.
- A second same-direction position on a coin while fewer than 5 are open in total.
- Opposite signals skipped; 5m dip entries.

| | Trades (2nd) | $150 over 4 years | Max DD | Worst day | 2022-24 | 2024-26 |
|---|---|---|---|---|---|---|
| no brake | 2,476 (438, +0.092R) | +1,357% | 62.5% | -12.8% | +222% | +346% (DD 59%) |
| with the brake | 2,476 | +662% | 41.7% | -8.7% | +119% | +249% (DD 40%) |

The deepest fall:

| | From | Down to |
|---|---|---|
| no brake | $411 (2023-04-23) | $154 (2023-12-17), -62.5% over 8 months |
| with the brake | $313 | $182, -41.7% |

## Implementation check with the agent's own code (research/tools/validate_design.py, validate_entries.py)

Setup:
- The SetupEngine and AccountEngine as built, on a copy of the 4-year journal.
- XRP/SOL/ETH 15m.
- The user's rules: max 5 open, the first per coin always, max 2 a coin, opposite skipped, A 3% / B 2%, 12% budget, 10x.

Shadow trades of each entry:

| Entry | Entered | Not entered | R a trade | 2022-24 | 2024-26 |
|---|---|---|---|---|---|
| **dip + limit (built)** | 3,263 | 359 (342 limit not filled, 17 target before the dip) | **+0.038** | +0.042 | **+0.035** |
| now + limit (no dip) | 3,321 | 302 (limit not filled) | +0.035 | +0.057 | +0.016 |
| dip + market | 3,605 | 17 | +0.022 | +0.032 | +0.014 |

The demo account on the same trades:

| Entry | Brake | $150 over 4 years | Max DD | 2022-24 | 2024-26 |
|---|---|---|---|---|---|
| **dip + limit** | off | **+773%** | 62.7% | **+178%** | **+215% (DD 53%)** |
| dip + limit | on | +339% | 43.1% | +121% | +117% (DD 37%) |
| now + limit | off | +508% | 62.7% | +153% | +153% (DD 56%) |
| now + limit | on | +205% | 42.6% | +63% | +83% |
| dip + market | off | +323% | 70.0% | +62% | +170% |
| dip + market | on | +191% | 48.2% | +63% | +79% |

What the check shows:
- The research simulation (+1,357%) assumed every dip entry fills. With the agent's limit-fill rule, 342 entries miss, often the trades that run away. This lowers the return, but the ranking holds: the dip + limit entry beats entering at once in both halves.
- A market order after the dip pays more in costs than it gains from the filled runaways.
