# Phase 4.5 — Exchange Adapter (trading venues)

**Goal:** The agent can simulate and, from Phase 6, trade on the exchange the user will really use, while the signals keep coming from the TradingView charts.
**Why before Phase 5:**
- The VPS is in the USA, where Binance's API is blocked.
- The user will trade with US KYC on Coinbase or Kraken.
- The go-live gate and the learning loop must judge the strategy on the fills, fees and contract sizes of that exchange.

**Depends on:** Phases 2–4. **Status (2026-10-04):** built; the venue decision is pending (see "Decision").

## Venues checked (2026-10-04)

| Venue | Who | XRP / SOL / LINK | Contract | Fees | API for a bot |
|---|---|---|---|---|---|
| `coinbase-us` Coinbase US perpetual-style futures | US residents | XPP / SLP / LNP (2030 contracts, perpetual-style) | 500 XRP ≈ $740, 5 SOL ≈ $595, 50 LINK ≈ $700 | from 0.02%, min $0.15 per contract, all fees included | Yes (Coinbase Advanced API, in ccxt) |
| Kraken US perpetuals (Bitnomial) | US residents | PXRPUH / PSOLUS / PLNKUD | 100 XRP ≈ $148, 1 SOL ≈ $119, 10 LINK ≈ $140 | exchange + NFA + clearing + commission (not published) | **None found.** Kraken's public futures API is the international one |
| `kraken-futures` | non-US | PF_XRPUSD / PF_SOLUSD / PF_LINKUSD | 1 coin | 0.02% / 0.05% | Yes |
| `coinbase-intl` | eligible non-US | XRP / SOL / LINK-PERP | 1 coin | 0% / 0.03% | Yes |
| `bitget`, `mexc` | non-US | USDT perps | 1 coin (MEXC SOL/LINK 0.1) | see `venues` | Yes |
| `binance-usdm` (current) | non-US; US IPs blocked | USDT perps | 1 coin | 0.02% / 0.05% | Yes |

Coinbase US data quality (one day, 2026-10-02): XRP has 1364 of 1440 one-minute candles with ~$67M a day; SOL 1249 and ~$41M; LINK only 979 and ~$9M. The median price difference to Binance is 0–7 bps. Prices follow Binance closely, so the signals can stay on the Binance charts.

## As built

| Part | Implementation |
|---|---|
| Venue registry | `venues.py`: one entry per venue (ccxt class, settlement currency, who may use it, candles per request, quiet minutes, funding and server time available, default fees). `MarketData` gives public market data for any venue; markets may be written as ccxt symbols or as the exchange's own id. `python -m tradeagent venues` lists them. |
| Settings | `exchange.venue` chooses the venue. Each coin has its TradingView signal chart and a market per venue (`exchange.symbols.<coin>.markets`). The old `ccxt:` key still works as the Binance market. The dashboard field "Trading exchange" (Settings > Exchanges) applies when the agent restarts. The live orders of Phase 6 go to the same venue; the old `live_account.exchange` setting is gone. |
| Market data | The journal holds one venue's candles, funding and market info at a time. When the venue changes they are cleared and downloaded again (`ensure_venue`), the newest candles first and older history over the next cycles, so the agent keeps reading. Minutes without trades (Coinbase) get a flat candle at the previous close. Funding is simulated only where its history is available (not on `coinbase-us`). |
| Sizing | Orders are whole contracts. If one contract would risk more than the risk per trade, the demo trade is skipped with the reason, e.g. "one contract (500 coins) would risk 17.50 (11.7% of the balance)". |
| Clock | The venue's server time, or the computer's clock where the venue has no time endpoint (Windows time sync must be on). |
| Trades | Every shadow and demo trade records the venue whose prices filled it (migration 9). |
| Keys | Coinbase API key name and EC private key can be pasted in the dashboard; the private key is kept on one line in `.env`. Kraken US keys will follow if Kraken offers API access. |
| Replay | `python -m tradeagent venue-replay <venue> --balance 150 --balance 1000` copies the journal to `data/replay/`, downloads that venue's history, simulates every stored signal again and compares it with Binance over the same period: R per variant, and the money with the venue's contract sizes. The real journal is only read. |
| Robustness | A network error is logged as one line instead of a traceback. A candle close noticed more than 10 minutes late (the computer slept) is skipped with a message that says how long the agent was paused. |

## Decision

### Coinbase US replay (2026-10-04)

`venue-replay coinbase-us` used the same TradingView signals with Coinbase US prices, entries from 2026-06-06. Download took 33 minutes; the replay 7 minutes.

Over 120 days, 41% of XRP minutes, 73% of LINK minutes (and 40% of LINK 5m candles) had no trades on Coinbase US.

| Variant | Binance: trades, R/trade, total | Coinbase US: trades, R/trade, total (missed limit entries) |
|---|---|---|
| v2 baseline | 261, +0.116R, +30.2R | 139, **+0.029R**, +4.0R (133 missed vs 32) |
| session_07_21 | 181, +0.159R, +28.8R | 97, **+0.195R**, +18.9R |
| session_13_21 | 132, +0.240R, +31.6R | 75, **+0.217R**, +16.2R |
| tf_15m | 181, +0.159R, +28.8R | 83, +0.066R, +5.5R |
| market_entry | 293, +0.072R, +21.1R | 272, +0.063R, +17.0R (no misses) |
| video_original | 1112, −0.157R | 1107, −0.171R |

Baseline by coin:

| Coin | Binance | Coinbase US |
|---|---|---|
| XRP | +0.291R | +0.110R |
| SOL | +0.198R | +0.128R |
| LINK | −0.090R | −0.216R |

Demo account, every baseline signal, 2% risk, Coinbase contract sizes:
- $150: **no trades**, because one contract risks about 9% of the balance.
- $1,000: +7.4%, 115 trades, max drawdown 17.8%.
- $2,500: +5.8%.

On Binance the same signals made about +60%.

**Reading:**
- v2's edge rests on maker limit entries. On a thin venue many of them do not fill, mostly the ones where the price moves away at once.
- LINK is weak on both venues and very thin on Coinbase.
- The US-session filters keep their edge on Coinbase because liquidity is higher then.
- These variants were chosen after looking at the same history, so they need forward confirmation before they become the baseline (Phase 5).

**Open decision (the user's):**
1. Live venue: Coinbase US now (API ready, needs about $1,000+ for 2% risk with these contracts), or Kraken US once Kraken confirms API access (contracts 5–50 times smaller).
2. Demo balance: the planned live balance, because $150 cannot hold one Coinbase contract.
3. Strategy on the US venue: forward-test the session filters and XRP + SOL only as challengers.

## Switching the venue

1. Run `venue-replay <venue>` and compare the edge.
2. Set Settings > Exchanges > Trading exchange, then press Restart on the Overview.
3. The agent downloads the venue's market data. The newest candles arrive within a cycle and the full history over the following hour.
4. Start a new forward test on the venue: `python -m tradeagent paper-reset --yes --from-now`.

## Exit criteria

- [x] Any listed venue can be chosen in settings or the dashboard; signals stay on TradingView.
- [x] Demo fills, contract sizes and the clock come from the chosen venue.
- [x] A replay compares the strategy on another venue without touching the journal.
- [x] Tests: venue settings, quiet-minute filling, history in steps, contract sizing, PEM keys, sleep and network messages.
- [ ] The user chooses the live venue, and the forward test restarts on it.
