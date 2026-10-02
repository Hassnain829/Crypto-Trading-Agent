from pathlib import Path

import pytest

from tradeagent.config import Settings, load_settings

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """The real settings, with the journal and logs redirected to a temp folder."""
    loaded = load_settings(REPO_ROOT)
    loaded.journal.path = str(tmp_path / "journal.db")
    loaded.logging.file = str(tmp_path / "logs" / "agent.log")
    return loaded
