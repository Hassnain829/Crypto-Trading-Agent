"""Settings: account limits, live limits with a live preview, exchange keys, costs, gate, rules and more."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

from nicegui import run, ui

from tradeagent import exchanges
from tradeagent.config import PaperAccountConfig
from tradeagent.dashboard.data import Store
from tradeagent.dashboard.widgets import (ChartOrEmpty, Tile, card, column, line_options, mode, money, pct, status_pill,
                                          tz_label, when)
from tradeagent.journal.db import now_ms
from tradeagent.settings_store import GROUPS, EditableField, audit_log, current, reset_value, set_value
from tradeagent.venues import get_venue

SECTIONS = [
    ("account", "Demo account", "account_balance_wallet"),
    ("live", "Live limits & preview", "shield"),
    ("exchanges", "Exchanges", "key"),
    ("costs", "Costs", "receipt"),
    ("gate", "Go-live gate", "flag"),
    ("rules", "Strategy rules", "rule"),
    ("markets", "Markets", "currency_bitcoin"),
    ("tradingview", "TradingView", "candlestick_chart"),
    ("research", "Research", "psychology"),
    ("audit", "Audit log", "history"),
]
GROUP_FOR = {"account": 0, "live": 1, "costs": 2, "gate": 3, "tradingview": 4, "research": 5, "exchanges": 6}


def build(store: Store, section: str = "account") -> None:
    with ui.column().classes("gap-1"):
        ui.label("Settings").classes("page-title")
        ui.label("Changes are checked before they are saved and written to the audit log. Settings marked "
                 "'next cycle' apply within five minutes; the others when the agent restarts.").classes("page-intro")
    with ui.row().classes("w-full gap-4 no-wrap items-start"):
        with ui.tabs().props("vertical dense inline-label").classes("w-[230px] shrink-0 card p-1") as tabs:
            tab = {key: ui.tab(key, label=label, icon=icon).props("no-caps").classes("justify-start") for key, label, icon in SECTIONS}
        tabs.on_value_change(lambda e: ui.navigate.history.replace(f"/settings/{e.value}"))
        with ui.tab_panels(tabs, value=tab.get(section, tab["account"])).props("vertical animated=false").classes(
                "flex-1 min-w-0 bg-transparent"):
            groups = list(GROUPS.items())
            for key in ("account", "costs", "gate", "tradingview", "research"):
                with ui.tab_panel(tab[key]).classes("p-0"):
                    title, fields = groups[GROUP_FOR[key]]
                    form_group(store, title, fields)
                    if key == "tradingview":
                        tradingview_info(store)
            with ui.tab_panel(tab["live"]).classes("p-0 gap-4"):
                title, fields = groups[GROUP_FOR["live"]]
                inputs = form_group(store, title, fields)
                live_preview_panel(store, inputs)
            with ui.tab_panel(tab["exchanges"]).classes("p-0 gap-4"):
                title, fields = groups[GROUP_FOR["exchanges"]]
                form_group(store, title, fields)
                venue_panel(store)
                exchanges_panel(store)
            with ui.tab_panel(tab["rules"]).classes("p-0"):
                rules_panel(store)
            with ui.tab_panel(tab["markets"]).classes("p-0"):
                markets_panel(store)
            with ui.tab_panel(tab["audit"]).classes("p-0"):
                audit_panel(store)


# ---- generic form for editable settings -----------------------------------------------------------
def _to_input(f: EditableField, value: Any) -> Any:
    if value is None:
        return None
    if f.kind in ("percent", "optpercent"):
        return round(value * 100, 4)
    return value


def _from_input(f: EditableField, value: Any, all_coins: list[str] | None = None) -> Any:
    if f.kind == "coins":  # every coin (or none picked) = no restriction
        picked = [c for c in (all_coins or []) if c in (value or [])]
        return None if not picked or picked == all_coins else picked
    if f.kind in ("optint", "optpercent") and (value is None or value == ""):
        return None
    if f.kind in ("percent", "optpercent"):
        return round(float(value) / 100, 6)
    if f.kind in ("int", "optint"):
        return int(value)
    if f.kind in ("money", "float"):
        return float(value)
    return value


def form_group(store: Store, title: str, fields: list[EditableField]) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    with card(title, classes="w-full"):
        settings, defaults = store.settings, store.defaults
        with ui.grid(columns=2).classes("w-full gap-x-8 gap-y-4"):
            for f in fields:
                value = _to_input(f, current(settings, f.path))
                default = current(defaults, f.path)
                overridden = current(settings, f.path) != default
                with ui.column().classes("gap-1"):
                    if f.kind == "bool":
                        el = ui.switch(f.label, value=bool(value))
                    elif f.kind == "select":
                        names = dict(f.labels)
                        options = {c: names.get(c, c.title()) for c in f.choices}
                        options.setdefault(value, str(value))  # a value set in settings.yaml outside the list
                        el = ui.select(options, value=value, label=f.label).classes("w-full")
                    elif f.kind == "time":
                        el = ui.input(f.label, value=value).props("mask='##:##'").classes("w-full")
                    elif f.kind == "coins":
                        coins = list(settings.exchange.symbols)
                        el = ui.select(coins, value=value or coins, label=f.label, multiple=True).classes("w-full").props(
                            "use-chips")
                    else:
                        suffix = {"money": "$", "percent": "%", "optpercent": "%"}.get(f.kind, "")
                        step = (f.step * 100 if f.step and f.kind in ("percent", "optpercent") else f.step) or (
                            1 if f.kind in ("int", "optint", "money") else 0.1)
                        el = ui.number(f.label, value=value, step=step, suffix=suffix,
                                       placeholder="no limit" if f.kind in ("optint", "optpercent") else "",
                                       format="%.0f" if f.kind in ("int", "optint") else None).classes("w-full").props("clearable"
                                                                                                                   if f.kind in ("optint", "optpercent") else "")
                    inputs[f.path] = (f, el)
                    with ui.row().classes("items-center gap-2"):
                        ui.label("next cycle" if f.live else "on restart").classes("pill").style("font-size:11px")
                        default_text = "off / no limit" if default is None else (
                            f"{default * 100:g}%" if f.kind in ("percent", "optpercent") else str(default))
                        if f.kind == "coins":
                            default_text = "all coins" if default is None else ", ".join(default)
                        ui.label(f"default {default_text}").classes("muted text-xs")
                        if overridden:
                            ui.link("reset", "#").classes("text-xs").on(
                                "click.prevent", lambda _, path=f.path: (_reset(store, path)))
                    if f.help:
                        ui.label(f.help).classes("muted text-xs")

        def save() -> None:
            errors, saved = [], 0
            for path, (f, el) in inputs.items():
                try:
                    value = _from_input(f, el.value, list(store.settings.exchange.symbols))
                except (TypeError, ValueError):
                    errors.append(f"{f.label}: not a valid number")
                    continue
                if value == current(store.settings, path):
                    continue
                problem = set_value(store.conn, store.settings, path, value)
                if problem:
                    errors.append(f"{f.label}: {problem}")
                else:
                    saved += 1
                store.invalidate()
            if errors:
                ui.notify("Not saved: " + "; ".join(errors), type="negative", multi_line=True, timeout=8000)
            elif saved:
                ui.notify(f"Saved {saved} change{'s' if saved > 1 else ''}", type="positive")
            else:
                ui.notify("Nothing changed")

        with ui.row().classes("w-full justify-end"):
            ui.button("Save changes", icon="save", on_click=save).props("unelevated")
    return inputs


def _reset(store: Store, path: str) -> None:
    reset_value(store.conn, store.settings, store.defaults, path)
    store.invalidate()
    ui.notify(f"{path} reset to the settings.yaml value; reload the page to see it", type="info")


# ---- live preview ----------------------------------------------------------------------------
def live_preview_panel(store: Store, inputs: dict[str, Any]) -> None:
    with card("Live preview", "Replays the baseline's shadow trades through the limits above (saved or not). "
              "Nothing is traded or stored.", classes="w-full"):
        with ui.row().classes("items-center gap-3"):
            period = ui.select({"forward": "Forward test", "30d": "Last 30 days", "all": "All history"}, value="all",
                               label="Period").classes("w-44")
            button = ui.button("Run preview", icon="play_arrow").props("unelevated")
        with ui.row().classes("w-full gap-4"):
            t_result, t_dd, t_rate, t_taken = Tile("Result"), Tile("Max drawdown"), Tile("Trades per day"), Tile("Signals taken")
        with ui.row().classes("w-full gap-4 items-start"):
            with ui.column().classes("flex-[2] min-w-[380px]"):
                eq = ChartOrEmpty(line_options([{"name": "Balance", "data": []}], "USDT", area=True), "240px",
                                  "No closed trades in this period.")
            skipped_box = ui.column().classes("flex-1 min-w-[260px] gap-1")

        async def go() -> None:
            values = {}
            for path, (f, el) in inputs.items():
                key = path.split(".", 1)[1]
                if key == "exchange":
                    continue
                try:
                    values[key] = _from_input(f, el.value, list(store.settings.exchange.symbols))
                except (TypeError, ValueError):
                    ui.notify(f"{f.label}: not a valid number", type="negative")
                    return
            try:
                rules = PaperAccountConfig(**values)
            except Exception as exc:  # pydantic validation message for the user
                ui.notify(f"Invalid limits: {exc}", type="negative", multi_line=True)
                return
            button.props("loading")
            result = await run.io_bound(_preview_in_thread, store.defaults.resolve(store.defaults.journal.path),
                                        store.settings, rules, store.period_start(period.value))
            button.props(remove="loading")
            t_result.set(money(result["net_pnl"], sign=True), pct(result["return_pct"] / 100, 1, sign=True)
                         + f" from {money(result['start_balance'])}",
                         "profit" if result["net_pnl"] > 0 else "loss" if result["net_pnl"] < 0 else "")
            t_dd.set(pct(result["max_drawdown"]), f"target ≤ {pct(store.settings.goal.max_drawdown, 0)}")
            t_rate.set(f"{result['trades_per_day']:.1f}", "closed trades per day")
            t_taken.set(f"{result['taken']} / {result['signals']}", "the rest were skipped by the limits")
            curve = [[result["equity"][0][0] - 1, result["start_balance"]]] if result["equity"] else []
            eq.chart.options["series"][0]["data"] = curve + [[ts, round(v, 2)] for ts, v in result["equity"]]
            eq.chart.update()
            eq.show(len(result["equity"]) > 0)
            skipped_box.clear()
            with skipped_box:
                ui.label("Skipped signals").classes("card-title")
                if not result["skipped"]:
                    ui.label("None: every signal was taken").classes("muted text-sm")
                for reason, n in result["skipped"].items():
                    with ui.row().classes("w-full justify-between"):
                        ui.label(reason).classes("text-sm")
                        ui.label(str(n)).classes("text-sm num")

        button.on_click(go)
        ui.timer(0.2, go, once=True)  # show the current limits' result right away


def _preview_in_thread(journal: Path, settings: Any, rules: PaperAccountConfig, since: int | None) -> dict[str, Any]:
    """Runs in a worker thread with its own connection (sqlite connections are not shared across threads)."""
    from tradeagent.account.preview import live_preview

    conn = sqlite3.connect(journal, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        return live_preview(conn, settings, rules, since=since)
    finally:
        conn.close()


# ---- exchanges -------------------------------------------------------------------------------
def exchanges_panel(store: Store) -> None:
    env_file = store.defaults.root / ".env"
    with ui.column().classes("w-full gap-1 mb-2"):
        ui.label("Keys stay on this computer: they are written to the project's .env file (never committed to git) and "
                 "shown masked. Use keys with read + futures trading only. Never enable withdrawals.").classes("text-2 text-sm")
        ui.label(f"Trading exchange: {get_venue(store.settings.venue).label}. Demo trades are filled with its prices and "
                 "live orders (Phase 6) will go there. Signals keep coming from the TradingView charts.").classes(
            "muted text-xs")
    box = ui.row().classes("w-full gap-4 items-stretch")

    def render() -> None:
        box.clear()
        status = exchanges.status(env_file)
        with box:
            for key, spec in exchanges.EXCHANGES.items():
                st = status[key]
                with ui.column().classes("card gap-3 flex-1 min-w-[300px]"):
                    with ui.row().classes("w-full items-center justify-between"):
                        with ui.column().classes("gap-0"):
                            ui.label(spec.name).classes("text-lg font-semibold")
                            ui.label(spec.market).classes("muted text-xs")
                        status_pill("good" if st["configured"] else "idle", "Keys saved" if st["configured"] else "Not connected")
                    for label, masked in st["masked"].items():
                        with ui.row().classes("w-full justify-between"):
                            ui.label(label).classes("text-2 text-sm")
                            ui.label(masked or "–").classes("text-sm num")
                    result = ui.label().classes("text-xs")
                    with ui.row().classes("gap-2"):
                        ui.button("Replace keys" if st["configured"] else "Add keys", icon="key",
                                  on_click=lambda _, k=key: key_dialog(k)).props("unelevated dense")

                        async def test(_, k=key, out=result) -> None:
                            out.set_text("Testing…")
                            ok, message = await run.io_bound(exchanges.test_connection, k, exchanges.read(env_file, k))
                            out.set_text(message)
                            out.classes(remove="profit loss", add="profit" if ok else "loss")
                        ui.button("Test connection", icon="network_check", on_click=test).props(
                            "outline dense").set_enabled(st["configured"])
                        if st["configured"]:
                            ui.button(icon="delete", on_click=lambda _, k=key: remove_dialog(k)).props(
                                "flat dense color=negative").tooltip("Remove these keys")

    def key_dialog(key: str) -> None:
        spec = exchanges.EXCHANGES[key]
        with ui.dialog() as dialog, ui.card().classes("card gap-3 w-[560px] max-w-[95vw]"):
            ui.label(f"{spec.name} API key").classes("text-lg font-semibold")
            with ui.column().classes("gap-1"):
                ui.label("How to create it").classes("card-title")
                for i, step in enumerate(spec.steps, 1):
                    ui.label(f"{i}. {step}").classes("text-sm")
                ui.link(f"Open {spec.name} API management", spec.url, new_tab=True).classes("text-sm")
            fields = {}
            for f in spec.fields:
                if f.multiline:  # a PEM private key keeps its line breaks only in a text area
                    fields[f.name] = ui.textarea(f.label, placeholder=f.hint).classes("w-full").props(
                        "autocomplete=off autogrow input-style='font-family:monospace;font-size:11px'")
                else:
                    fields[f.name] = ui.input(f.label, password=True, password_toggle_button=True,
                                              placeholder=f.hint).classes("w-full").props("autocomplete=off")
            warn = ui.label().classes("text-xs loss")

            def save(force: bool = False) -> None:
                values = {k: (el.value or "").strip() for k, el in fields.items()}
                problems = exchanges.check(key, values)
                blocking = [p for p in problems if p.endswith("is empty")]
                if blocking or (problems and not force):
                    warn.set_text("; ".join(problems) + ("" if blocking else ". Press 'Save anyway' if you are sure."))
                    save_anyway.set_visibility(not blocking)
                    return
                exchanges.save(env_file, key, values)
                with store.conn:
                    store.conn.execute("INSERT INTO settings_audit (ts, key, old_json, new_json, source) VALUES (?, ?, ?, ?, ?)",
                                       (now_ms(), f"exchange.{key}.keys", '"(hidden)"', '"saved (hidden)"', "dashboard"))
                dialog.close()
                ui.notify(f"{spec.name} keys saved to .env. Press 'Test connection' to check them.", type="positive")
                render()

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat")
                save_anyway = ui.button("Save anyway", on_click=lambda: save(True)).props("outline")
                save_anyway.set_visibility(False)
                ui.button("Save keys", icon="save", on_click=lambda: save(False)).props("unelevated")
        dialog.open()

    def remove_dialog(key: str) -> None:
        spec = exchanges.EXCHANGES[key]
        with ui.dialog() as dialog, ui.card().classes("card gap-3"):
            ui.label(f"Remove the {spec.name} keys from .env?")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat")

                def go() -> None:
                    exchanges.remove(env_file, key)
                    with store.conn:
                        store.conn.execute("INSERT INTO settings_audit (ts, key, old_json, new_json, source)"
                                           " VALUES (?, ?, ?, ?, ?)", (now_ms(), f"exchange.{key}.keys", '"(hidden)"',
                                                                       '"removed"', "dashboard"))
                    dialog.close()
                    render()
                ui.button("Remove", on_click=go).props("unelevated color=negative")
        dialog.open()

    render()


# ---- strategy rules (config/setups.yaml) ------------------------------------------------------
def rules_panel(store: Store) -> None:
    from tradeagent.setups.config import load_variants
    from tradeagent.tv.catalog import load_catalog

    path = store.defaults.resolve(store.defaults.shadow.setups)
    catalog = load_catalog(store.defaults.resolve(store.defaults.tradingview.catalog))
    with card("Strategy rules", "config/setups.yaml: the baseline and its manual one-change variants (Claude's experiments "
              "are on the Learning page). Saved rules apply in the next agent cycle; changed rules get a new variant id and "
              "start collecting trades from zero.", classes="w-full"):
        editor = ui.codemirror(path.read_text(encoding="utf-8"), language="YAML",
                               theme="vscodeDark" if mode() == "dark" else "vscodeLight").classes("w-full h-[520px] min-w-0")
        result = ui.column().classes("w-full gap-1")

        def validate() -> list | None:
            result.clear()
            with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as fh:
                fh.write(editor.value)
                tmp = Path(fh.name)
            try:
                variants = load_variants(tmp, catalog)
            except Exception as exc:
                with result:
                    ui.label(f"Not valid: {exc}").classes("loss text-sm")
                return None
            finally:
                tmp.unlink(missing_ok=True)
            with result:
                ui.label(f"Valid: baseline {variants[0].id} and {len(variants) - 1} variants").classes("profit text-sm")
                ui.label(", ".join(v.id for v in variants[1:])).classes("muted text-xs")
            return variants

        def save() -> None:
            if validate() is None:
                return
            old = path.read_text(encoding="utf-8")
            if old == editor.value:
                ui.notify("Nothing changed")
                return
            backups = store.defaults.resolve("data/backups")
            backups.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backups / f"setups-{time.strftime('%Y%m%d-%H%M%S')}.yaml")
            path.write_text(editor.value, encoding="utf-8")
            digest = lambda text: hashlib.sha256(text.encode()).hexdigest()[:10]  # noqa: E731
            with store.conn:
                store.conn.execute("INSERT INTO settings_audit (ts, key, old_json, new_json, source) VALUES (?, ?, ?, ?, ?)",
                                   (now_ms(), "setups.yaml", f'"{digest(old)}"', f'"{digest(editor.value)}"', "dashboard"))
            ui.notify("Saved (a backup is in data/backups). The agent uses the new rules from its next cycle.", type="positive")

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Revert", icon="undo", on_click=lambda: editor.set_value(path.read_text(encoding="utf-8"))).props("flat")
            ui.button("Validate", icon="fact_check", on_click=validate).props("outline")
            ui.button("Save", icon="save", on_click=save).props("unelevated")


# ---- read-only panels --------------------------------------------------------------------------
def venue_panel(store: Store) -> None:
    s = store.settings
    venue = get_venue(s.venue)
    with card(venue.label, "The exchange the demo trades are filled on now", classes="w-full"):
        for k, v in (("Who can use it", venue.who), ("Fees", venue.fee_note or "see the exchange"),
                     ("Settles in", venue.settle), ("Markets", ", ".join(f"{c} {m}" for c, m in s.markets().items())),
                     ("Simulated costs", f"maker {s.costs.maker_fee:.3%}, taker {s.costs.taker_fee:.3%}, "
                                         f"slippage {s.costs.slippage:.3%} (Settings > Costs)")):
            with ui.row().classes("w-full gap-3 no-wrap items-start"):
                ui.label(k).classes("kv-key w-[130px] shrink-0")
                ui.label(v).classes("text-sm")
        ui.label("Before switching, compare the edge on the new exchange: "
                 ".venv\\Scripts\\python -m tradeagent venue-replay <exchange> --balance 1000").classes("muted text-xs")


def markets_panel(store: Store) -> None:
    s = store.settings
    venue = get_venue(s.venue)
    with card("Markets", f"Signals from the TradingView charts; trades filled on {venue.label}", classes="w-full"):
        rows = [{"id": coin, "coin": coin, "market": s.market(coin), "tv": c.tradingview, "layout": f"AGENT-{coin}"}
                for coin, c in s.exchange.symbols.items()]
        ui.table(rows=rows, row_key="id", columns=[column("coin", "Coin"), column("tv", "Signal chart (TradingView)"),
                                                   column("market", f"Market on {venue.id}"),
                                                   column("layout", "Layout")]).classes("w-full").props("flat dense")
        with ui.row().classes("gap-8 mt-2"):
            with ui.column().classes("gap-0"):
                ui.label("Trading timeframes").classes("kv-key")
                ui.label(", ".join(s.timeframes.trade)).classes("kv-value")
            with ui.column().classes("gap-0"):
                ui.label("Higher timeframes").classes("kv-key")
                ui.label(", ".join(s.timeframes.overview)).classes("kv-value")
        ui.label("Adding a coin needs its own TradingView layout with the 5 indicators, and TradingView Essential's 5 layouts "
                 "are all in use. Ask Claude to set a new coin up (symbol cycling or a bigger plan).").classes("muted text-xs")


def tradingview_info(store: Store) -> None:
    tv = store.settings.tradingview
    with card("Connection", classes="w-full mt-4"):
        with ui.row().classes("gap-8"):
            for k, v in (("Debug port", f"{tv.cdp_host}:{tv.cdp_port}"), ("Signal version", str(tv.signal_version)),
                         ("History kept per chart", f"{tv.min_bars} bars"), ("Read delay", f"{tv.read_delay_s:g} s")):
                with ui.column().classes("gap-0"):
                    ui.label(k).classes("kv-key")
                    ui.label(v).classes("kv-value")
        ui.table(rows=[{"id": k, "layout": k, "layout_id": v} for k, v in tv.layouts.items()], row_key="id",
                 columns=[column("layout", "Layout"), column("layout_id", "Layout id")]).classes("w-full").props("flat dense")


def audit_panel(store: Store) -> None:
    with card("Audit log", "Every setting change: when, what, old → new, and from where", classes="w-full"):
        table = ui.table(rows=[], row_key="id", pagination=25, columns=[
            column("time", f"Time ({tz_label()})"), column("key", "Setting"), column("old", "Old"), column("new", "New"),
            column("source", "Source")]).classes("w-full").props("flat dense")

        def load() -> None:
            table.rows = [{"id": i, "time": when(r["ts"]), "key": r["key"], "old": r["old_json"], "new": r["new_json"],
                           "source": r["source"]} for i, r in enumerate(audit_log(store.conn))]
            table.update()
        load()
        ui.timer(10.0, load)
