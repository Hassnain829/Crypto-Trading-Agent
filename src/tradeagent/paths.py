"""Locating the project root (the folder that holds config/settings.yaml)."""

from __future__ import annotations

import os
from pathlib import Path

CONFIG_RELATIVE = Path("config") / "settings.yaml"


def find_project_root(start: Path | None = None) -> Path:
    """Return the project root.

    Order: the TRADEAGENT_HOME environment variable, then the nearest parent of `start`
    (default: the current directory) that contains config/settings.yaml, then the source
    checkout this package was installed from.
    """
    env = os.environ.get("TRADEAGENT_HOME")
    if env:
        return Path(env).resolve()
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / CONFIG_RELATIVE).is_file():
            return candidate
    return Path(__file__).resolve().parents[2]
