"""Builds one of the dashboard's slow reports in its own process and prints it as JSON.

The gate's account replay and the variant report take seconds on a large journal. Built in a thread of the dashboard
they held Python's lock for those seconds, so every click in the browser waited (2026-10-29). The dashboard
(data.Store._build_in_worker) starts this at below-normal priority and only waits for the pipe:

    python -m tradeagent.dashboard.slow_reports gate|variants|preview   < {"journal": ..., "root": ..., "settings": {...}}

(preview also takes "rules" and "since").

It opens the journal read-only and writes nothing.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


def build(report: str, job: dict) -> object:
    path = Path(job["journal"])
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        if report == "gate":
            from tradeagent.account.report import account_report
            from tradeagent.config import Settings

            settings = Settings.model_validate(job["settings"])
            settings._root = Path(job["root"])
            return account_report(conn, settings)
        if report == "variants":
            from tradeagent.dashboard.data import Store

            return Store._variants(conn)
        if report == "preview":  # the Settings page's live preview of limits that may not be saved yet
            from tradeagent.account.preview import live_preview
            from tradeagent.config import PaperAccountConfig, Settings

            settings = Settings.model_validate(job["settings"])
            settings._root = Path(job["root"])
            return live_preview(conn, settings, PaperAccountConfig.model_validate(job["rules"]), since=job["since"])
        raise ValueError(f"unknown report {report!r}")
    finally:
        conn.close()


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m tradeagent.dashboard.slow_reports gate|variants|preview < job.json", file=sys.stderr)
        return 2
    report = build(argv[0], json.loads(sys.stdin.read()))
    sys.stdout.write(json.dumps(report))  # ASCII only, whatever the console's code page
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
