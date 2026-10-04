"""Small building blocks shared by the dashboard pages: formatting, cards, tiles, charts and tables."""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from nicegui import app, ui

from tradeagent.dashboard.theme import PALETTES, STATUS, STATUS_ICON, chart_base


def mode() -> str:
    return app.storage.general.get("theme", "dark")


def palette() -> dict[str, Any]:
    return PALETTES[mode()]


# ---- formatting ------------------------------------------------------------------------------
def money(v: float | None, sign: bool = False) -> str:
    if v is None:
        return "–"
    return f"{v:+,.2f} $" if sign else f"{v:,.2f} $"


def pct(v: float | None, digits: int = 1, sign: bool = False) -> str:
    if v is None:
        return "–"
    return f"{v * 100:+.{digits}f}%" if sign else f"{v * 100:.{digits}f}%"


def rr(v: float | None) -> str:
    return "–" if v is None else f"{v:+.3f}R"


def num(v: float | None, digits: int = 2) -> str:
    return "–" if v is None else f"{v:,.{digits}f}"


_timezone_setting: Callable[[], str] = lambda: "Etc/UTC"


def use_timezone(setting: Callable[[], str]) -> None:
    """Where the display time zone comes from (the app passes the setting tradingview.timezone)."""
    global _timezone_setting
    _timezone_setting = setting


@lru_cache(maxsize=16)
def _zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def local_time(ms: int) -> datetime:
    """A UTC timestamp in the display time zone ('system' = this computer's)."""
    t = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    name = _timezone_setting()
    return t.astimezone() if name == "system" else t.astimezone(_zone(name))


