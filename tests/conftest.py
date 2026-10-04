from pathlib import Path

import pytest

from tradeagent.config import Settings, SymbolConfig, load_settings

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
    # Tests use a fixed coin universe (XRP, LINK, SOL), independent of the coins traded live.
    sym = loaded.exchange.symbols
    sym.clear()
    sym.update({
        "XRP": SymbolConfig(tradingview="BINANCE:XRPUSDT.P", markets={"binance-usdm": "XRP/USDT:USDT", "coinbase-us": "XPP-20DEC30-CDE"}),
        "LINK": SymbolConfig(tradingview="BINANCE:LINKUSDT.P", markets={"binance-usdm": "LINK/USDT:USDT", "coinbase-us": "LNP-20DEC30-CDE"}),
        "SOL": SymbolConfig(tradingview="BINANCE:SOLUSDT.P", markets={"binance-usdm": "SOL/USDT:USDT", "coinbase-us": "SLP-20DEC30-CDE"}),
    })
    loaded.tradingview.layouts = {"AGENT-XRP": "K7xX5RYP", "AGENT-LINK": "CztsiO1R", "AGENT-SOL": "NZPfFmj0",
                                  "AGENT-HTF": "9yUw9zox"}
    loaded.paper_account.symbols = None
    loaded.live_account.symbols = None
    return loaded
