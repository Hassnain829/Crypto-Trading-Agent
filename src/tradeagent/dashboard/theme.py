"""Colors, CSS and chart styling for the dashboard (dark by default, light on request).

Palette roles follow the data-viz reference palette: one accent hue for single series, a fixed categorical
order for comparisons, reserved status colors that always come with an icon or a sign, hairline grids.
"""

from __future__ import annotations

from typing import Any

PALETTES: dict[str, dict[str, Any]] = {
    "dark": {
        "page": "#0d0d0d", "surface": "#1a1a19", "surface_2": "#222220", "border": "rgba(255,255,255,0.10)",
        "text": "#ffffff", "text_2": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a", "axis": "#383835",
        "accent": "#3987e5", "profit": "#0ca30c", "loss": "#e66767", "neutral": "#383835",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
    },
    "light": {
        "page": "#f9f9f7", "surface": "#fcfcfb", "surface_2": "#f0efec", "border": "rgba(11,11,11,0.10)",
        "text": "#0b0b0b", "text_2": "#52514e", "muted": "#898781", "grid": "#e1e0d9", "axis": "#c3c2b7",
        "accent": "#2a78d6", "profit": "#006300", "loss": "#d03b3b", "neutral": "#e1e0d9",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    },
}
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
STATUS_ICON = {"good": "check_circle", "warning": "warning", "serious": "error", "critical": "cancel", "idle": "radio_button_unchecked"}


def css(mode: str) -> str:
    p = PALETTES[mode]
    return f"""
    :root {{ --page: {p['page']}; --surface: {p['surface']}; --surface-2: {p['surface_2']}; --border: {p['border']};
             --text: {p['text']}; --text-2: {p['text_2']}; --muted: {p['muted']}; --accent: {p['accent']};
             --profit: {p['profit']}; --loss: {p['loss']}; --grid: {p['grid']}; }}
    body {{ background: var(--page); color: var(--text); font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
    .q-page, .nicegui-content {{ background: var(--page); }}
    .nicegui-content {{ padding: 20px 24px 40px; gap: 16px; }}
    .q-header {{ background: var(--surface) !important; color: var(--text) !important; border-bottom: 1px solid var(--border); }}
    .q-drawer {{ background: var(--surface) !important; border-right: 1px solid var(--border); }}
    .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; box-shadow: none; padding: 16px 18px; }}
    .card-title {{ font-size: 13px; font-weight: 600; color: var(--text-2); text-transform: uppercase; letter-spacing: .04em; }}
    .card-sub {{ font-size: 12px; color: var(--muted); }}
    .tile-label {{ font-size: 12px; color: var(--text-2); }}
    .tile-value {{ font-size: 26px; font-weight: 650; line-height: 1.15; color: var(--text); }}
    .tile-sub {{ font-size: 12px; color: var(--muted); }}
    .page-title {{ font-size: 22px; font-weight: 650; }}
    .page-intro {{ font-size: 13px; color: var(--text-2); max-width: 900px; }}
    .muted {{ color: var(--muted); }} .text-2 {{ color: var(--text-2); }}
    .profit {{ color: var(--profit) !important; }} .loss {{ color: var(--loss) !important; }}
    .num {{ font-variant-numeric: tabular-nums; }}
    .nav-item {{ border-radius: 8px; margin: 2px 8px; color: var(--text-2); }}
    .nav-item.active {{ background: var(--surface-2); color: var(--text); font-weight: 600; }}
    .nav-item:hover {{ background: var(--surface-2); }}
    .pill {{ display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px;
             font-size: 12px; font-weight: 600; border: 1px solid var(--border); background: var(--surface-2); }}
    .q-table__container {{ background: var(--surface) !important; border: 1px solid var(--border); border-radius: 12px; box-shadow: none; }}
    .q-table thead th {{ color: var(--text-2); font-weight: 600; font-size: 12px; }}
    .q-table tbody td {{ font-variant-numeric: tabular-nums; font-size: 13px; }}
    .q-table tbody tr {{ cursor: pointer; }}
    .q-tab {{ text-transform: none; font-weight: 600; }}
    .q-btn {{ text-transform: none; }}
    .q-tab-panel {{ width: 100%; }} .q-tab-panels {{ width: 100%; }}
    .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; width: 100%; }}
    .chart-empty {{ height: 100%; min-height: 200px; display: flex; align-items: center; justify-content: center; }}
    .feed-row {{ border-bottom: 1px solid var(--border); padding: 8px 0; }}
    .feed-row:last-child {{ border-bottom: none; }}
    .step-box {{ background: var(--surface-2); border-radius: 10px; padding: 10px 12px; min-width: 150px; flex: 1; }}
    .kv-key {{ color: var(--muted); font-size: 12px; }} .kv-value {{ font-size: 14px; font-variant-numeric: tabular-nums; }}
    .codeblock {{ font-family: Consolas, "Cascadia Mono", monospace; font-size: 12px; white-space: pre-wrap;
                  background: var(--surface-2); border-radius: 8px; padding: 10px; max-height: 520px; overflow: auto; }}
    .markdown-body h1 {{ font-size: 20px; }} .markdown-body h2 {{ font-size: 17px; margin-top: 18px; }}
    .markdown-body table {{ border-collapse: collapse; font-size: 13px; }}
    .markdown-body td, .markdown-body th {{ border: 1px solid var(--border); padding: 4px 8px; }}
    """


def chart_base(mode: str) -> dict[str, Any]:
    """Shared ECharts styling: recessive axes and grid, tooltip on hover, no animation flicker on refresh."""
    p = PALETTES[mode]
    axis = {"axisLine": {"lineStyle": {"color": p["axis"]}}, "axisTick": {"show": False},
            "axisLabel": {"color": p["muted"], "fontSize": 11}, "splitLine": {"lineStyle": {"color": p["grid"], "width": 1}}}
    return {
        "backgroundColor": "transparent",
        "animation": False,
        "textStyle": {"fontFamily": "system-ui, -apple-system, Segoe UI, sans-serif", "color": p["text_2"]},
        "grid": {"left": 8, "right": 16, "top": 28, "bottom": 8, "containLabel": True},
        "tooltip": {"trigger": "axis", "backgroundColor": p["surface"], "borderColor": p["axis"],
                    "textStyle": {"color": p["text"], "fontSize": 12}, "axisPointer": {"lineStyle": {"color": p["muted"]}}},
        "legend": {"textStyle": {"color": p["text_2"], "fontSize": 12}, "top": 0, "icon": "roundRect", "itemWidth": 12, "itemHeight": 4},
        "xAxis": {**axis, "splitLine": {"show": False}},
        "yAxis": {**axis, "axisLine": {"show": False}},
    }
