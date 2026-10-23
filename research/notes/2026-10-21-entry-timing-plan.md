# 2026-10-21: the 15m decides, the 5m times the entry (plan, written before the results)

The user's idea:
- The 15m signal decides the trade, with its stop and target, and the trade is a 15m trade.
- The 5m chart only times the entry, to get in at a better price (a dip) at the right moment.
- On top of C6 (one position per coin), or A1 (up to two same-direction 15m positions).

## Entries tested

The stop stays the 15m swing stop. "TP same" keeps the 15m trade's take-profit price, so a better entry earns more R. "TP 1.5R" sets the target 1.5R from the new entry.

| # | Entry | If no entry |
|---|---|---|
| E0 | now: limit at the next 1m open after the 15m confirmation | |
| E1 | limit 0.25R below the planned entry (above for shorts), valid 2 h; TP same | skipped |
| E1b | as E1, TP 1.5R from the fill | skipped |
| E2 | limit 0.5R better, valid 2 h; TP same | skipped |
| E3 | wait for the first 5m candle that closes against the trade (a dip), within 1 h; enter at the next 5m open; TP same | enter at the 1-hour mark |
| E4 | wait for the 5m Klinger histogram to turn back the trade's way after being against it (a dip that ends), within 2 h; enter at the next 5m open; TP same | skipped |

In every entry, a setup whose stop or target is touched before the entry is skipped.

## How the trades are run

- The exits are re-simulated with the agent's own simulator: maker fee on limit fills, taker on stops, slippage, funding, 72-hour timeout.
- The account policy is applied after the entries: C6, and A1 for the user's first question.
- Risk as today: A 3% / B 2%, 12%.

## Samples and judgement

Samples:
- XRP/SOL/ETH, 4 years, with in-sample 2022-10 to 2024-10 and out-of-sample 2024-10 to 2026-10.
- BTC, 4 years.
- The 10 check coins, 1.5 years.

An entry rule is better only if it beats E0 in both halves and does not lose on the replication samples.

## Results (research/tools/entry_timing_test.py; output in data/research/long4/entry_timing.txt)

### XRP/SOL/ETH, 4 years, $150 at A 3% / B 2%, 12%

| Entry | Policy | Entered | R a trade | 4 years | DD | 2022-24 | 2024-26 |
|---|---|---|---|---|---|---|---|
| E0 now | C6 | 100% | +0.061 | +519% | 59% | +87% | +232% (DD 39%) |
| E0 now | A1 | 100% | +0.060 | +617% | 64% | +176% | +160% (DD 52%) |
| E1 limit 0.25R, TP same | C6 | 60% | +0.083 | +504% | 57% | +67% | +262% |
| E1 limit 0.25R, TP same | A1 | 60% | +0.089 | +768% | 52% | +166% | +226% |
| E1b limit 0.25R, TP 1.5R from the fill | C6 | 60% | +0.022 | +26% | 60% | -26% | +71% |
| E2 limit 0.5R | C6 | 27% | +0.086 | -27% | 62% | -19% | +195% |
| **E3 first 5m dip candle (else 1 h)** | **C6** | 100% | **+0.067** | **+737%** | **57%** | **+94%** | **+331% (DD 43%)** |
| **E3 first 5m dip candle (else 1 h)** | **A1** | 100% | **+0.073** | **+1,307%** | 62.5% | **+221%** | **+326% (DD 58%)** |
| E4 5m Klinger turns back | C6 | 66% | +0.041 | +130% | 64% | +125% | +3% |
| E4 5m Klinger turns back | A1 | 66% | +0.057 | +324% | 69% | +251% | +21% |

### Replication

| Sample | E0 | E3 |
|---|---|---|
| BTC, C6 | -53% (-0.080R) | -49% (-0.070R) |
| BTC, A1 | -62% | -56% |
| Check coins, C6 | -61% (+0.013R) | -64% (+0.018R) |
| Check coins, A1 | -68% | -66% |

### Verdict

- **E3 is the only entry better than E0 in both halves**, with C6 and with A1. On the replication samples it is not worse per trade.
  - Its gain per trade is small (+0.006R with C6, +0.013R with A1), so part of it can be luck. Both halves agree, though.
- **Limit dips (E1, E2) miss 40–73% of the trades**, often the best ones.
- **Klinger timing (E4) fails in 2024-26.**
- **A1 + E3 has the highest return.** C6 + E3 has the lower drawdown in 2024-26 (43% vs 58%).
