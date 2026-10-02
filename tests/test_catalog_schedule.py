import pytest
from pydantic import ValidationError

from tradeagent.tv.catalog import Catalog, load_catalog
from tradeagent.tv.schedule import closing_at, last_closed_bar, next_boundary


def test_repo_catalog_loads_and_templates_split_indicators(repo_root):
    catalog = load_catalog(repo_root / "config" / "indicators.yaml")
    assert catalog.signal_version == 1
    assert set(catalog.js_spec("scalp")) == {"qtrend", "klinger", "vwap", "zerolag", "atp_macd"}
    assert set(catalog.js_spec("trend")) == {"qtrend", "zerolag"}
    buy = next(f for f in catalog.js_spec("trend")["qtrend"]["fields"] if f["name"] == "buy")
    assert buy == {"name": "buy", "plot": "plot_19", "title": "Q-Trend BUY", "kind": "flag"}


def test_catalog_rejects_unknown_template_indicator():
    with pytest.raises(ValidationError):
        Catalog.model_validate(
            {
                "signal_version": 1,
                "indicators": {"a": {"study": "A", "fields": {"x": {"plot": "plot_0", "title": "X", "kind": "value"}}}},
                "templates": {"scalp": ["a", "missing"]},
            }
        )


def test_catalog_rejects_bad_plot_id():
    with pytest.raises(ValidationError):
        Catalog.model_validate(
            {
                "signal_version": 1,
                "indicators": {"a": {"study": "A", "fields": {"x": {"plot": "zero", "title": "X", "kind": "value"}}}},
                "templates": {"scalp": ["a"]},
            }
        )


def test_last_closed_bar():
    # 10:07:30 UTC on 2026-10-02 -> last closed 5m candle opened at 10:00, 1h candle at 09:00
    now = 1790935650
    assert last_closed_bar(now, "5m") == 1790935200
    assert last_closed_bar(now, "1h") == 1790931600
    # exactly on a boundary the candle that just closed is the previous one
    assert last_closed_bar(1790935500, "5m") == 1790935200


def test_next_boundary_and_closing_timeframes():
    assert next_boundary(1790935650, 300) == 1790935800
    assert next_boundary(1790935800, 300) == 1790936100  # strictly after
    tfs = ["5m", "15m", "1h", "4h"]
    assert closing_at(1790935800, tfs) == ["5m"]  # 10:10
    assert closing_at(1790936100, tfs) == ["5m", "15m"]  # 10:15
    assert closing_at(1790942400, tfs) == ["5m", "15m", "1h", "4h"]  # 12:00
