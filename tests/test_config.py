import pytest
import yaml
from pydantic import ValidationError

from tradeagent.config import Settings, load_settings


def _raw(repo_root):
    return yaml.safe_load((repo_root / "config" / "settings.yaml").read_text(encoding="utf-8"))


def test_repo_settings_load(repo_root):
    s = load_settings(repo_root)
    assert list(s.exchange.symbols) == ["XRP", "LINK", "SOL"]
    assert s.venue == "binance-usdm" and s.market("XRP") == "XRP/USDT:USDT"
    assert s.market("XRP", "coinbase-us") == "XPP-20DEC30-CDE"
    assert s.exchange.symbols["XRP"].tradingview == "BINANCE:XRPUSDT.P"
    assert s.timeframes.trade == ["5m", "15m"]
    assert s.timeframes.overview == ["1h", "4h"]
    assert s.tradingview.signal_version == 1
    assert set(s.tradingview.layouts) == {"AGENT-XRP", "AGENT-LINK", "AGENT-SOL", "AGENT-HTF"}
    assert s.paper_account.risk_per_trade == 0.02


def test_relative_paths_start_at_project_root(repo_root):
    s = load_settings(repo_root)
    assert s.resolve("data/journal.db") == repo_root / "data" / "journal.db"


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("paper_account", "risk_per_trade", 0.5),  # more than 5% per trade
        ("paper_account", "max_positions_per_coin", 0),  # a limit must be at least 1 (or null for none)
        ("timeframes", "trade", ["7m"]),  # unknown timeframe
        ("costs", "taker_fe", 0.0005),  # typo in a key name
        ("tradingview", "min_bars", 100),  # too little history for the indicators
    ],
)
def test_invalid_values_are_rejected(repo_root, section, key, value):
    raw = _raw(repo_root)
    raw[section][key] = value
    with pytest.raises(ValidationError):
        Settings.model_validate(raw)


@pytest.mark.parametrize("layout", ["AGENT-HTF", "AGENT-SOL"])
def test_every_coin_and_the_htf_need_a_layout(repo_root, layout):
    raw = _raw(repo_root)
    del raw["tradingview"]["layouts"][layout]
    with pytest.raises(ValidationError):
        Settings.model_validate(raw)


def test_layout_helpers(repo_root):
    s = load_settings(repo_root)
    assert s.layout_for("XRP") == "K7xX5RYP"
    assert s.htf_layout == "9yUw9zox"
    assert s.all_timeframes == ["5m", "15m", "1h", "4h"]


def test_secrets_come_from_env_file_and_stay_hidden(tmp_path, repo_root, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.yaml").write_text(
        (repo_root / "config" / "settings.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / ".env").write_text("BINANCE_API_KEY=abc\nBINANCE_API_SECRET=xyz\n", encoding="utf-8")
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)

    s = load_settings(tmp_path)
    assert s.secrets.has_binance_keys
    assert s.secrets.binance_api_key.get_secret_value() == "abc"
    assert "abc" not in repr(s.secrets)


def test_environment_variable_wins_over_env_file(tmp_path, repo_root, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.yaml").write_text(
        (repo_root / "config" / "settings.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / ".env").write_text("BINANCE_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("BINANCE_API_KEY", "from-env")

    s = load_settings(tmp_path)
    assert s.secrets.binance_api_key.get_secret_value() == "from-env"


def test_per_coin_limit_cannot_exceed_the_total(repo_root):
    raw = _raw(repo_root)
    raw["paper_account"].update(max_positions=2, max_positions_per_coin=3)
    with pytest.raises(ValidationError):
        Settings.model_validate(raw)


def test_timezone_must_be_system_or_a_known_zone(repo_root):
    s = load_settings(repo_root)
    assert s.tradingview.timezone == "system"
    s.tradingview.model_validate({**s.tradingview.model_dump(), "timezone": "Asia/Karachi"})
    with pytest.raises(ValueError):
        s.tradingview.model_validate({**s.tradingview.model_dump(), "timezone": "Mars/Base"})
