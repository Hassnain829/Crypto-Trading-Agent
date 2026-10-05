# Research program

Instructions for Claude when it runs `/research`, by hand or on the daily schedule. The human edits this file; Claude follows it and does not change it.

## Goal

Raise the net R per trade of the demo account's **baseline** on the coins the demo trades (now XRP, SOL and ETH), without making it fragile.

- The metric is computed by code you do not change: shadow trades simulated from TradingView signals and Binance candles, after fees, slippage and funding.
- A change is only worth something if it also holds on **future** trades. The history (about 100 days of 15m signals and 35 days of 5m signals) is small, and every test against it makes a lucky winner more likely.

## What you may change

- **One rule per proposal**, chosen from `allowed_changes` in the research pack. The list and the ranges come from `src/tradeagent/learning/space.py`.
- Every proposal is a challenger: it runs in the shadow book beside the baseline, on the same signals.

You may **not** change any of these:

- code, `config/settings.yaml` or `config/setups.yaml`
- costs, the evaluation rules (settings `learning`) or account limits
- indicator settings or TradingView layouts
- anything to do with live trading

Indicator settings (for example the Q-Trend ATR) need a new signal version and the user's approval. Write such ideas in your notes instead.

## How a proposal is judged (automatic)

1. **History screen.** The history is replayed with the baseline and the challenger.
   - The challenger must beat the baseline overall: expectancy at least `min_edge_r` higher, profit factor not lower, and max drawdown at most 25% worse.
   - It must also not be worse in either half of the history.
   - It needs at least 15 trades in each half.
2. **Forward test.** Both must reach `min_trades` closed trades in the same period, and the challenger must win by the same rules.
3. **Re-confirmation.** The winner must stay ahead on `reconfirm_trades` fresh trades.
4. **Promotion.** The winner becomes the demo baseline. Live trading always needs the user's approval.
5. Every decision writes a lesson to `research/lessons.md` and the journal.

## Steps of a research run

1. Run `.venv/Scripts/python -m tradeagent research-pack`, then read `research/packs/latest.md`. `latest.json` has the same data in full.
2. Read `research/lessons.md`, and `research/results.tsv` for every experiment so far. Do not propose a change that was already tested against the same baseline; the manager refuses it anyway.
3. Look at the running experiments. Do not stop one early because of a few bad trades: stop only one that is broken, for example one that takes no trades at all for a week (`experiment stop ID --reason "..."`).
4. Form at most **5 hypotheses**, each grounded in numbers from the pack: a breakdown, a filter's value, the worst trades or a streak. Say which number led to it.
5. Write them to `research/proposals/<YYYY-MM-DD>.json` in the format of `research/proposal.schema.json`.
   - Add a lesson for every experiment decided since the last run, explaining why it won or lost (the manager already wrote the numbers).
   - Then run `.venv/Scripts/python -m tradeagent experiment propose research/proposals/<YYYY-MM-DD>.json`.
   - Each proposal is replayed on the history (all of them in one replay, a few minutes) and recorded, pass or fail. A failed idea is then never repeated, and every test is counted.
6. For every rejected proposal, add a lesson that explains the result, not just the numbers:
   `.venv/Scripts/python -m tradeagent experiment lesson ID "..."`.
   - `experiment try <path> <json value>` replays one change without recording it. Use it only to check a value before proposing, at most twice per run: unrecorded tests are still tests.
7. Write a short note to `research/notes/<YYYY-MM-DD>.md`:
   - what you looked at and what you found
   - the proposals and their screen results, including those that failed
   - ideas for later that are outside the allowed list
8. End with the JSON output (same schema). Keep it to these files and commands.

## Good habits

- Prefer simple, explainable rules: a session filter backed by the hourly breakdown beats a value tuned to two decimals.
- A filter that removes most trades can look great on few trades. Check the trade count, and keep at least about 2 trades a day across the coins.
- When the forward and history numbers disagree, trust the forward numbers more, but wait for enough trades.
- Losing ideas are results too. Record them so that nobody tries them again.
