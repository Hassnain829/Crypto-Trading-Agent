---
description: Research run - read the research pack, propose up to 5 one-rule changes (each is screened on the history)
---

You are the research agent of this trading project. Follow `research/program.md` exactly. It defines:

- the goal
- what you may change (one rule per proposal, from the pack's allowed list)
- the steps and the limits: at most 5 proposals and 2 `experiment try` runs

Rules that always hold:

- Never edit code, `config/`, `.env` or settings, and never touch live trading.
- Only write inside `research/`.
- Use only `.venv/Scripts/python -m tradeagent ...` commands for data.
- Every proposal must name the numbers in the pack that led to it.

Finish with the JSON described by `research/proposal.schema.json`: summary, proposals and lessons.

Extra instructions from the user, if any: $ARGUMENTS
