# 2026-10-20: every idea of today on the real demo signals

Tool: `research/tools/demo_ideas_test.py`. The live journal is only read.

## Sample

- 51 demo signals, 2026-10-05 to 10-20.
- 7 were still open; they are valued at the 17:20 UTC price.
- The quality of the 43 signals before 10-18, and their squeeze, were taken from the same signal on the v6 charts (all 43 found).
- Result: 14 A and 37 B; the squeeze fired on 20.

The simulation applies today's rules from the start (A 3% / B 2%, 12% budget). The real demo had no budget before 10-19, so "now" here is $193 rather than the real $208.90 plus the open positions.

## The demo's own groups

| Group | Trades | Won | R a trade |
|---|---|---|---|
| all | 51 | 53% | +0.316 |
| quality A | 14 | 57% | +0.515 |
| quality B | 37 | 51% | +0.241 |
| squeeze fired | 20 | 60% | +0.537 |
| squeeze not fired | 31 | 48% | +0.174 |
| B without squeeze | 22 | 41% | -0.015 |
| duplicates (same direction already open) | 18 | 39% | -0.015 |
| counter signals (opposite already open) | 19 | 63% | +0.571 |

## The rules

| Rule | Trades | R a trade | Half 1 / half 2 | Total | Demo $150 | DD | Both SL | P(beats now) |
|---|---|---|---|---|---|---|---|---|
| now | 51 | +0.316 | +12.6 / +3.5 | +16.1R | +29% | 10.6% | 1 | |
| S1 15m decides | 33 | +0.319 | +8.3 / +2.2 | +10.5R | +13% | 10.6% | 0 | 18% |
| S2 newest wins | 51 | +0.421 | +15.0 / +6.5 | +21.5R | +64% | 7.2% | 0 | 84% |
| S3 close the older B | 51 | +0.373 | +14.0 / +5.0 | +19.0R | +47% | 8.2% | 0 | 79% |
| S4 S3 + no new B against an open A | 48 | +0.399 | +12.5 / +6.6 | +19.1R | +49% | 8.2% | 0 | 78% |
| B1 only A | 14 | +0.515 | +0.4 / +6.8 | +7.2R | +9% | 7.7% | 0 | 24% |
| B2 skip B without squeeze | 29 | +0.568 | +9.8 / +6.7 | +16.5R | +32% | 7.2% | 0 | 53% |
| B3 skip B against the 1h trend | 27 | +0.429 | +8.3 / +3.3 | +11.6R | +15% | 6.9% | 1 | 33% |
| B4 skip B 5m against 15m | 38 | +0.406 | +9.8 / +5.6 | +15.4R | +20% | 8.6% | 1 | 48% |
| D1 no duplicates | 35 | +0.481 | +11.5 / +5.3 | +16.8R | +45% | 9.2% | 1 | 55% |
| D2 no duplicates + close older B | 35 | +0.485 | +11.8 / +5.2 | +17.0R | +47% | 8.2% | 0 | 55% |
| P1 one per coin, first wins | 28 | +0.350 | +11.1 / -1.3 | +9.8R | +23% | 10.2% | 0 | 23% |
| P2 one per coin, newest wins | 35 | +0.527 | +11.8 / +6.7 | +18.4R | +53% | 7.2% | 0 | 61% |
| P3 one per coin, the better wins | 35 | +0.527 | +11.8 / +6.7 | +18.4R | +53% | 7.2% | 0 | 61% |
| P4 P3 + a better duplicate replaces | 36 | +0.457 | +8.2 / +8.3 | +16.5R | +46% | 7.2% | 0 | 51% |

P(beats now) comes from a paired day-block bootstrap of the R difference. 51 trades over 15 days is a small sample: nothing reaches 90%.

Risk rules on the same signals (every signal):

| Rules | Demo $150 | Max DD |
|---|---|---|
| A 3% / B 2%, 12% budget (now) | +29% | 10.6% |
| A 3% / B 2%, 20% budget | +38% | 9.2% |
| flat 5%, 12% budget | +24% | 28.1% |
| flat 5%, 20% budget | +62% | 21.6% |
| A 5% / B 3%, 20% budget | +51% | 15.5% |

## Across the three samples (past v6, replication, demo)

Consistent everywhere:
- Duplicates are about 0R (+0.06 past, -0.24 replication, -0.015 demo).
- B without squeeze is about 0R (+0.05 past, -0.015 demo).
- The newer of two opposite signals wins.
- 15m decides (S1), only A (B1) and first wins (P1) lose.

Best candidates:

| Candidate | Past | Demo | Replication |
|---|---|---|---|
| P3 one per coin, the better wins (the user's idea) | +308% vs +236% | +53% vs +29% | slightly worse |
| S3 close the older B | +335% | +47% (P 79%) | slightly worse |
| D1 no duplicates | same money, lower DD | +45% | better |
