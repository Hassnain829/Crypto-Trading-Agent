"""Learning: how the agent improves, what it has learned, and how strong the current strategy is."""

from __future__ import annotations

import json

from nicegui import ui

from tradeagent.dashboard.data import Store
from tradeagent.learning import experiments as ex
from tradeagent.dashboard.rules_text import describe
from tradeagent.dashboard.widgets import ago, card, chart, column, empty, palette, pct, rr, signed_slot, when

STATUS_TEXT = {
    "screening": "replaying the history", "running": "forward test", "reconfirming": "won once · re-confirming",
    "promoted": "promoted", "lost": "lost", "rejected": "failed on history", "stopped": "stopped",
}
STATUS_ICON = {"promoted": "military_tech", "lost": "close", "rejected": "block", "stopped": "pause_circle",
               "running": "science", "reconfirming": "verified", "screening": "history"}


def build(store: Store) -> None:
    with ui.column().classes("gap-1"):
        ui.label("Learning").classes("page-title")
        ui.label("The agent never changes its own rules in secret. Every idea becomes a variant that runs beside the baseline "
                 "on the same signals; only ideas that win on old and fresh data replace it.").classes("page-intro")

    data = store.learning()
    tested = data["tested"]
    with card("How the agent learns", classes="w-full"):
        with ui.row().classes("w-full gap-3 items-stretch"):
            steps = [
                ("visibility", "1 · Watch", f"{tested['snapshots']:,} indicator snapshots read from TradingView"),
                ("science", "2 · Test every idea", f"{tested['active']} active variants simulated on every signal"),
                ("receipt_long", "3 · Record", f"{tested['shadow_trades']:,} shadow trades with fees, slippage and funding"),
                ("psychology", "4 · Research", "Claude reads the daily research pack and proposes one change at a time"),
                ("military_tech", "5 · Promote", "An idea that wins on history, then forward, then again on fresh trades "
                                                 "becomes the baseline"),
            ]
            for icon, title, text in steps:
                with ui.column().classes("step-box gap-1"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon(icon, size="20px").style(f"color:{palette()['accent']}")
                        ui.label(title).classes("font-semibold text-sm")
                    ui.label(text).classes("text-2 text-xs")

    with ui.row().classes("w-full gap-4 items-stretch"):
        with card("Strategy versions", "Net R per trade of each baseline on the history it was chosen on",
                  classes="flex-1 min-w-[420px]"):
            history = data["history"]
            if history:
                p = palette()
                chart({
                    "xAxis": {"type": "category", "data": [h["version"] for h in history]},
                    "yAxis": {"type": "value", "name": "R per trade"},
                    "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
                    "series": [{"type": "bar", "barMaxWidth": 46, "data": [
                        {"value": h["expectancy_r"], "itemStyle": {"color": p["profit"] if (h["expectancy_r"] or 0) >= 0
                                                                   else p["loss"], "borderRadius": [4, 4, 0, 0]}}
                        for h in history],
                        "label": {"show": True, "position": "top", "color": p["text_2"], "formatter": "{c}R"}}],
                }, "250px")
            else:
                empty("No versions recorded yet.")
        with card("Version history", classes="flex-1 min-w-[420px]"):
            for h in reversed(history):
                with ui.row().classes("w-full items-start gap-3 no-wrap feed-row"):
                    ui.label(h["version"]).classes("pill")
                    with ui.column().classes("gap-0 flex-1"):
                        ui.label(h["summary"]).classes("text-sm")
                        ui.label(f"{when(h['adopted_at'])} · {h['trades']} trades · {rr(h['expectancy_r'])} per trade · "
                                 f"demo account {h['paper_return_pct']:+.1f}% on that history").classes("muted text-xs")

    with ui.row().classes("w-full gap-4 items-stretch"):
        with card("Current baseline", "The rules the demo account trades", classes="flex-1 min-w-[420px]"):
            base = data["baseline"]
            if base:
                ui.label(base["id"]).classes("pill")
                for k, v in describe(base["params"]):
                    with ui.row().classes("w-full gap-3 no-wrap"):
                        ui.label(k).classes("kv-key w-[110px] shrink-0")
                        ui.label(v).classes("text-sm")
            else:
                empty("No baseline registered yet. Start the agent once.")
        with card("Strength", "How much the current strategy can be trusted", classes="flex-1 min-w-[420px]"):
            strength_box = ui.column().classes("w-full gap-3")

    exps = store.experiments()
    rules = exps["rules"]
    with card("Experiments", f"Each changes one rule of the baseline. A winner needs {rules['min_trades']} trades on both "
              f"sides, {rules['min_edge_r']:+g}R or more per trade, a profit factor not lower and a drawdown at most "
              f"{rules['max_drawdown_worse']:.0%} worse; then it must stay ahead on {rules['reconfirm_trades']} fresh trades",
              classes="w-full min-w-0"):
        counts_label = ui.label().classes("muted text-xs")
        wrap = "white-space: normal; min-width: 150px; max-width: 240px"
        table = ui.table(rows=[], row_key="id", pagination=15, columns=[
            column("name", "Experiment"), {**column("change", "Change"), "style": wrap, "headerStyle": wrap},
            column("source", "From"), column("status", "Status"), column("since", "Since"),
            column("ch_trades", "Trades", "right"), column("ch_exp", "Its R/trade", "right"),
            column("base_exp", "Baseline same period", "right"), column("delta", "Difference", "right"),
            column("progress", "Progress", "right"), column("history", "All history", "right"),
            column("actions", "", "right", sortable=False),
        ]).classes("w-full").style("max-width: 100%").props("flat dense wrap-cells")
        for name in ("ch_exp", "base_exp", "delta", "history"):
            signed_slot(table, name, "R", 3)
        table.add_slot("body-cell-actions", """
            <q-td :props="props">
              <template v-if="props.row.can_act">
                <q-btn flat dense round size="sm" icon="military_tech" :color="props.row.confirmed ? 'positive' : 'grey'"
                       @click="$parent.$emit('promote', props.row)"><q-tooltip>Promote to the demo baseline</q-tooltip></q-btn>
                <q-btn flat dense round size="sm" icon="stop_circle" color="grey"
                       @click="$parent.$emit('stop', props.row)"><q-tooltip>Stop this experiment</q-tooltip></q-btn>
              </template>
            </q-td>""")
        ui.label("Promote writes the change into config/setups.yaml (a backup goes to data/backups) and the demo trades it "
                 "from the next cycle. Live trading always needs your separate approval.").classes("muted text-xs")

    with ui.row().classes("w-full gap-4 items-stretch"):
        with card("Experiment timeline", "Every decision, newest first. Many tests make lucky winners more likely, "
                  "which is why winners must win twice", classes="flex-[3] min-w-[420px]"):
            timeline_box = ui.column().classes("w-full gap-0")
        with card("Research pack", "What Claude reads before it proposes anything (written every day)",
                  classes="flex-[2] min-w-[320px]"):
            if exps["pack"]:
                ui.label(f"Written {when(exps['pack']['at'])}").classes("muted text-xs")
                with ui.expansion("Open the latest pack", icon="description").classes("w-full"):
                    ui.markdown(exps["pack"]["text"]).classes("markdown-body w-full")
            else:
                empty("No research pack yet: the agent writes one every day (or run: python -m tradeagent research-pack).")
            ui.label("Run the research yourself in Claude Code with /research, or turn on the daily run in "
                     "Settings → Research.").classes("muted text-xs mt-2")

    with ui.row().classes("w-full gap-4 items-stretch"):
        with card("Research notes", "What was tested and why; written after every research round", classes="flex-[3] min-w-[420px]"):
            if data["docs"]:
                for doc in data["docs"]:
                    with ui.expansion(doc["title"], icon="article").classes("w-full"):
                        ui.markdown(doc["text"]).classes("markdown-body w-full")
            else:
                empty("No research notes yet.")
            ui.label("Lessons").classes("card-title mt-2")
            if data["lessons"]:
                ui.markdown(data["lessons"]).classes("markdown-body")
            else:
                ui.label("No lessons yet: every experiment decision writes one to research/lessons.md.").classes("muted text-sm")
        with card("Decisions", "From docs/REQUIREMENTS.md, newest first", classes="flex-[2] min-w-[320px]"):
            with ui.scroll_area().classes("w-full h-[520px]"):
                for dec in data["decisions"]:
                    with ui.column().classes("feed-row w-full gap-0"):
                        ui.label(dec["date"]).classes("muted text-xs num")
                        ui.label(dec["text"]).classes("text-sm")
    with ui.row().classes("w-full justify-end"):
        ui.button("Approve for live trading", icon="verified").props("unelevated").tooltip(
            "Becomes available in Phase 6, once the go-live gate is met").set_enabled(False)

    def promote_dialog(row: dict) -> None:
        early = not row["confirmed"]
        with ui.dialog() as dialog, ui.card().classes("card gap-3 w-[520px] max-w-[95vw]"):
            ui.label(f"Promote {row['name']}?").classes("card-title")
            ui.label(f"The demo account will trade the baseline with: {row['change']}.")
            if early:
                with ui.row().classes("items-start gap-2 no-wrap"):
                    ui.icon("warning", size="20px").classes("loss")
                    ui.label(f"Not proven yet: {row['rules_text']}; it has not won twice. Promoting now skips the test "
                             "and is recorded as an early promotion.").classes("text-sm")
            else:
                ui.label("It beat the baseline and stayed ahead on fresh trades.").classes("text-sm profit")
            ui.label("config/setups.yaml gets the change (backup in data/backups); the other experiments restart their "
                     "comparison against the new baseline.").classes("muted text-xs")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat")

                def go() -> None:
                    try:
                        message = ex.promote(store.conn, store.settings, row["id"], by="dashboard", early=early)
                    except (ValueError, OSError) as exc:
                        ui.notify(f"Not promoted: {exc}", type="negative", multi_line=True)
                        return
                    dialog.close()
                    store.invalidate()
                    ui.notify(f"{message}. The agent uses it from its next cycle.", type="positive")
                    refresh()
                ui.button("Promote anyway" if early else "Promote", on_click=go).props(
                    "unelevated color=negative" if early else "unelevated")
        dialog.open()

    def stop_dialog(row: dict) -> None:
        with ui.dialog() as dialog, ui.card().classes("card gap-3 w-[480px] max-w-[95vw]"):
            ui.label(f"Stop {row['name']}?").classes("card-title")
            ui.label("It stops collecting trades and is recorded as stopped, with your reason as its lesson.").classes("text-sm")
            if row["source"] == "setups.yaml":
                ui.label("It is a manual challenger: remove its line from config/setups.yaml too, or it will run again "
                         "as a new experiment.").classes("muted text-xs")
            reason = ui.input("Reason").classes("w-full")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat")

                def go() -> None:
                    if not reason.value.strip():
                        ui.notify("Write a short reason first", type="warning")
                        return
                    ex.stop(store.conn, row["id"], f"{reason.value.strip()} (dashboard)")
                    dialog.close()
                    store.invalidate()
                    ui.notify(f"{row['name']} stopped", type="positive")
                    refresh()
                ui.button("Stop", on_click=go).props("unelevated color=negative")
        dialog.open()

    table.on("promote", lambda e: promote_dialog(e.args))
    table.on("stop", lambda e: stop_dialog(e.args))

    def refresh() -> None:
        data = store.experiments()
        history = {v["variant"]: v["expectancy_r"] for v in store.variants()}
        counts_label.set_text(" · ".join(f"{n} {STATUS_TEXT[k]}" for k, n in data["counts"].items() if n)
                              or "No experiments yet.")
        rows = []
        for e in data["rows"]:
            ch, base = e.get("challenger") or {}, e.get("baseline") or {}
            reconfirm = e["status"] == "reconfirming"
            need = data["rules"]["reconfirm_trades"] if reconfirm else data["rules"]["min_trades"]
            have = min(ch.get("trades") or 0, base.get("trades") or 0)
            both = ch.get("expectancy_r") is not None and base.get("expectancy_r") is not None
            rows.append({
                "can_act": e["status"] in ("running", "reconfirming") and e["name"] not in ex.REFERENCE,
                "confirmed": e["status"] == "reconfirming" and (e.get("result") or {}).get("phase") == "reconfirm",
                "rules_text": f"{min(have, need)} of {need} trades on both sides" + (" (fresh trades after its first win)"
                                                                                     if reconfirm else ""),
                "id": e["id"], "name": e["name"], "change": _change(e["change"]), "source": e["source"],
                "status": STATUS_TEXT[e["status"]], "since": when(e["reconfirm_from"] or e["started_at"]),
                "ch_trades": ch.get("trades") or 0, "ch_exp": _r3(ch.get("expectancy_r")),
                "base_exp": _r3(base.get("expectancy_r")),
                "delta": _r3(ch["expectancy_r"] - base["expectancy_r"]) if both else None,
                "progress": f"{min(have, need)} / {need}" if e["status"] in ("running", "reconfirming") else "–",
                "history": _r3(history.get(e["variant_id"])),
                "_order": (0 if e["status"] in ("screening", "running", "reconfirming") else 1, -e["id"]),
            })
        rows.sort(key=lambda r: r.pop("_order"))
        table.rows = rows
        table.update()
        timeline_box.clear()
        with timeline_box:
            events = sorted(data["rows"], key=lambda e: -(e["decided_at"] or e["created_at"]))
            if not events:
                empty("No experiments yet.")
            for e in events[:40]:
                with ui.row().classes("w-full items-start gap-3 no-wrap feed-row"):
                    ui.icon(STATUS_ICON[e["status"]], size="20px").classes(
                        "profit" if e["status"] == "promoted" else "loss" if e["status"] in ("lost", "rejected") else "muted")
                    with ui.column().classes("gap-0 flex-1"):
                        ui.label(f"{e['name']} · {_change(e['change'])}").classes("text-sm font-semibold")
                        ui.label(f"{STATUS_TEXT[e['status']]} · {when(e['decided_at'] or e['created_at'])}"
                                 f" · from {e['source']}").classes("muted text-xs")
                        if e.get("hypothesis") and e["source"] != "setups.yaml":
                            ui.label(e["hypothesis"]).classes("text-2 text-xs")
                        if e.get("lesson"):
                            ui.label(e["lesson"].splitlines()[-1]).classes("text-xs")

        gate = store.gate()
        hist = store.strategy("all")
        status = store.agent_status()
        cov = gate["snapshot_coverage"]
        strength_box.clear()
        with strength_box:
            items = [
                ("Edge (all history)", rr(hist["expectancy_r"]),
                 f"95% range {hist['ci'][0]:+.2f} … {hist['ci'][1]:+.2f}R over {hist['trades']} trades" if hist["ci"] else "needs more trades",
                 hist["ci"] is not None and hist["ci"][0] > 0),
                ("Edge (forward test)", rr(gate["strategy_expectancy_r"]), f"{gate['strategy_trades']} fresh trades so far",
                 (gate["strategy_expectancy_r"] or 0) > 0),
                ("Consistency", pct(hist["positive_windows"], 0) if hist["positive_windows"] is not None else "–",
                 "of 50-trade stretches ended positive", (hist["positive_windows"] or 0) >= 0.6),
                ("Data quality", pct(cov), "of expected TradingView reads in the last 7 days", cov >= 0.99),
                ("Reliability", {"running": "Running", "starting": "Starting", "stalled": "Stalled", "stopped": "Stopped"}[status["state"]],
                 f"last cycle {ago(status['last_cycle_age_s'])}", status["state"] == "running"),
                ("Risk (live limits)", pct(gate["live_preview"]["max_drawdown"]),
                 f"max drawdown of the live preview, target ≤ {pct(store.settings.goal.max_drawdown, 0)}",
                 gate["live_preview"]["taken"] > 0 and gate["live_preview"]["max_drawdown"] <= store.settings.goal.max_drawdown),
            ]
            for label, value, sub, good in items:
                with ui.row().classes("w-full items-center gap-3 no-wrap"):
                    ui.icon("check_circle" if good else "pending", size="20px").classes("profit" if good else "muted")
                    ui.label(label).classes("text-sm w-[150px] shrink-0")
                    ui.label(value).classes("text-base font-semibold num w-[90px]")
                    ui.label(sub).classes("muted text-xs")

    refresh()
    ui.timer(30.0, refresh)


def _r3(v: float | None) -> float | None:
    return None if v is None else round(v, 3)


def _change(change: dict) -> str:
    """{"filters": {"session_utc": [13, 21]}} -> filters.session_utc = [13, 21]."""
    parts: list[str] = []

    def walk(node: dict, prefix: str) -> None:
        for key, value in node.items():
            if isinstance(value, dict):
                walk(value, f"{prefix}{key}.")
            else:
                parts.append(f"{prefix}{key} = {json.dumps(value)}")
    walk(change, "")
    return ", ".join(parts)
