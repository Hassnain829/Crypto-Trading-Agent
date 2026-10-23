# 2026-10-20: one decision per coin from both charts (plan, written before the results)

The user's idea:
- Do not take both the 5m and the 15m signal of a coin.
- No duplicate in the same direction, and no long and short together.
- Decide from both charts which trade is better, and open only that one, on its own timeframe (its stop and target).

The 2026-10-18 test of "one position per coin" kept the first signal and had no quality tiers. This test adds the tiers and the squeeze flag, and picks the better signal.

## Score of a signal (fixed before the run)

| Flag | Points |
|---|---|
| quality A | 2 |
| squeeze released in its direction | 1 |

Signals that enter in the same minute are ordered by score, then the 15m first.

## Policies

| # | Policy |
|---|---|
| P0 | now: every signal, any number of positions per coin |
| D1 | no duplicates: a signal in the same direction as an open position of the coin is skipped; opposite signals as now |
| D2 | no duplicates, and an opposite signal closes an older B position (an older A stays) |
| P1 | one position per coin, the first wins: every new signal of the coin is skipped while a position is open |
| P2 | one position per coin, the newest wins: an opposite signal closes the open position and opens; duplicates are skipped |
| P3 | one position per coin, the better wins: duplicates are skipped; an opposite signal replaces the open position unless the open one has a higher score, in which case the new one is skipped |
| P4 | as P3, and a duplicate with a higher score replaces the open position (closed at the price of the new entry) |

A closed position is closed at the 1m open of the new signal's entry, with its own costs taken off.

## Samples and pass rule

The same three samples as 2026-10-20-coordination-plan.md:
- **Past:** v6 charts.
- **Forward:** the demo. There are no tiers before 2026-10-18, so P3 and P4 work like P2 there.
- **Replication:** the skipped signals, treated as if taken.

A policy passes only if:
- its total R beats P0 in both past halves, and
- it does not lose forward, and
- its R a trade on the replication sample is not worse than P0's.

Also reported:
- the demo account at today's rules (A 3% / B 2%, 12% budget)
- the max drawdown
- how often a coin had both a long and a short stopped

## Results (research/tools/one_position_test.py)

**Duplicates are weak in every sample.** These are signals in the same direction as a position already open on the coin:

| Sample | Duplicates | R a trade |
|---|---|---|
| Past | 52 | +0.059R |
| Forward | 16 | +0.012R |
| Replication | 189 | -0.244R (its average is -0.203R) |

| Policy | Past half 1 / half 2 | Past total | Past DD | Past demo | Forward total | Forward demo | Replication R a trade | Both SL (past / fwd) |
|---|---|---|---|---|---|---|---|---|
| P0 now | +30.4 / +23.1 | +53.5R | 10.0R | +236%, DD 16.1% | +16.4R | +24%, DD 11.9% | -0.203 | 6 / 1 |
| D1 no duplicates | +26.8 / +22.9 | +49.8R | 5.8R | +235%, DD 13.0% | +16.6R | +39%, DD 8.2% | -0.194 | 3 / 1 |
| D2 no duplicates + close older B | +28.8 / +20.5 | +49.2R | 7.4R | +231% | +19.9R | +48% | -0.216 | 1 / 0 |
| P1 one per coin, first wins | +27.3 / +14.3 | +41.6R | 5.9R | +171% | +9.6R | +22% | -0.208 | 0 / 0 |
| P2 one per coin, newest wins | +27.2 / +23.0 | +50.2R | 8.1R | +231% | +19.9R | +48% | -0.229 | 0 / 0 |
| **P3 one per coin, the better wins** | **+35.2 / +23.1** | **+58.3R** | **5.0R** | **+308%, DD 11.2%** | **+19.9R** | **+48%, DD 6.6%** | -0.212 | 0 / 0 |
| P4 P3 + a better duplicate replaces | +37.7 / +20.6 | +58.3R | 5.0R | +316% | +21.0R | +51% | -0.203 | 0 / 0 |

No policy passes all three checks strictly.

**P3 (the better signal wins)** has the best past and forward numbers:
- ROI +308% vs +236% past, +48% vs +24% forward.
- Half the drawdown in R.
- Long and short are never stopped together.

Its caveats:
- Past half 2 is only equal (+23.1R).
- The replication sample is slightly worse (-0.212 vs -0.203R a trade).
- The score uses quality A and the squeeze flag, which were both found on this past data.
- Forward it acts like P2, because there were no tiers before 10-18. P2 is worse than P0 on the past.

**D1 (no duplicates)** is the safest step:
- It is the only policy that points the same way in every sample.
- The money stays the same: past +235% vs +236%, forward +39% vs +24%.
- The drawdown drops from 10.0R to 5.8R.
- Replication improves (-0.194 vs -0.203R a trade).
- It fails the strict rule only because past half 1 has 3.6R less.

Both P3 and D1 are account rules, not signal rules. The engine's `max_positions_per_coin = 1` is P1, which is the worst of these. They need a forward check in a second (shadow) account before the demo changes. One position per coin also fits Binance's one-way position mode for Phase 6.
