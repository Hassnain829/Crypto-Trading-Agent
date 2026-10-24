# 2026-10-23: BTC leads the alts; the 4h chart breakout as tier A; the second engine

Tools: research/tools/engine2_check.py, btc_realtime.py, btc_tier.py. Output: data/research/engine2.txt,
btc_realtime.txt, btc_tier.txt.

## BTC and XRP/SOL/ETH (the user's point: BTC is the father figure)

- **Correlation of 1h returns with BTC over 4 years:** XRP 0.62, SOL 0.70, ETH 0.83.
- **On the 111 days BTC fell 3%+, the coins fell too:** XRP on 93% of them (average -5.1%), SOL 96% (-6.6%), ETH 99%
  (-5.4%). BTC averaged -4.6%.
- **The design's trades on those days:** shorts +0.859R (203), longs -0.434R (95). On BTC +3% days: longs +0.557R,
  shorts -0.621R. These whole-day numbers are hindsight.
- **Known at the decision** (BTC moved 2%+ in the trade's direction or against it):

| BTC's move before the decision | design: with | against | flat | v0, not seen: with | against |
|---|---|---|---|---|---|
| since the UTC day's open | +0.196R (378) | -0.009R (183) | +0.019R | +0.133R (667) | -0.059R (582), both halves negative |
| last 4 h | +0.126R (379) | 9 trades | +0.025R | +0.041R | -0.122R (161), both halves negative |
| **last 12 h** | **+0.158R (324; +0.161 / +0.154)** | +0.005R (209) | +0.026R | +0.051R (both halves) | -0.016R |

- **Correction to the earlier wording:** BTC's slow trend (daily/4h EMA) does not help, but BTC's recent move does.

## The full tier-A package in the account (simple account at the user's rules)

The simple account was checked against the real replay: S0 gave +807% / DD 62.7% here vs +773% / 62.7% in the real one.

| Scheme | 4 years | 2022-24 | 2024-26 | TradingView since 06-25 |
|---|---|---|---|---|
| S1: A or 1h/1d pattern | +1,136%, DD 67.6% | +299% (67.6%) | +210% (66.1%) | +280% (17.8%) |
| + 4h chart breakout | +1,180%, DD 66.6% | +307% (66.6%) | +214% (65.9%) | +288% (17.8%) |
| + BTC 12h move with the trade | +1,421%, DD 68.2% | +369% (65.8%) | +224% (68.3%) | +282% (17.8%) |
| **and skip trades against a 2%+ BTC 12h move** | **+1,430%, DD 59.3%** | **+310% (59.3%)** | **+274% (57.8%)** | +266% (14.3%) |
| everyone 2% | +728%, DD 62.7% | +185% | +190% | +183% (15.7%) |

- Skipping trades against BTC removes about 4% of the trades.
- Tier A then covers about 57% of the trades.
- On the TradingView window only 17 trades had a 2%+ BTC 12h move, so that check is thin.

## The 4h chart breakout as a tier-A reason: replicated

| Sample | with a breakout in the trade's direction | without |
|---|---|---|
| design, 4 years (found) | +0.199R (146; +0.144 / +0.267) | +0.030R |
| dip15 on BTC (not seen) | +0.452R (21) | -0.023R |
| v0, 4 coins (not seen) | +0.067R (395; +0.084 / +0.044) | -0.006R |
| trend15, 4 coins (not seen) | +0.147R (257; +0.142 / +0.156) | +0.025R |

## The second engine (4h chart breakout -> first 15m pullback, agent stop, 1.5R)

- **9 coins the agent does not trade (2025-04 to 2026-10):** +0.017R on 2,046 trades. ZEC +0.131R, NEAR +0.074R and ADA
  +0.017R are positive; BNB -0.129R and the rest about -0.02R. It does not clearly replicate.
- **Overlap:** 20% of its XRP/SOL/ETH trades are within 4 h of a design trade on the same coin and side, so 80% are new.
- **One account with the design:**

| | 4 years | 2022-24 | 2024-26 | trades a day |
|---|---|---|---|---|
| design alone | +1,136%, DD 67.6% | +299% | +210% | 1.66 |
| design + engine 2 | +2,714%, DD 71.1% | +335% (DD 50.0%) | +563% (71.1%) | 2.38 |
| engine 2 alone | +277%, DD 56.0% | +32% | +185% | 1.02 |

- **Verdict:** more trades and more money in the account, but the other coins do not confirm it. Forward-test it in the
  shadow book before the demo. It needs a new candle-based engine.

## The user's charts (another TradingView account, 2026-10-24 02:16 PKT)

- The daily shows the big red 10-22 candle.
- Their 4h and 15m charts show "Bull Div" labels and green ATP MACD dots at the latest lows. The timeframes disagree, so
  it is not a clean confluence.
- In Binance's UTC data, 10-19 closed slightly red (82,078 -> 81,903). So two green candles came before the red one, not
  three.
