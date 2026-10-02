# Roadmap

## Phase overview

| Phase | Name | Goal | Depends on | Estimated calendar time |
|---|---|---|---|---|
| 0 | [Foundation](phases/phase-0-foundation.md) | VPS, TradingView, repo and config ready | — | 1–2 days |
| 1 | [TradingView signal reader](phases/phase-1-tradingview-reader.md) | Read every closed candle of all 5 indicators reliably | 0 | 3–5 days (incl. 48h test) |
| 2 | [Market data + shadow engine](phases/phase-2-shadow-engine.md) | Unlimited shadow trades with real prices and fees | 1 | ~1 week (incl. 7-day run) |
| 3 | [Paper account + risk engine](phases/phase-3-paper-account-and-risk.md) | Live-like account with every live rule | 2 | 3–5 days |
| 4 | [Dashboard v1](phases/phase-4-dashboard.md) | See and control everything from a browser | 2 (can run beside 3) | ~1 week |
| 5 | [Learning loop](phases/phase-5-learning-loop.md) | Claude research, experiments, lessons | 2, 3, 4 | 2–3 weeks incl. data collection |
| 6 | [Live trading](phases/phase-6-live-trading.md) | Small live account on Binance | Go-live gate + your approval | 2–4 weeks of monitored trading |
| 7 | [Scale and improve](phases/phase-7-scale-and-improve.md) | More coins, setups and features | 6 | Ongoing |

**Status (2026-10-02):** Phase 0 complete. Phases 1, 2 and 3 built. One `agent` run covers their remaining runtime tests: 48 hours (Phase 1) and 7 days (Phases 2 and 3).

Times are estimates. Building is fast; collecting enough shadow trades is the real clock. The earliest realistic live start is about 6–8 weeks after Phase 0, and only if the go-live gate is met.

## Week-by-week view (estimate)

| Week | Work | Data collected |
|---|---|---|
| 1 | Phase 0 + Phase 1 | Indicator snapshots start |
| 2 | Phase 2 | Shadow trades start (exploration book) |
| 3 | Phase 3 + Phase 4 | Paper account starts |
| 4–6 | Phase 5 | Experiments run; paper account builds its sample |
| 6–8+ | Go-live gate check → Phase 6 | Live trading (only if the gate is met) |

## Critical path

Buy TradingView Essential → Phase 0 → **Phase 1 (riskiest: reading closed candles from TradingView)** → Phase 2 (data collection starts) → Phases 3 + 4 → Phase 5 → go-live gate → Phase 6

## Why this order

- **Phase 1 comes first** because everything depends on reading TradingView reliably. If it fails, we change the plan before building anything else.
- **Shadow data collection starts early (Phase 2)** because learning needs hundreds of trades.
- **The dashboard comes once there is data to show.**
- **Live trading is last and gated.**

## Decision points

| When | Question | Options |
|---|---|---|
| End of Phase 1 | Is CDP reading reliable enough? | Continue / Pine "combiner" table / backup alerts |
| End of Phase 2 | Does the baseline produce enough trades? | Adjust triggers / add timeframes |
| During Phase 5 | Is the paper account moving toward the gate? | Keep researching / change setups |
| Gate met | Start live trading? | Your approval in the dashboard |

## Related documents

- [REQUIREMENTS.md](REQUIREMENTS.md): what we agreed
- [ARCHITECTURE.md](ARCHITECTURE.md): how the parts fit together
- [GOALS-AND-METRICS.md](GOALS-AND-METRICS.md): how success is measured
