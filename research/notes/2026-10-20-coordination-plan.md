# 2026-10-20: linking the 5m and 15m signals, and avoiding weak B trades (plan, written before the results)

The user asked how to solve "the 5m and 15m charts trade on their own", and how to avoid the weak B trades.

## Rules tested (fixed before the run)

Coordination of the charts of one coin:

| # | Rule | What it does |
|---|---|---|
| S0 | now | every signal on its own |
| S1 | 15m decides | a 5m signal is taken only in the direction of the 15m Q-Trend (its last buy/sell flip on a closed candle); 15m signals are always taken |
| S2 | one direction per coin, newest wins | a new signal closes every open opposite position of the coin at its entry |
| S3 | quality decides | as S2, but only older B positions are closed; an older A stays open |
| S4 | quality decides both ways | S3, and a new B signal against an open A position is not taken |

Avoiding weak B trades (skipped at entry):

| # | Rule |
|---|---|
| B1 | take only A trades |
| B2 | skip B trades without a squeeze release |
| B3 | skip B trades against the 1h trend |
| B4 | skip B 5m trades against the 15m Q-Trend |

## Samples and pass rule

Samples:
1. **Past:** v6 charts, 2026-07-13 to 10-18.
2. **Forward:** demo signals since the demo started. There were no tiers before 2026-10-18, so the quality rules cannot be judged there.
3. **Replication:** the skipped signals (stop under 1.5%) on the v6 charts, treated as if they were taken.

What is measured:
- Total R and R a trade.
- Max drawdown in R.
- The demo account at today's rules (A 3% / B 2%, 12% budget, event simulation; cross-checked against the account engine for S0).

A rule passes only if:
- its total R beats S0 in both past halves, and
- it does not lose in the forward sample, where the sample can judge it, and
- the replication sample points the same way.

Skipping signals is shown for the user's decision; the demo takes every signal today.

## Results (research/tools/coordination_test.py)

Cross-check: the event simulation of S0 gives $504.49 on the past ($503.09 in the account engine) and $185.42 forward ($184.89).

| Rule | Past half 1 | Past half 2 | Past total | Past demo | Forward total | Forward demo | Replication R a trade (S0 -0.203) | Verdict |
|---|---|---|---|---|---|---|---|---|
| S0 now | +30.4R | +23.1R | +53.5R | +236%, DD 16.1% | +16.4R | +24% | -0.203 | |
| S1 15m decides | +28.6 | +16.7 | +45.4 | +200% | +9.3 | +18% | -0.221 (worse) | **fails** everywhere |
| S2 newest wins | +29.2 | +27.5 | +56.8 | +321%, DD 17.2% | +22.9 | +58% | -0.233 (worse) | fails (past half 1, replication) |
| S3 close the older B | **+34.5** | **+26.2** | **+60.7** | **+335%, DD 15.9%** | **+23.9** | **+62%** | -0.210 (slightly worse) | passes past and forward, **not replicated** |
| S4 S3 + no new B against an open A | +38.6 | +19.9 | +58.5 | +350% | +22.9 | +59% | -0.217 | fails (past half 2) |
| B1 only A | +21.4 | +15.7 | +37.1 | +153%, DD 9.0% | n/a | n/a | A -0.073 (tier replicates) | B trades add money: no |
| B2 skip B without squeeze | +25.2 | +25.1 | +50.4 | +226%, DD 13.0% | n/a (squeeze since 10-20) | n/a | -0.186 | fails (half 1); B without squeeze ≈ +0.05R |
| B3 skip B against the 1h trend | no 1h data on the past charts | | | | +4.8 | +11% | n/a | fails forward |
| B4 skip B 5m against 15m | +26.6 | +21.7 | +48.3 | +194% | +9.3 | +18% | -0.198 | fails |

For skip rules, the replication column is the R a trade of what is kept. In a losing sample any skip lowers the total loss, so only the R a trade is compared there.

What the results show:
- **Making 5m follow the 15m (S1, B4) loses money.** The 5m signals against the 15m trend are pullback trades that pay (+0.25R on 2026-10-18, again here).
- **One direction per coin (S2)** helps forward, but not in past half 1, and it is worse on the replication sample.
- **Closing the older B (S3)** is the only coordination rule better in all four halves. On the skipped signals it is slightly worse (-0.210 vs -0.203R a trade). There, tight-stop chop makes the newer signal no better informed.
  - So it is a shadow-challenger candidate, not a demo change.
- **B trades are worth taking.**
  - Overall: +0.13R a trade on the past, +16.4R in total.
  - B trades that never get an opposite signal: about +0.35R (91 trades).
  - B trades that do get an opposite signal: -0.47R (33 trades).
  - At entry it cannot be known which kind a trade will be. The opposite signal is the new information, which is why closing at that moment works better than skipping at entry.
- **The only weak B group found at entry is B without a squeeze release:** about +0.05R on 66 past trades. Squeeze is recorded since 2026-10-20, so check it forward (early November) before any skip or size change.
