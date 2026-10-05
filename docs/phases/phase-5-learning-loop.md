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

## As built (2026-10-04)

### How it works

1. **The rules a proposal may change.** `src/tradeagent/learning/space.py` lists the 26 allowed rules with their ranges and steps. The research pack shows them with their current values.
   - A proposal changes exactly one rule.
   - Costs, data, indicator settings, account limits and the judge's settings cannot be changed.
2. **Proposal.** `experiment propose <file>` reads JSON in the format of `research/proposal.schema.json`. That schema is generated from `space.py`, and a test keeps the two in sync.
   - The Experiment Manager checks the name, the hypothesis, the rule and its value.
   - It also refuses a change already tested against the same baseline, and a new proposal when 15 challengers are open.
3. **History screen** (`screen.py`). The baseline and all waiting proposals are replayed together on a copy of the journal (`data/replay/journal-screen.db`). This takes 2–4 minutes and runs at low priority.
   - A proposal passes if it beats the baseline over the whole history by the judge's rules.
   - It must also not be worse in either half. The halves hold equal numbers of baseline trades, because 5m snapshots start later than 15m ones.
   - It needs at least 15 trades in each half.
   - Failures become `rejected` and get a lesson.
4. **Forward test.** A passed proposal becomes a challenger in the shadow book from that moment.
   - The challengers of `config/setups.yaml` are tracked the same way (source `setups.yaml`). Their window starts at the demo's forward start, or when they first ran if that is later.
   - Every hour the agent compares each challenger with the baseline. Both must have `learning.min_trades` closed trades entered since the window start, on the demo's coins.
   - The challenger needs an expectancy at least `min_edge_r` higher, a profit factor not lower, and a max drawdown at most `max_drawdown_worse` worse.
5. **Re-confirmation.** A first win starts a new window, and the challenger must win again on `reconfirm_trades` fresh trades.
6. **Promotion.** With `learning.auto_promote`, the confirmed winner becomes the demo baseline. You can also promote by hand with the Promote button on the Learning page (or `experiment promote`).
   - A winner that has not won twice can still be promoted by hand. The dialog warns first, and the promotion is recorded as early.
   - The change is written into `config/setups.yaml` by `learning/setups_file.py`:
     - only the changed rule lines are edited, so comments stay
     - the challenger's line is removed
     - a version line is added to the header
     - a backup goes to `data/backups`

     If the file has an unusual layout and the result does not load back as intended, nothing is written.
   - A new `baseline_history` version is added (v3.2, ...).
   - The paper account follows the new baseline from the next cycle, and all other comparisons restart against it.
   - The go-live gate counts trades by their rules, not by the variant's name. The forward trades the winner made as a challenger therefore count for the new baseline, and the gate does not restart from zero.
   - Live trading still needs the user's approval.
7. **Lessons.** Every decision writes a lesson to the experiment and to `research/lessons.md`. `research/results.tsv` lists every experiment and is rebuilt with each pack.
8. **The agent** reloads the rules every cycle, so edits to `setups.yaml`, new experiments and promotions apply without a restart. Every hour it also:
   - judges the experiments
   - starts the history screen for waiting proposals in the background
   - writes the research pack once a day, after `research.daily_time_utc`
   - with `research.enabled`, starts `claude -p "/research"` with a fixed list of allowed tools (`learning/runner.py`). If the claude CLI is not installed, it logs a warning instead.

### Files and commands

| What | Where |
|---|---|
| Research instructions (human-edited) | `research/program.md` |
| `/research` command | `.claude/commands/research.md` |
| Proposal format | `research/proposal.schema.json` |
| Research pack | `research/packs/<day>.md` and `.json`, plus `latest.*` (not in git) |
| Lessons, results, run notes, proposals | `research/lessons.md`, `research/results.tsv`, `research/notes/`, `research/proposals/` |
| Judge settings | `learning` in `config/settings.yaml`, editable under Settings → Research |
| Dashboard | Learning page: experiments table with Promote and Stop buttons, timeline, latest research pack, lessons |

```powershell
.venv\Scripts\python -m tradeagent research-pack
.venv\Scripts\python -m tradeagent experiment list --all
.venv\Scripts\python -m tradeagent experiment propose research\proposals\2026-10-05.json
.venv\Scripts\python -m tradeagent experiment try filters.min_stop_pct 1.25   # replay only, not recorded
.venv\Scripts\python -m tradeagent experiment screen      # proposals waiting for their replay
.venv\Scripts\python -m tradeagent experiment evaluate    # judge now (the agent does it hourly)
.venv\Scripts\python -m tradeagent experiment stop 7 --reason "..."
.venv\Scripts\python -m tradeagent experiment lesson 7 "..."
.venv\Scripts\python -m tradeagent experiment promote 7 --yes   # writes setups.yaml; --early before it won twice
```

### First cycle (2026-10-04)

- **Five manual challengers retired** before the forward test, because they were worse than the baseline on the history: `min_stop_1pct`, `min_stop_2pct`, `confirm_0`, `stop_1h_swing` and `trigger_strong`.
  - Eight remain in the forward test, with `video_original` as the reference.
- **Five proposals from the first research run** were screened on the history and all rejected:
  - break-even at +1R
  - a 1.25R target
  - a 2R target
  - entries 04–20 UTC only
  - a 15-candle swing stop

  See `research/notes/2026-10-04.md`.
- **The stop floor failed** in an earlier test: −0.036R a trade over 954 trades. The option (`stop.min_pct`) stays available for other baselines.

### Not built yet

- **Strategy Tester flow** for indicator settings (build task 7). It needs Node.js for the TradingView MCP server and a Pine wrapper. Deferred; indicator-setting ideas go into the research notes.
- **The scheduled run needs the claude CLI on the PATH** of the computer that runs the agent, logged in with the Pro plan. Until then, run `/research` by hand in Claude Code.
