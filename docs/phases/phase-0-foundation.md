# Phase 0 — Foundation

**Goal:** Everything installed and connected so the build can start.
**Depends on:** nothing. **Estimated time:** 1–2 days.

> **Status: complete (2026-10-02).** `python -m tradeagent doctor` passes on the PC with 3 warnings (see Notes).
>
> **Current host: your Windows PC.** VPS-only steps (auto-logon, Binance-allowed location) apply later, when you move the setup to the VPS yourself.

## Your tasks

1. ✅ Buy TradingView Essential.
2. ✅ Install TradingView Desktop and log in (PC now; VPS later).
3. ✅ Create the 4 AGENT layouts and the "Scalp" / "Trend" indicator templates. Done and verified; see [TRADINGVIEW-SETUP.md](../TRADINGVIEW-SETUP.md).
4. Avoid casual changes to indicator settings on the AGENT charts. The agent will detect every change and start a new signal version, which resets comparisons.
5. ✅ Python 3.12+ (3.14.6) and Git are installed. Node.js is **optional** (see Notes).
6. ✅ Claude Code works through the VS Code extension with your Pro account.
7. Binance: an account with USDT-M futures enabled. API keys are not needed until [Phase 6](phase-6-live-trading.md).
8. **Open:** turn on Windows time sync. The PC clock is ~1.4 s behind Binance because the Windows Time service is stopped. Open Settings → Time & Language → Date & time → "Set time automatically" → "Sync now".

## Build tasks (done)

1. Repository skeleton: `src/tradeagent/`, `tests/`, `config/`, `scripts/`.
2. Configuration:
   - `config/settings.yaml`, validated by pydantic. Unknown keys and unsafe values are rejected.
   - Secrets come from `.env` or from environment variables; template in `.env.example`.
3. Logging: rotating file `data/logs/agent.log`, UTC timestamps.
4. SQLite journal `data/journal.db`:
   - WAL mode
   - versioned migrations; each runs in one transaction and rolls back fully on error
   - an `events` table
5. TradingView access: a minimal Python CDP client (`tradeagent/tv/cdp.py`) and `scripts/launch_tradingview_debug.ps1`, which starts the Microsoft Store build with the debug port.
6. `python -m tradeagent doctor` checks:
   - Python and packages
   - config and secrets
   - journal
   - Binance public API: 3 symbols, live prices, clock drift
   - TradingView: debug port and the 4 AGENT layouts
   - Claude Code CLI and Node.js (optional)
7. `.gitignore`, pinned `requirements.txt`, `pyproject.toml`, pytest with 18 tests. The network test runs with `-m network`.

## Deliverables

- Repository structure and config files
- `python -m tradeagent doctor` passing on the PC

## Exit criteria

- [x] TradingView Essential is active; the layouts and templates are saved
- [x] `doctor` passes (Binance OK, TradingView reachable, 4/4 AGENT layouts)
- [x] Claude Code works with your Pro login (VS Code extension)

## Notes

| Doctor warning | Meaning | Action |
|---|---|---|
| Binance clock drift ~1.4 s | The PC clock lags because the Windows Time service is stopped | Turn on time sync (task 8). Phase 1 schedules reads by Binance server time anyway. |
| Claude Code CLI not on PATH | Only the VS Code extension is installed | Needed only for scheduled research in Phase 5 |
| Node.js not installed | The agent talks to TradingView directly from Python over CDP | Needed only to run the TradingView MCP server inside Claude Code research sessions |

## Risks

| Risk | Mitigation |
|---|---|
| TradingView Desktop is restarted normally (no debug port) | Run `scripts/launch_tradingview_debug.ps1`; `doctor` points to it |
| TradingView Desktop does not start after a reboot (VPS later) | Windows auto-logon + a startup task running the launcher |
| 8 GB RAM is not enough (VPS later) | Measure in Phase 1; upgrade if usage stays above 80% |
