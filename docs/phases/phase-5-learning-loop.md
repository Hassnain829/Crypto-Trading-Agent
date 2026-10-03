# Phase 5 — Learning Loop

**Goal:** The agent improves itself. Claude studies the results and proposes one change at a time, and only changes that hold up become the new baseline.
**Depends on:** Phases [2](phase-2-shadow-engine.md), [3](phase-3-paper-account-and-risk.md) and [4](phase-4-dashboard.md). **Estimated time:** 2–3 weeks, mostly data collection.

## The loop

1. **Research pack** (daily, automatic). A markdown + JSON report from the journal containing:
   - metrics per variant with sample sizes
   - breakdowns by coin, timeframe, hour, HTF alignment and indicator states
   - the value of each filter (counterfactual vs taken trades)
   - losing streaks and the worst trades with their snapshots
   - data-quality notes
2. **Claude research** (Pro plan):
   - **Interactive:** run `/research` in Claude Code. Claude reads the pack, may look at charts on a dedicated research tab through the MCP, and writes proposals and lessons.
   - **Scheduled (optional):** Task Scheduler runs `claude -p "/research" --output-format json --json-schema ...` once a day on the VPS.
3. **Proposal format** (validated JSON): variable, new value, hypothesis, expected effect, confidence.
4. **Validation** by the Experiment Manager:
   - the variable and value are in the allowed list and range
   - exactly one change from the baseline
   - not already tested against this baseline
5. **Challenger.** A valid proposal becomes a challenger and runs in shadow beside the baseline.
6. **Evaluation** (defaults, editable). The challenger wins only if all of these hold:
   - both have ≥ 100 closed trades in the same period
   - challenger expectancy ≥ baseline + 0.05R
   - profit factor not lower than the baseline's
   - max drawdown not more than 25% worse
7. **Re-confirmation.** The winner must stay ahead on the next ≥ 50 fresh trades.
8. **Promotion.** The winner becomes the new baseline for the paper account automatically. Live trading needs your approval.
9. **Lesson.** Every experiment, won or lost, ends with a lesson in `research/lessons.md` and the journal.

## Design reference: karpathy/autoresearch

[autoresearch](https://github.com/karpathy/autoresearch) lets an LLM agent improve a model overnight. The agent:
1. edits one file (`train.py`) and commits the change
2. runs a fixed 5-minute experiment
3. reads a ground-truth metric from code it may not change (`prepare.py`)
4. keeps the commit if the metric improved, otherwise resets it
5. logs every run in `results.tsv`

Its code (GPT training on a GPU) is not useful here, but the loop maps directly:

| autoresearch | Here |
|---|---|
| `program.md` (the human writes the agent's instructions) | `research/program.md`: what Claude may change (only `config/setups.yaml` variants, one change each), the metric, the rules |
| `train.py` (the only file the agent edits) | `config/setups.yaml` |
| `prepare.py` with the read-only metric | The replay, `verify-trades` and the report. Costs, data and the evaluation are off limits to Claude. |
| 5-minute experiment | A replay of the history (~5 minutes) |
| Keep or reset by git | Promote only if the variant wins in both halves of the history **and** on fresh forward trades |
| `results.tsv` | `research/results.tsv` plus the `experiments` table and `research/lessons.md` |

The main difference: a trading history is small and repeated tests overfit it fast. In the 2026-10-03 review, a combination that looked like +0.58R on two weeks was flat on older data. So forward confirmation stays mandatory, and the number of experiments is capped.

## Limits that stop the agent from fooling itself

- Max 15 challengers at the same time.
- Every challenger differs from the baseline in one variable only.
- All experiments are counted and shown. Many tests make lucky winners more likely, so re-confirmation is mandatory.
- Claude never edits code, live settings or indicator settings directly.

## Indicator-setting research (for example Q-Trend ATR 32 → 28)

Changing an indicator setting changes the signals for every variant, so it is handled separately:

1. Test it on a separate research tab in the TradingView Strategy Tester (~35 days of 5m data with Essential), driven through the MCP.
   - This needs a small Pine strategy wrapper that reads the indicator outputs.
   - The approach is confirmed in this phase.
2. If the new setting is clearly better, you approve a new signal version. Comparisons then restart within the new version.

## Build tasks

1. Research pack generator
2. `/research` Claude Code command (a project file) plus the JSON schema for proposals
3. Optional scheduled run (Task Scheduler)
4. Experiment Manager: validation, challenger lifecycle, evaluation, re-confirmation, promotion
5. Lessons store (journal + `research/lessons.md`)
6. Learning page in the dashboard
7. Strategy Tester research flow on the research tab

## Deliverables

- Daily research pack
- `/research` command and the optional schedule
- Experiment Manager running challengers automatically
- Lessons memory visible in the dashboard

## Exit criteria

- [ ] At least 3 complete experiment cycles (proposal → test → decision → lesson)
- [ ] The Learning page shows the full timeline
- [ ] If enabled, scheduled research runs for 7 days without manual help

## Risks

| Risk | Mitigation |
|---|---|
| Pro usage limits are reached | Research waits; trading and shadow are not affected |
| `claude -p` later requires an API key (Claude Code plans to make `--bare` the default, and it ignores subscription logins) | Switch the research runner to the Claude API with a config change |
| Overfitting | One variable at a time, re-confirmation, experiment count shown |
