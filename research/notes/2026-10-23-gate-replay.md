# 2026-10-23: the new strategy on the agent's own TradingView data, BTC trend, no trades for 3 days

## Why the agent took no trade from 10-20 15:25 to 10-23

- The market fell about 4-5% in 48 hours (BTC from 84,700 on 10-21 18:00 to 81,000), slowly. The biggest BTC 5m candle in
  6 days was -0.74%, so the BTC-shock filter would not have fired.
- In 72 hours the baseline had 50 signals (23 short, 27 long). Every one was skipped by `min_stop_pct` (10-candle swing stop
  closer than 1.5%; stops were 0.25-1.42%).
- Taken anyway, they would have made -13.1R (shorts 21 closed: 6 won, -8.4R; longs -4.7R).
- The new design (dip15 in the shadow) also skipped all 9 of its 15m signals for the same reason (+2.5R on 7 if taken).
- Widening tight stops was already rejected (lessons 2026-10-20, stop_floor_1_5pct).

## BTC trend as a direction filter (rules fixed before looking)

On the design's 3,263 trades, 2022-10 to 2026-10 (data/replay/journal-news.db, v0-e78944):

| BTC factor | with | against | |
|---|---|---|---|
| daily close vs 50-day EMA | +0.035R (1,483) | +0.043R (1,701) | flips between halves |
| 4h close vs 50-bar EMA | +0.045R | +0.032R | flips between halves |
| 24 h move beyond ±3% | +0.137R (342) | +0.099R (274) | neutral days +0.019R (2,647); both halves |

- BTC's direction does not help.
- How much BTC moves does help: after a ±3% BTC day the design's trades did better in both directions and both halves.
- Open idea: a size factor on big BTC days. Not tested in the account yet.

## The new strategy replayed on the agent's TradingView snapshots from 2026-09-15 (research/tools/gate_replay.py)

- Data: the agent's own TradingView snapshots, backfill and live, copied to data/replay/journal-gate.db. Output:
  data/research/gate_replay.txt.
- Check: v0 replayed against the live agent since 10-02 matched on 438 of 453 signals. Every matched one had the same
  taken/skipped decision, and all 390 closed results were the same.
- The news filters never fired in this window (Fear & Greed 50-68, no 2% BTC 5m candle), so the design and the new strategy
  are identical here.

| 09-15 to 10-23 (38.7 days) | shadow | demo account, user's rules, $150 |
|---|---|---|
| v0 (current) | 127 trades, 3.3 a day, 54% won, +0.271R, PF 1.59 | 78 trades, $214.06 (+42.7%), DD 14.0% |
| new strategy | 65 trades, 1.7 a day, 57% won, +0.380R, PF 1.94 | 48 trades (21 short), $234.99 (+56.7%), DD 12.2% |

- Demo trades of the new strategy by week from 09-15: 7, 15, 8, 6, 9, 3.
- Gate of the new strategy counted from 09-15: 8 of 10 met. Missing: 65/100 trades, and live snapshot coverage 98.1%, the
  same as the real gate. Lower bound +0.137R, live preview +105.96 USDT, DD 6.1%.

## Python indicator copies vs TradingView, the new strategy, 09-15 to 10-19

- Python: 62 trades, +0.413R, PF 2.05, +25.6R.
- TradingView: 62 trades, +0.405R, PF 2.03, +25.1R.
- 49 trades were the same in both.
- The 4-year Python replay is a fair stand-in for TradingView on this window. These weeks are far better than the 4-year
  average of about +0.05R, so do not expect +0.38R to last.

## Later on 2026-10-23: per coin, earlier start dates, BTC moves over several candles

### Per coin, the new strategy from 09-15 (XRP/SOL/ETH; the demo does not trade BTC)

| Coin | shadow | demo |
|---|---|---|
| XRP | 29 trades, 59% won, +0.416R | 21 trades, +53.52 USDT |
| SOL | 22 trades, 64% won, +0.583R | 18 trades, +30.37 USDT |
| ETH | 14 trades, 43% won, -0.014R | 9 trades, +1.10 USDT |

ETH from 06-25 is positive: 40 trades, +0.184R.

### Gate by counting start date (data/research/gate_replay_<date>.txt; journal-gate-2026-06-25.db)

The live account in the preview is set to the demo rules: max 5, 2 a coin, opposite skipped.

| from | trades | R | live preview DD |
|---|---|---|---|
| 06-25 | 157 | +0.293R | 15.7% (fails) |
| 07-15 | 144 | +0.330R | 15.7% (fails) |
| 08-01 | 125 | +0.349R | 13.4% |
| 08-15 | 118 | +0.380R | 11.7% |
| 09-01 | 91 | +0.403R | 10.3% |
| 09-15 | 65 | +0.380R | 10.3% |

- With today's live limits (no position caps, opposite allowed), the DD from 08-01 is 15.5%, which fails.
- The user had named 1 Aug or June. Counting from 1 Aug, with live rules equal to the demo rules, meets 9 of 10 checks. Live
  snapshot coverage (98.1%) is the one left.

### The Fear & Greed filter, 06-25 to 10-23

- It removed 27 trades, 06-26 to 07-02, when the index was 11-19 (extreme fear). They made +5.9R.
- Demo from 06-25: without filters $150 -> $464.81 (+210%), DD 18.3%; with filters $409.50 (+173%), DD 18.3%.
- With the weak 4-year evidence (about 77%), this suggests the baseline without news filters and the filters as a shadow
  challenger.

### BTC moving 2%+ within 4-7 15m candles (the user's idea)

It happens on 2.2% of 15m candles. The design's 4-year trades after such a move: 471, +0.081R (2022-24 +0.171R, 2024-26
-0.005R), vs +0.030R otherwise. Nearly all of them go with BTC's move (2 against). A wait rule after such moves would cut
better-than-average trades, so it was not adopted.