def tz_label() -> str:
    """The display time zone as an offset, e.g. UTC+5 (used in column headers)."""
    minutes = int(local_time(int(time.time() * 1000)).utcoffset().total_seconds() // 60)
    if minutes == 0:
        return "UTC"
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{'+' if minutes > 0 else '-'}{hours}" + (f":{rest:02d}" if rest else "")


def when(ms: int | None) -> str:
    return local_time(ms).strftime("%m-%d %H:%M") if ms else "–"


def ago(seconds: float | None) -> str:
    if seconds is None:
        return "never"
    if seconds < 90:
        return f"{seconds:.0f}s ago"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min ago"
    if seconds < 172_800:
        return f"{seconds / 3600:.1f} h ago"
    return f"{seconds / 86400:.0f} days ago"


def tone(v: float | None) -> str:
    return "" if v is None or v == 0 else "profit" if v > 0 else "loss"


# ---- layout ----------------------------------------------------------------------------------
def page_header(title: str, intro: str) -> None:
    with ui.column().classes("gap-1"):
        ui.label(title).classes("page-title")
        ui.label(intro).classes("page-intro")


@contextmanager
def card(title: str | None = None, sub: str | None = None, classes: str = ""):
    with ui.column().classes(f"card gap-3 {classes}") as col:
        if title:
            with ui.column().classes("gap-0"):
                ui.label(title).classes("card-title")
                if sub:
                    ui.label(sub).classes("card-sub")
        yield col


class Tile:
    """A KPI tile: label, big value, small line under it. Update with set()."""

    def __init__(self, label: str, help_text: str = "") -> None:
        with ui.column().classes("card gap-1 min-w-[150px] flex-1"):
            with ui.row().classes("items-center gap-1"):
                ui.label(label).classes("tile-label")
                if help_text:
                    ui.icon("info_outline", size="14px").classes("muted").tooltip(help_text)
            self.value = ui.label("–").classes("tile-value num")
            self.sub = ui.label("").classes("tile-sub")

    def set(self, value: str, sub: str = "", value_tone: str = "") -> None:
        self.value.set_text(value)
        self.value.classes(remove="profit loss", add=value_tone)
        self.sub.set_text(sub)


def status_pill(status: str, text: str):
    color = STATUS.get(status, "#898781")
    with ui.element("span").classes("pill") as pill:
        ui.icon(STATUS_ICON.get(status, "circle"), size="14px").style(f"color:{color}")
        ui.label(text)
    return pill


def kv(key: str, value: str, value_class: str = "") -> None:
    with ui.column().classes("gap-0"):
        ui.label(key).classes("kv-key")
        ui.label(value).classes(f"kv-value {value_class}")


def kpi_grid():
    return ui.element("div").classes("kpi-grid")


class ChartOrEmpty:
    """A chart that shows a short message instead of empty axes until there are at least two points."""

    def __init__(self, options: dict[str, Any], height: str, message: str) -> None:
        self.box = ui.column().classes("w-full").style(f"height:{height}")
        with self.box:
            self.chart = chart(options, height)
            self.msg = ui.column().classes("w-full chart-empty")
            with self.msg:
                empty(message, "show_chart")

    def show(self, has_data: bool) -> None:
        self.chart.set_visibility(has_data)
        self.msg.set_visibility(not has_data)


def empty(text: str, icon: str = "hourglass_empty") -> None:
    with ui.column().classes("items-center w-full py-6 gap-1"):
        ui.icon(icon, size="28px").classes("muted")
        ui.label(text).classes("muted text-sm text-center")


def progress(value: float, ok: bool) -> None:
    color = STATUS["good"] if ok else palette()["accent"]
    ui.linear_progress(value=max(0.0, min(1.0, value)), show_value=False, size="8px").props(
        f'rounded color="{color}" track-color="grey-9"' if mode() == "dark" else f'rounded color="{color}"')


# ---- charts ----------------------------------------------------------------------------------
def chart(options: dict[str, Any], height: str = "260px") -> ui.echart:
    base = chart_base(mode())
    merged = {**base, **options}
    for axis in ("xAxis", "yAxis"):
        if axis in options and isinstance(options[axis], dict):
            merged[axis] = {**base[axis], **options[axis]}
    if "tooltip" in options:
        merged["tooltip"] = {**base["tooltip"], **options["tooltip"]}
    return ui.echart(merged).classes("w-full").style(f"height:{height}")


def line_options(series: list[dict[str, Any]], y_name: str = "", money_axis: bool = False, area: bool = False) -> dict[str, Any]:
    p = palette()
    out = []
    for i, s in enumerate(series):
        color = s.get("color") or p["series"][i % len(p["series"])]
        item = {"type": "line", "name": s["name"], "data": s["data"], "showSymbol": False, "smooth": False,
                "lineStyle": {"width": 2, "color": color}, "itemStyle": {"color": color}, "step": s.get("step", False)}
        if area and i == 0:
            item["areaStyle"] = {"color": color, "opacity": 0.08}
        out.append(item)
    return {
        "xAxis": {"type": "time"},
        "yAxis": {"type": "value", "name": y_name, "scale": True,
                  "nameTextStyle": {"color": p["muted"], "fontSize": 11, "align": "left"}},
        "legend": {"show": len(series) > 1},
        "series": out,
    }


def bar_options(categories: list[str], values: list[float | None], signed: bool = True, horizontal: bool = False,
                fmt: str = "{c}") -> dict[str, Any]:
    p = palette()
    data = [{"value": v, "itemStyle": {"color": (p["profit"] if (v or 0) >= 0 else p["loss"]) if signed else p["accent"],
                                       "borderRadius": [4, 4, 0, 0] if not horizontal else [0, 4, 4, 0]}} for v in values]
    cat_axis = {"type": "category", "data": categories}
    val_axis = {"type": "value"}
    return {
        "xAxis": val_axis if horizontal else cat_axis,
        "yAxis": cat_axis if horizontal else val_axis,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "series": [{"type": "bar", "data": data, "barMaxWidth": 28, "label": {"show": False}}],
    }


def histogram_options(values: list[float], bins: list[float]) -> dict[str, Any]:
    p = palette()
    counts = [0] * (len(bins) - 1)
    for v in values:
        for i in range(len(bins) - 1):
            if bins[i] <= v < bins[i + 1] or (i == len(bins) - 2 and v >= bins[-1]) or (i == 0 and v < bins[0]):
                counts[i] += 1
                break
    labels = [f"{bins[i]:+.1f}…{bins[i + 1]:+.1f}" for i in range(len(bins) - 1)]
    data = [{"value": c, "itemStyle": {"color": p["profit"] if bins[i] >= 0 else p["loss"], "borderRadius": [4, 4, 0, 0]}}
            for i, c in enumerate(counts)]
    return {"xAxis": {"type": "category", "data": labels, "axisLabel": {"rotate": 0, "fontSize": 10}},
            "yAxis": {"type": "value", "name": "trades"},
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "series": [{"type": "bar", "data": data, "barCategoryGap": "8%"}]}


# ---- tables ----------------------------------------------------------------------------------
def column(name: str, label: str, align: str = "left", sortable: bool = True) -> dict[str, Any]:
    return {"name": name, "label": label, "field": name, "align": align, "sortable": sortable}


def signed_slot(table: ui.table, name: str, suffix: str = "", digits: int = 2) -> None:
    """Show a numeric column with a sign and profit/loss color (the sign keeps it readable without color)."""
    table.add_slot(f"body-cell-{name}", f"""
        <q-td :props="props" class="num">
          <span v-if="props.value === null || props.value === undefined" style="color:var(--muted)">–</span>
          <span v-else :class="props.value > 0 ? 'profit' : (props.value < 0 ? 'loss' : '')">
            {{{{ (props.value > 0 ? '+' : '') + Number(props.value).toFixed({digits}) }}}}{suffix}
          </span>
        </q-td>""")


def chip_slot(table: ui.table, name: str) -> None:
    table.add_slot(f"body-cell-{name}", """
        <q-td :props="props">
          <span class="pill" :style="props.value === 'open' ? 'border-color:var(--accent)' : ''">{{ props.value }}</span>
        </q-td>""")
