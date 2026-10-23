"""Background jobs of the learning loop, started by the agent: the history screen and the daily Claude research."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tradeagent.config import Settings

# What the scheduled research may do without asking: read, write research notes, and run the agent's own
# research commands (which validate every proposal). No other commands, no code or config edits.
# Experiment commands are listed one by one (research/program.md uses exactly these): `experiment promote`
# (which writes config/setups.yaml, even early) and `experiment evaluate` (which can auto-promote) stay with
# the agent's hourly judge and the user.
RESEARCH_EXPERIMENT_COMMANDS = ("list", "propose", "try", "stop", "lesson")
RESEARCH_TOOLS = [
    "Read", "Glob", "Grep",
    "Write(research/**)", "Edit(research/**)",
    "Bash(.venv/Scripts/python -m tradeagent research-pack*)",
    *(f"Bash(.venv/Scripts/python -m tradeagent experiment {name}*)" for name in RESEARCH_EXPERIMENT_COMMANDS),
    "Bash(.venv/Scripts/python -m tradeagent shadow-report*)",
    "Bash(.venv/Scripts/python -m tradeagent trades*)",
]


def _log(settings: Settings, name: str) -> Path:
    path = settings.resolve(settings.logging.file).with_name(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def spawn(settings: Settings, cmd: list[str], log_name: str) -> subprocess.Popen:
    """Run a command in the background at low priority, without a window, appending its output to a log."""
    out = open(_log(settings, log_name), "ab")
    out.write(f"\n--- {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {' '.join(cmd[:4])} ---\n".encode())
    out.flush()
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
    try:
        return subprocess.Popen(cmd, cwd=settings.root, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                creationflags=flags, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    finally:
        out.close()


def spawn_screen(settings: Settings) -> subprocess.Popen:
    return spawn(settings, [sys.executable, "-m", "tradeagent", "experiment", "screen"], "learning.log")


def spawn_long_backtest(settings: Settings) -> subprocess.Popen:
    return spawn(settings, [sys.executable, "-m", "tradeagent", "experiment", "long-backtest"], "learning.log")


def claude_command() -> str | None:
    """The claude CLI: on the PATH, or where the native installer puts it (a long-running agent may have been
    started before the installer added that folder to the PATH)."""
    found = shutil.which("claude")
    if found:
        return found
    native = Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")
    return str(native) if native.exists() else None


def spawn_research(settings: Settings) -> subprocess.Popen | None:
    """The daily research run: Claude Code (Pro login) runs the /research command once. None if not installed.
    research/program.md limits the work (at most 5 proposals and 2 tries per run)."""
    claude = claude_command()
    if claude is None:
        return None
    cmd = [claude, "-p", "/research", "--output-format", "json", "--allowedTools", *RESEARCH_TOOLS]
    return spawn(settings, cmd, "research.log")
