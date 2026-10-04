"""System: logs, events, data quality, machine resources and indicator settings versions."""

from __future__ import annotations

from nicegui import ui

from tradeagent.dashboard.data import Store
from tradeagent.dashboard.widgets import card, chart, column, empty, line_options, palette, tz_label, when


def build(store: Store) -> None:
    with ui.column().classes("gap-1"):
        ui.label("System").classes("page-title")
        ui.label("What the agent is doing under the hood: its log, warnings, how complete the data is, and the machine.").classes(
            "page-intro")
    with ui.tabs().props("align=left dense").classes("w-full") as tabs:
        t_logs, t_events, t_quality = ui.tab("Agent log", icon="terminal"), ui.tab("Events", icon="notifications"), ui.tab(
            "Data quality", icon="fact_check")
        t_res, t_ind = ui.tab("Resources", icon="memory"), ui.tab("Indicator settings", icon="tune")
    with ui.tab_panels(tabs, value=t_logs).classes("w-full bg-transparent"):
        with ui.tab_panel(t_logs).classes("p-0"):
            logs_panel(store)
        with ui.tab_panel(t_events).classes("p-0"):
            events_panel(store)
        with ui.tab_panel(t_quality).classes("p-0 gap-4"):
            quality_panel(store)
        with ui.tab_panel(t_res).classes("p-0"):
            resources_panel(store)
        with ui.tab_panel(t_ind).classes("p-0"):
            indicators_panel(store)


def logs_panel(store: Store) -> None:
    with card("Agent log", "data/logs/agent.log, newest first", classes="w-full"):
        with ui.row().classes("items-center gap-3"):
            level = ui.select(["DEBUG", "INFO", "WARNING", "ERROR"], value="INFO", label="Level").classes("w-36")
            search = ui.input("Search", placeholder="e.g. cycle, paper, watchdog").classes("w-72").props("clearable")
            follow = ui.switch("Live", value=True).tooltip("Reload every 5 seconds")
        area = ui.scroll_area().classes("w-full h-[560px] codeblock")
        with area:
            text = ui.label().classes("whitespace-pre-wrap")

        def load() -> None:
            lines = store.log_lines(level.value, search.value or "")
            text.set_text("\n".join(reversed(lines)) if lines else "No log lines yet. The agent writes here while it runs.")

        level.on_value_change(lambda _: load())
        search.on_value_change(lambda _: load())
        load()
        ui.timer(5.0, lambda: follow.value and load())


def events_panel(store: Store) -> None:
    with card("Events", "Warnings and errors the agent recorded in the journal, plus watchdog actions", classes="w-full"):
        with ui.row().classes("items-center gap-3"):
            level = ui.select({None: "All levels", "INFO": "Info", "WARNING": "Warning", "ERROR": "Error"}, value=None,
                              label="Level").classes("w-36")
            source = ui.select({None: "All sources", "reader": "Reader", "watchdog": "Watchdog", "engine": "Engine",
                                "agent": "Agent", "resources": "Resources", "doctor": "Doctor"}, value=None,
                               label="Source").classes("w-40")
        table = ui.table(rows=[], row_key="id", pagination=25, columns=[
            column("time", f"Time ({tz_label()})"), column("level", "Level"), column("source", "Source"), column("message", "Message")]).classes(
            "w-full").props("flat dense")

        def load() -> None:
            table.rows = [{"id": i, "time": when(e["ts"]), "level": e["level"], "source": e["source"], "message": e["message"]}
                          for i, e in enumerate(store.events(level.value, source.value))]
            table.update()
        level.on_value_change(lambda _: load())
        source.on_value_change(lambda _: load())
        load()
        ui.timer(10.0, load)


def quality_panel(store: Store) -> None:
    with card("TradingView coverage", "Closed candles that should have been read, and how many were read without problems",
              classes="w-full"):
        hours = ui.toggle({24: "24 hours", 168: "7 days"}, value=24).props("no-caps unelevated")
        table = ui.table(rows=[], row_key="id", columns=[
            column("chart", "Chart"), column("expected", "Expected", "right"), column("ok", "Read OK", "right"),
            column("missed", "Missed", "right"), column("coverage", "Coverage", "right"), column("p50", "Latency p50", "right"),
            column("p95", "Latency p95", "right")]).classes("w-full").props("flat dense")

        def load() -> None:
            rows = []
            for r in store.coverage(hours.value):
                expected = r["expected"]
                rows.append({"id": f"{r['symbol']}{r['timeframe']}", "chart": f"{r['symbol']} {r['timeframe']}",
                             "expected": expected, "ok": r["ok"], "missed": expected - r["ok"],
                             "coverage": f"{r['ok'] / expected * 100:.1f}%" if expected else "–",
                             "p50": f"{r['latency_p50_s']:.1f} s" if r.get("latency_p50_s") is not None else "–",
                             "p95": f"{r['latency_p95_s']:.1f} s" if r.get("latency_p95_s") is not None else "–"})
            table.rows = rows
            table.update()
        hours.on_value_change(lambda _: load())
        load()
    with card("Candle gaps", f"Missing {store.settings.venue} 1m candles in the last 48 hours (repaired automatically "
              "when the exchange has them)",
              classes="w-full"):
        gaps = store.gaps()
        if gaps:
            ui.table(rows=[{"id": i, "symbol": g["symbol"], "from": when(g["from"]), "to": when(g["to"]), "minutes": g["minutes"]}
                           for i, g in enumerate(gaps)], row_key="id",
                     columns=[column("symbol", "Coin"), column("from", "From"), column("to", "To"),
                              column("minutes", "Minutes", "right")]).classes("w-full").props("flat dense")
        else:
            empty("No gaps.", "check_circle")


def resources_panel(store: Store) -> None:
    history = store.resources_history()
    p = palette()
    with ui.row().classes("w-full gap-4 items-stretch"):
        with card("RAM used", "Whole machine, hourly, last 7 days", classes="flex-1 min-w-[420px]"):
            if history:
                chart(line_options([{"name": "RAM %", "data": [[t, d.get("ram_used_pct")] for t, d in history],
                                     "color": p["series"][0]}], "%"), "240px")
            else:
                empty("The agent records this once an hour while it runs.")
        with card("TradingView memory", "MB used by TradingView Desktop", classes="flex-1 min-w-[420px]"):
            if history:
                chart(line_options([{"name": "TradingView MB", "data": [[t, d.get("tradingview_mb")] for t, d in history],
                                     "color": p["series"][1]}], "MB"), "240px")
            else:
                empty("The agent records this once an hour while it runs.")


def indicators_panel(store: Store) -> None:
    with card("Indicator settings versions", "A new version is created when any indicator input changes on an AGENT chart; "
              "results are compared only within one version", classes="w-full"):
        rows = store.indicator_versions()
        if rows:
            ui.table(rows=[{"id": r["signal_version"], "version": r["signal_version"], "hash": r["settings_hash"][:16],
                            "since": when(r["created_at"])} for r in rows], row_key="id",
                     columns=[column("version", "Version"), column("hash", "Settings hash"), column("since", "Since")]).classes(
                "w-full").props("flat dense")
        else:
            empty("No versions recorded yet.")
