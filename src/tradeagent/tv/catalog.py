"""Indicator output catalog (config/indicators.yaml): which TradingView plots the agent reads."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldSpec(_Strict):
    plot: str = Field(pattern=r"^plot_\d+$")
    title: str
    kind: Literal["value", "flag"]


class IndicatorSpec(_Strict):
    study: str
    fields: dict[str, FieldSpec] = Field(min_length=1)


class Catalog(_Strict):
    signal_version: int = Field(ge=1)
    indicators: dict[str, IndicatorSpec] = Field(min_length=1)
    templates: dict[str, list[str]] = Field(min_length=1)

    @model_validator(mode="after")
    def _templates_use_known_indicators(self) -> Catalog:
        for name, keys in self.templates.items():
            unknown = [k for k in keys if k not in self.indicators]
            if unknown:
                raise ValueError(f"template {name!r} uses unknown indicators {unknown}")
        return self

    def js_spec(self, template: str) -> dict[str, Any]:
        """The part of the catalog the in-page reader needs for one chart template."""
        return {
            key: {
                "study": self.indicators[key].study,
                "fields": [
                    {"name": name, "plot": f.plot, "title": f.title, "kind": f.kind}
                    for name, f in self.indicators[key].fields.items()
                ],
            }
            for key in self.templates[template]
        }

    def study_names(self) -> list[str]:
        return [ind.study for ind in self.indicators.values()]


def load_catalog(path: Path) -> Catalog:
    with path.open(encoding="utf-8") as fh:
        return Catalog.model_validate(yaml.safe_load(fh))
