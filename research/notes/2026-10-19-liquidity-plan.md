# Liquidity ideas: test plan, written before any result was seen (2026-10-19)

The user approved testing three liquidity ideas on past data only. Ideas that pass go to the forward test. Nothing changes in the agent until then.

## Data and sample

- **Trades:** the baseline's (v0-773ea9) taken, closed trades in the journal: history from the backfill plus the forward test, on XRP, SOL and ETH, 5m and 15m.
- **Decision time:** the close of the confirmation candle. Only data that was closed at that moment is used.
- **Halves:** the sample is split by time into two equal halves.
- **Cluster bootstrap:** trades entered within 30 minutes of each other are resampled together.

## Pass rule (the same for every flag)

A flag splits the trades into two groups. It passes only if all of these hold:

1. The difference in expectancy is at least **0.15R**, in the same direction, in **both halves**.
2. Each group has at least 25 trades in each half.
3. The longs and the shorts do not point in opposite directions.

At most two definitions per idea are tested. Unrecorded extra tries count as tests.

## Idea 1: liquidity pool in the way of the target (Binance candles)

The pools are computed at the decision time. For a long, the levels above the entry are used; for a short, the levels below.

- **1a, prior range:** the previous UTC day's high (or low), and the high (or low) of the 4 hours before the decision. Flag "blocked" when one of them lies between the entry and the target.
- **1b, equal highs/lows:** in the last 24 hours, two or more 5m swing highs (a high above the 2 candles on each side) within 0.10% of each other. A swing low is the same for shorts. The pool is the highest of them (or the lowest for shorts). Flag "blocked" when such a pool lies between the entry and the target.

**Follow-up only if a blocked flag passes:** a target just before the first blocking pool.
- The target moves to the pool minus 0.05%, if that is still at least 0.75R from the entry.
- The trade is replayed on 1m candles with the project's simulator (same fees, slippage and limit-entry rules).

## Idea 2: open interest context (TradingView OI history)

- **Data:** the 15m open interest of each coin's Binance perpetual. It is read from TradingView on the Market_check layout, never on the AGENT layouts.
- **Check first:** the TradingView values are compared with Binance's own 30-day OI history.
- **Measure:** at the decision time, the OI change over the last 4 hours (16 closed 15m bars) and the price change over the same 4 hours.
  - **2a, OI with the trade:** OI rising by more than 1% → "new positions are opening".
  - **2b, regime:** price and OI over the last 4 h. Up/up = new longs. Up/down = short covering. Down/up = new shorts. Down/down = long liquidation. Each trade is labelled by whether its direction goes with or against the regime.

## Idea 3: liquidation flush (proxy from the same OI data)

There is no free liquidation history, so a forced-closing proxy is used: a 15m bar where OI falls by more than 1.5% while the price moves more than 1%.

- **3a:** a flush **against** the trade's direction in the 2 hours before the decision. For a long: OI falls and the price falls, so longs were liquidated. That is capitulation, which can favour a reversal.
- **3b:** a flush **with** the trade's direction in the same 2 hours. The move may already be exhausted.

## After the tests

If a flag passes, it becomes a size tier, as the Trendline one did. Trades are never skipped (the user's rule). A target change goes to a challenger first. Results go into this file and into research/lessons.md.

## Results (2026-10-19, past data only)

**Samples:**
- 254 taken baseline trades on XRP, SOL and ETH. Idea 1 uses Binance candles. 217 of the trades fall inside the TradingView OI history, which starts 2026-07-07.
- For a robustness check, 977 skipped baseline signals (taken = 0, the minimum-stop filter): different trades with simulated results.
- **OI data check:** TradingView `BINANCE:<coin>USDT.P_OI` (15m, 10,009 bars per coin) against Binance's 30-day openInterestHist. XRP and ETH match closely (correlation of 15m changes 0.93 and 0.99, level gap below 1%). SOL is looser (0.51, gaps up to 3%).

| Flag | Taken trades: flag vs other | Halves (difference) | Skipped signals: flag vs other | Verdict |
|---|---|---|---|---|
| 1a prior range blocks the target | 248 of 254 are blocked | – | – | No information (almost always true) |
| 1b equal highs/lows block the target | +0.154R vs +0.534R | +0.00 / +0.67 | – | No pass: only half 2, and XRP goes the other way |
| 2a OI rose > 1% in the 4 h before | **+0.633R (68%, n 38) vs +0.224R** | **+0.51 / +0.33** | **+0.042R (n 82) vs -0.217R; halves +0.26 / +0.26** | **Promising.** It fails the 25-trade minimum on the taken trades (17 and 21 per half) but **passes fully on the independent skipped-signal sample**. Mostly in longs; shorts point the same way, weaker |
| 2b with the price move and OI rose | +0.896R (78%, n 23) vs +0.225R | +0.60 / +0.75 | +0.203R (n 43) vs -0.214R; halves +0.46 / +0.38 | Same direction, too few trades (11–22 per half) |
| 3a, 3b OI flush in the last 2 h | 0 and 4 trades | – | 0 | Not testable: flushes this large are too rare |

**Other observations:**
- Losers that first reached +0.5R turned near a pool in only 8 of 44 cases.
- Stop-outs that were real sweeps (back 0.5R inside the stop within 30 minutes): 15 of 171 (9%). A stop buffer would rarely help.

**Conclusion:**
- Ideas 1 and 3 are dropped.
- Idea 2a, OI rising into the signal, is the one candidate. It is consistent in both halves and in two different samples.
- Before it becomes a size tier, check whether it overlaps with the Trendline tier.
- Then record it on every trade and use it for demo sizing, forward-checked like the Trendline tier.

## Overlap check and decision (2026-10-19)

Overlap with the Trendline tier, on the trades that have both histories:

| Group | Taken trades | Skipped signals |
|---|---|---|
| OI rising only | +0.584R (66% won, n 35) | +0.119R (n 77) |
| Trendline only | +0.565R (64% won, n 33) | -0.241R (n 109) |
| Both | n 3 | n 5 |
| Neither | +0.138R (48% won, n 145) | -0.225R (n 765) |

Only 3 of the 38 OI trades are Trendline trades too, so the OI flag finds different good trades.

**Implemented** (approved; the OI source is the Binance API):
- quality A = Trendline breakout OR open interest up more than 1% in 4 h (the `open_interest` table, synced every cycle)
- demo risk A 3%, B 2%
- every trade records `oi_change_4h` for the forward check
