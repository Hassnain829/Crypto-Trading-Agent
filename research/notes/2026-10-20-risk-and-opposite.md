# 2026-10-20: 5% risk and a 20% open-risk budget; long and short open on one coin

Research only. Nothing in the running system was changed.

Tool: `research/tools/risk_conflict_test.py` (`risk`, `conflict`).

Samples:
- **Past:** the v6 backtest journal, 2026-07-13 to 10-18, 188 trades.
- **Forward:** a copy of the live journal, every demo signal since the demo started.

The forward replay with no budget reproduces the real demo to the cent ($208.90, 44 closed trades). The 12% budget only started on 2026-10-19.

## 1. Bigger risk (the demo account replayed, $150, every signal)

| Rules | Past | Past max DD | Forward | Forward max DD | Skipped (past / fwd) |
|---|---|---|---|---|---|
| now: A 3% / B 2%, 12% budget | +235% | 16.2% | +23% | 11.8% | 16 / 4 |
| A 3% / B 2%, 20% budget | +294% | 16.9% | +39% (= the real demo) | 8.2% | 4 / 0 |
| flat 5%, 12% budget | +357% | 29.2% | +20% | 28.1% | 65 / 24 |
| flat 5%, 20% budget | +616% | 36.2% | +52% | 21.5% | 36 / 13 |
| A 5% / B 3%, 20% budget | +544% | 26.3% | +46% | 14.2% | 12 / 4 |
| flat 5%, 20%, 20x leverage | +619% | 36.2% | +52% | 21.5% | 36 / 13 |
| flat 5%, 20%, 10% day stop | +612% | 37.7% | +77% | 10.5% | 56 / 21 |

Day-block bootstrap of the past trades: whole days redrawn 4,000 times. Trades of one 30-minute cluster share the budget. Long overlaps are ignored, so drawdowns are on the low side.

| Rules | Median return | Bad 5% | Median max DD | Bad 5% DD | P(DD > 30%) | P(DD > 50%) |
|---|---|---|---|---|---|---|
| now | +250% | +54% | 22% | 38% | 17% | 0% |
| A 3% / B 2%, 20% budget | +263% | +57% | 22% | 38% | 17% | 0% |
| flat 5%, 12% budget | +485% | +22% | 44% | 67% | 93% | 32% |
| flat 5%, 20% budget | +653% | +33% | 46% | 70% | 95% | 37% |
| A 5% / B 3%, 20% budget | +590% | +88% | 33% | 53% | 64% | 7% |

What the test shows:
- **Flat 5% on every trade** doubles the return, but the drawdown goes to 36% on the past and about 46% in the median bootstrap path. In about 1 path out of 3, the account falls by more than half.
  - The trades come in clusters of 3–4 signals in the same move, so 5% a trade means 15–20% on one move.
  - It also skips more signals: four trades fill a 20% budget.
- **Only the budget to 20% (risk stays A 3% / B 2%)** is the cleanest gain.
  - Past: +294% vs +235% at almost the same drawdown.
  - Forward: it is what the demo actually did before 2026-10-19 (+39% vs +23% with the 12% budget).
- **A 5% / B 3% with a 20% budget** is the middle way: about 2.3× the return, past drawdown 26%, bootstrap 7% chance of > 50%.
- Leverage 20x changes nothing; the budget binds first. The 10% day stop helped forward by luck (it skipped losing clusters) and not on the past.
- These are in-sample numbers for the tiers, in a mostly rising market, and the gate (100 trades) is not reached yet.

## 2. Long and short open on the same coin

Why it happens: the 5m and 15m charts each give their own signals, and nothing in the rules links them. A 5m flip against a 15m position is usually a pullback. The user does not want signals skipped (the 2026-10-18 skip and one-per-coin rules were not better in every period).

| | Past (v6) | Forward |
|---|---|---|
| Pairs (newer, older) | 74 | 19 |
| Newer won / older won | 37 / 23 | 13 / 2 |
| Both stopped | 11 (15%) | 4 (21%) |
| The newer (counter) trade | +0.277R (n = 58) | +0.690R (n = 16) |
| Counter A | +0.601R (23) | none yet |
| Counter B against an open A | -0.004R (13) | none yet |
| The older trade after a counter signal came | **-0.328R (50)** | **-0.646R (13)** |
| Older A | -0.061R (17) | none yet |
| Older B | **-0.466R (33)** | -0.646R (13, all B) |

Rules on the same trades:

**Size rules** (half size for some counter trades): none is better in both halves. Rejected.

**Close rules** (the new opposite signal is taken, and the older position is closed at its entry, own costs taken off):

| Close rule | Past half 1 | Past half 2 | Past R a trade | Past max DD | Fwd half 1 | Fwd half 2 | Fwd R a trade | Fwd max DD |
|---|---|---|---|---|---|---|---|---|
| keep both (now) | +30.4R | +23.1R | +0.285 | 8.5R | +13.2R | +3.1R | +0.372 | 5.2R |
| close the older position | +29.2R | +27.5R | +0.302 | 10.7R | +15.6R | +7.3R | +0.520 | 3.8R |
| **close the older position only if it is B** | **+34.5R** | **+26.2R** | **+0.323** | **7.8R** | +15.6R | +7.3R | +0.520 | 3.8R |
| close an older B only if it is losing | +31.8R | +25.8R | +0.306 | 7.8R | +15.8R | +5.6R | +0.486 | 4.4R |

"Close the older B" is better in both past halves and both forward halves, with a smaller drawdown. It also frees budget for the new signal. Today the ETH 5m short was skipped because the budget was full.

Caveats:
- The A/B split was chosen on this same data (older A -0.06R vs older B -0.47R).
- The forward sample has no A trades yet, so there the rule equals "close the older position".
- The plain "close the older position" failed in one half of the older history on 2026-10-18.

So it is a candidate for a shadow challenger, not for the demo directly.

## Open demo positions at 16:40 UTC

| Position | Quality | Now | History of this kind |
|---|---|---|---|
| ETH 15m long, 10-18 22:15 | B | +0.9R | older B with a counter signal (the ETH 5m short at 15:30): past -0.47R |
| XRP 15m long, 10-18 22:30 | B | +0.65R | the same (the XRP 5m short at 15:25) |
| XRP 15m long, 10-20 14:15 | A, squeeze fired | -0.3R | the strongest kind: A +0.58R, squeeze fired +0.41R |
| ETH 15m long, 10-20 14:15 | A, squeeze fired | -0.3R | the same |
| XRP 5m short, 15:25 | B, no squeeze | -0.25R | counter B against an open A: -0.004R, 38% won |
| SOL 5m short, 15:25 | B, no squeeze | -0.3R | an ordinary B (+0.13R), against the 1h and 4h trend; only 0.1% risk (budget full) |

Under the "close the older B" rule, the two 10-18 longs would have been closed at the 5m shorts:
- XRP at about +0.43R
- ETH at about +0.65R

The A longs would have stayed open.
