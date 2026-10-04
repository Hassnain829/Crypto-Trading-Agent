"""The dashboard web app (NiceGUI): header, navigation and the six pages.

Run it with `python -m tradeagent dashboard`. It starts the agent (which opens TradingView in debug mode) and
starts it again after a crash; the agent is its own process, so if the dashboard stops, trading does not.
It listens on 127.0.0.1:8080 by default (no login, personal use).
"""

from __future__ import annotations

from nicegui import app, ui

from tradeagent import __version__
from tradeagent.config import load_settings
from tradeagent.dashboard.data import Store
from tradeagent.dashboard.pages import learning, overview, performance, settings_page, system, trades
from tradeagent.dashboard.theme import PALETTES, STATUS, css
from tradeagent.dashboard.widgets import ago, mode, use_timezone
from tradeagent.supervisor import Supervisor

NAV = [
    ("/", "Overview", "space_dashboard", overview.build),
    ("/trades", "Trades", "receipt_long", trades.build),
    ("/performance", "Performance", "insights", performance.build),
    ("/learning", "Learning", "psychology", learning.build),
    ("/settings", "Settings", "tune", settings_page.build),
    ("/system", "System", "monitor_heart", system.build),
]
_store: Store | None = None


def store() -> Store:
    assert _store is not None, "dashboard store not initialised"
    return _store


def root() -> None:
    m = mode()
    p = PALETTES[m]
    ui.add_css(css(m))
    ui.dark_mode(m == "dark")
    ui.colors(primary=p["accent"], positive=STATUS["good"], negative=STATUS["critical"], warning=STATUS["warning"])
    nav_items: dict[str, ui.row] = {}

    with ui.header().classes("items-center px-4 py-2 gap-3 no-wrap"):
        menu = ui.button(icon="menu").props("flat round dense")
        with ui.row().classes("items-center gap-2 no-wrap"):
            ui.icon("smart_toy", size="24px").style(f"color:{p['accent']}")
            ui.label("Crypt-AI Agent").classes("text-base font-bold")
        ui.label("DEMO").classes("pill").tooltip("Demo trading with simulated money. Live trading starts in Phase 6, "
                                                 "and only with your approval.")
        ui.space()
        status_box = ui.row().classes("items-center gap-2 no-wrap")

        def toggle_theme() -> None:
            app.storage.general["theme"] = "light" if mode() == "dark" else "dark"
            ui.navigate.reload()
        ui.button(icon="light_mode" if m == "dark" else "dark_mode", on_click=toggle_theme).props("flat round dense").tooltip(
            "Switch light / dark")

    with ui.left_drawer(value=True, fixed=True).props("width=220 breakpoint=900").classes("pt-3") as drawer:
        for path, label, icon, _ in NAV:
            with ui.row().classes("nav-item items-center gap-3 px-3 py-2 cursor-pointer no-wrap").on(
                    "click", lambda _, target=path: ui.navigate.to(target)) as item:
                ui.icon(icon, size="20px")
                ui.label(label).classes("text-sm")
            nav_items[path] = item
        ui.space()
        with ui.column().classes("px-4 pb-4 gap-0 absolute-bottom"):
            ui.label(f"tradeagent {__version__}").classes("muted text-xs")
            ui.label("127.0.0.1 only · no login").classes("muted text-xs")
    menu.on_click(drawer.toggle)

    def page(path: str, builder):
        def show() -> None:
            for target, item in nav_items.items():
                item.classes(remove="active")
            nav_items[path].classes(add="active")
            builder(store())
        return show

    def trade_page(trade_id: str) -> None:
        for item in nav_items.values():
            item.classes(remove="active")
        nav_items["/trades"].classes(add="active")
        trades.page(store(), trade_id)

    with ui.column().classes("w-full max-w-[1500px] mx-auto gap-4"):
        def settings_section(section: str) -> None:
            for item in nav_items.values():
                item.classes(remove="active")
            nav_items["/settings"].classes(add="active")
            settings_page.build(store(), section)

        ui.sub_pages({**{path: page(path, builder) for path, _, _, builder in NAV}, "/trade/{trade_id}": trade_page,
                      "/settings/{section}": settings_section})

    def refresh_header() -> None:
        s = store()
        status = s.agent_status()
        kill = s.kill_switch()
        status_box.clear()
        with status_box:
            names = {"running": ("good", "Agent running"), "starting": ("warning", "Agent starting"),
                     "stalled": ("serious", "Agent stalled"), "stopped": ("critical", "Agent stopped")}
            st, text = names[status["state"]]
            if status["state"] == "stopped" and status["wanted"] == "stopped":
                text = "Agent stopped (by you)"
            with ui.element("span").classes("pill").tooltip(f"Last cycle {ago(status['last_cycle_age_s'])}"):
                ui.icon("circle", size="10px").style(f"color:{STATUS[st]}")
                ui.label(text)
            if kill != "off":
                with ui.element("span").classes("pill"):
                    ui.icon("pause_circle", size="14px").style(f"color:{STATUS['warning']}")
                    ui.label("Paused" if kill == "pause" else "Closing all")

    refresh_header()
    ui.timer(5.0, refresh_header)


def run(host: str = "127.0.0.1", port: int = 8080, open_browser: bool = True, start_agent: bool = True) -> None:
    global _store
    settings = load_settings()
    _store = Store(settings)
    use_timezone(lambda: store().settings.tradingview.timezone)
    # Keeps the agent running (it opens TradingView in debug mode itself). With start_agent=False only the
    # Overview buttons start or stop it.
    _store.supervisor = Supervisor(settings, watch=start_agent)
    _store.supervisor.start()
    ui.run(root=root, host=host, port=port, title="Crypt-AI Agent", reload=False, show=open_browser,
           favicon="🤖", show_welcome_message=True, uvicorn_logging_level="warning")
