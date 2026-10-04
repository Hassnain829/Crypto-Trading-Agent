"""Learning: how the agent improves, what it has learned, and how strong the current strategy is."""

from __future__ import annotations

from nicegui import ui

from tradeagent.dashboard.data import Store
from tradeagent.dashboard.rules_text import describe
from tradeagent.dashboard.widgets import ago, card, chart, column, empty, palette, pct, rr, signed_slot, when

FORWARD_NEEDED = 50  # fresh trades a challenger needs before it can be promoted (Phase 5 rules)


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
                ("psychology", "4 · Research", "Claude studies the journal and proposes one change at a time (Phase 5)"),
                ("military_tech", "5 · Promote", "A variant that wins on history and fresh trades becomes the baseline"),
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

    with card("Challengers", "Each changes one thing from the baseline. Promotion needs a better result on history and "
              f"at least {FORWARD_NEEDED} fresh trades", classes="w-full"):
        table = ui.table(rows=[], row_key="id", pagination=20, columns=[
            column("name", "Variant"), column("trades", "Trades", "right"), column("win", "Win %", "right"),
            column("exp", "Expectancy", "right"), column("delta", "vs baseline", "right"),
            column("first", "1st half", "right"), column("second", "2nd half", "right"),
            column("fresh", f"Fresh trades (of {FORWARD_NEEDED})", "right"), column("verdict", "Status"),
        ]).classes("w-full").props("flat dense")
        for name in ("exp", "delta", "first", "second"):
            signed_slot(table, name, "R", 3)

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
                ui.label("The lessons file starts with the automatic research loop (Phase 5).").classes("muted text-sm")
        with card("Decisions", "From docs/REQUIREMENTS.md, newest first", classes="flex-[2] min-w-[320px]"):
            with ui.scroll_area().classes("w-full h-[520px]"):
                for dec in data["decisions"]:
                    with ui.column().classes("feed-row w-full gap-0"):
                        ui.label(dec["date"]).classes("muted text-xs num")
                        ui.label(dec["text"]).classes("text-sm")
    with ui.row().classes("w-full justify-end"):
        ui.button("Approve for live trading", icon="verified").props("unelevated").tooltip(
            "Becomes available in Phase 6, once the go-live gate is met").set_enabled(False)

    def refresh() -> None:
        variants = store.variants()
        rows = []
        base = next((v for v in variants if v["role"] == "baseline"), None)
        for v in variants:
            if v["role"] == "baseline":
                verdict = "baseline"
            elif v["delta_r"] is None or v["trades"] < 30:
                verdict = "collecting"
            elif v["delta_r"] >= 0.05:
                both = (v.get("first_expectancy_r") or 0) > ((base or {}).get("first_expectancy_r") or 0) \
                    and (v.get("second_expectancy_r") or 0) > ((base or {}).get("second_expectancy_r") or 0)
                if not both:
                    verdict = "ahead overall · mixed halves"
                elif v["forward_trades"] < FORWARD_NEEDED:
                    verdict = "ahead · needs fresh trades"
                else:
                    verdict = "ready to promote"
            elif v["delta_r"] <= -0.05:
                verdict = "behind"
            else:
                verdict = "even"
            rows.append({"id": v["variant"], "name": v["name"], "trades": v["trades"],
                         "win": round((v["win_rate"] or 0) * 100, 1), "exp": _r3(v["expectancy_r"]), "delta": _r3(v["delta_r"]),
                         "first": _r3(v.get("first_expectancy_r")), "second": _r3(v.get("second_expectancy_r")),
                         "fresh": f"{min(v['forward_trades'], FORWARD_NEEDED)} / {FORWARD_NEEDED}", "verdict": verdict})
        table.rows = rows
        table.update()

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
