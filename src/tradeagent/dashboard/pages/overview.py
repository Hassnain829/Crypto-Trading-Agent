"""Overview: what the agent is doing right now."""

from __future__ import annotations

from nicegui import ui

from tradeagent.dashboard.data import Store, now_ms
from tradeagent.dashboard.theme import STATUS
from tradeagent.dashboard.widgets import (ChartOrEmpty, Tile, ago, card, column, empty, kpi_grid, line_options, money,
                                          local_time, palette, pct, rr, signed_slot, status_pill, tz_label,
                                          when)

FEED_COLORS = {"win": "profit", "loss": "loss", "warning": "", "error": "loss", "open": "", "setting": ""}


def build(store: Store) -> None:
    with ui.row().classes("w-full items-end justify-between"):
        with ui.column().classes("gap-1"):
            ui.label("Overview").classes("page-title")
            ui.label("The demo account trades every baseline signal with 2% risk; the shadow book tests every rule "
                      "variant on the same signals. Nothing here uses real money yet.").classes("page-intro")

    with kpi_grid():
        t_balance = Tile("Demo balance", "Realized balance of the demo account. Equity adds open positions at the last price.")
        t_today = Tile("Today (UTC)", "Closed and open trades since 00:00 UTC.")
        t_open = Tile("Open positions")
        t_edge = Tile("Strategy edge", "Average net R per trade of the baseline's shadow trades since the forward test started "
                      "(every signal, after fees, slippage and funding).")
        t_ready = Tile("Go-live readiness", "Checks of the go-live gate that are met. Live trading always needs your approval.")

    with ui.row().classes("w-full gap-4 items-stretch"):
        with card("Demo equity", "Balance after each closed trade", classes="flex-[2] min-w-[420px]"):
            eq = ChartOrEmpty(line_options([{"name": "Balance", "data": []}], "USDT", area=True), "290px",
                              "The curve starts with the first closed demo trade.")
        with card("Agent", "Reads TradingView, runs the shadow book and the demo account. The dashboard keeps it "
                  "running and restarts it after a crash.", classes="flex-1 min-w-[300px]"):
            agent_box = ui.column().classes("w-full gap-2")
            with ui.row().classes("gap-2"):
                start_btn = ui.button("Start", icon="play_arrow", on_click=lambda: agent_action("start")).props("outline dense")
                stop_btn = ui.button("Stop", icon="stop", on_click=lambda: agent_action("stop")).props("outline dense")
                restart_btn = ui.button("Restart", icon="restart_alt", on_click=lambda: agent_action("restart")).props(
                    "outline dense")

    with ui.row().classes("w-full gap-4 items-stretch"):
        with card("Open positions", "Demo account, valued at the last 1m close (exit costs included)",
                  classes="flex-[2] min-w-[420px]"):
            positions = ui.table(rows=[], row_key="id", columns=[
                column("coin", "Coin"), column("tf", "TF"), column("side", "Side"), column("since", f"Since ({tz_label()})"),
                column("entry", "Entry", "right"), column("stop", "Stop", "right"), column("target", "Target", "right"),
                column("last", "Last", "right"), column("pnl", "Open PnL $", "right"), column("r", "Open R", "right"),
            ]).classes("w-full").props("flat dense")
            signed_slot(positions, "pnl")
            signed_slot(positions, "r", "R")
            no_positions = ui.column().classes("w-full")
        with ui.column().classes("flex-1 min-w-[300px] gap-4"):
            with card("Today"):
                today_box = ui.grid(columns=2).classes("w-full gap-3")
            with card("Kill switch", "Stops the demo account (and live trading later). The shadow book keeps learning."):
                kill_box = ui.column().classes("w-full gap-2")

    with ui.row().classes("w-full gap-4 items-stretch"):
        with card("Activity", "Demo trades, warnings and setting changes", classes="flex-[2] min-w-[420px]"):
            feed_box = ui.column().classes("w-full gap-0")
        with card("Data feeds", f"Last TradingView read per chart and the last {store.settings.venue} candle",
                  classes="flex-1 min-w-[300px]"):
            health_box = ui.column().classes("w-full gap-1")

    def confirm_kill(mode: str) -> None:
        texts = {"off": "Resume trading: the demo account takes new signals again.",
                 "pause": "Pause: no new demo entries. Open positions keep running to their stop or target.",
                 "close_all": "Close all: every open demo position is closed at the last price in the next cycle, "
                              "then new entries stay paused."}
        with ui.dialog() as dialog, ui.card().classes("card gap-3 min-w-[380px]"):
            ui.label("Kill switch").classes("card-title")
            ui.label(texts[mode])
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat")

                def go() -> None:
                    store.set_kill_switch(mode)
                    dialog.close()
                    ui.notify(f"Kill switch set to {mode.replace('_', ' ')}", type="positive")
                    if mode == "off" and store.supervisor:  # resuming needs a running agent
                        if store.supervisor.start_agent() == "started":
                            ui.notify("Agent starting; TradingView opens in debug mode if needed", type="info")
                    refresh()
                ui.button("Confirm", on_click=go).props("unelevated color=negative" if mode == "close_all" else "unelevated")
        dialog.open()

    def agent_action(action: str) -> None:
        sup = store.supervisor
        if sup is None:
            ui.notify("Agent control is not available in this dashboard process", type="warning")
            return
        if action == "start":
            result = sup.start_agent()
            ui.notify("Agent is already running" if result == "already running"
                      else "Agent starting; TradingView opens in debug mode if needed", type="positive")
            refresh()
            return
        texts = {"stop": "Stop the agent: no TradingView reads, no demo trades and no learning until you press Start. "
                         "It stays stopped after a dashboard restart. It finishes the current step first (a few seconds).",
                 "restart": "Restart the agent: it finishes the current step, stops, and starts again within a minute."}
        with ui.dialog() as dialog, ui.card().classes("card gap-3 min-w-[380px]"):
            ui.label(f"{action.title()} the agent").classes("card-title")
            ui.label(texts[action])
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat")

                def go() -> None:
                    sup.stop_agent() if action == "stop" else sup.restart_agent()
                    dialog.close()
                    ui.notify("Stop requested" if action == "stop" else "Restart requested", type="positive")
                    refresh()
                ui.button("Confirm", on_click=go).props("unelevated color=negative" if action == "stop" else "unelevated")
        dialog.open()

    def refresh() -> None:
        paper = store.paper()
        gate = store.gate()
        status = store.agent_status()
        health = store.health()
        today = store.today()
        p = palette()

        t_balance.set(money(paper["balance"]), f"equity {money(paper['equity'])}")
        t_today.set(money(paper["today_pnl"], sign=True), pct(paper["today_pct"] / 100, 2, sign=True),
                    "profit" if paper["today_pnl"] > 0 else "loss" if paper["today_pnl"] < 0 else "")
        t_open.set(str(len(paper["positions"])), f"{paper['closed']} closed since the forward start")
        exp = gate["strategy_expectancy_r"]
        t_edge.set(rr(exp), f"{gate['strategy_trades']} shadow trades · win {pct(gate['strategy_win_rate'])}",
                   "profit" if exp and exp > 0 else "loss" if exp and exp < 0 else "")
        met = sum(1 for c in gate["gate"] if c["ok"])
        t_ready.set(f"{met} / {len(gate['gate'])}", f"day {gate['days_running']:.1f} of {store.settings.goal.min_days}")

        curve = store.equity_curve()
        eq.chart.options["series"][0]["data"] = [[t, round(v, 2)] for t, v in curve]
        eq.chart.update()
        eq.show(len(curve) > 1)

        positions.rows = [{"id": x["id"], "coin": x["symbol"], "tf": x["timeframe"], "side": x["side"],
                           "since": when(x["entry_time"]), "entry": f"{x['entry_fill']:g}", "stop": f"{x['stop']:g}",
                           "target": "", "last": f"{x['last_price']:g}" if x["last_price"] else "–",
                           "pnl": round(x["unrealized_usd"], 2), "r": round(x["unrealized_r"], 2)} for x in paper["positions"]]
        positions.update()
        positions.set_visibility(bool(paper["positions"]))
        no_positions.clear()
        if not paper["positions"]:
            with no_positions:
                empty("No open positions. New signals appear here as soon as the agent takes them.", "inbox")

        agent_box.clear()
        with agent_box:
            labels = {"running": ("good", "Running"), "starting": ("warning", "Starting"),
                      "stalled": ("serious", "No cycle for a while"), "stopped": ("critical", "Stopped")}
            st, text = labels[status["state"]]
            if status["state"] == "stopped" and status["wanted"] == "stopped":
                text = "Stopped by you (press Start)"
            elif status["state"] == "stopped":
                text = "Stopped: the dashboard starts it again within a minute"
            elif status["state"] == "starting":  # the first read is at the next 5-minute candle close
                first_read = (now_ms() // 300_000 + 1) * 300_000
                text = f"Starting: first read at {local_time(first_read).strftime('%H:%M')}"
            status_pill(st, text)
            beat = status["heartbeat"] or {}
            offset = beat.get("clock_offset_ms")
            rows = [("Last cycle", ago(status["last_cycle_age_s"])),
                    ("Snapshots in the last cycle", f"{beat.get('snapshots_ok', 0)}/{beat.get('snapshots', 0)} ok"
                     if beat else "–"),
                    ("Read latency", f"{beat.get('max_latency_s', 0):.1f} s" if beat else "–"),
                    ("Running since", when(status["started_at"]) if status["state"] != "stopped" else "–"),
                    ("Strategy", f"{store.baseline_version()} ({store.baseline_id or '–'})"),
                    ("RAM / CPU", f"{health['machine']['ram_used_pct']:.0f}% / {health['machine']['cpu_pct']:.0f}%"),
                    ("PC clock vs exchange", "–" if offset is None else f"{-offset / 1000:+.1f} s (corrected)")]
            for k, v in rows:
                with ui.row().classes("w-full justify-between"):
                    ui.label(k).classes("text-2 text-sm")
                    ui.label(v).classes("text-sm num")
            if offset is not None and abs(offset) > 1000:
                ui.label("This computer's clock is off by more than a second. The agent corrects for it with "
                         "exchange's server time; turning on Windows time sync keeps the logs exact.").classes("muted text-xs")
            running = status["state"] != "stopped"
            start_btn.set_enabled(not running)
            stop_btn.set_enabled(running)
            restart_btn.set_enabled(running)

        today_box.clear()
        with today_box:
            for label, value in (("Snapshots read", today["snapshots"]), ("Baseline signals", today["signals"]),
                                 ("Demo opened", today["paper_opened"]), ("Demo closed", today["paper_closed"]),
                                 ("Shadow trades opened", today["shadow_opened"]), ("Shadow trades closed", today["shadow_closed"])):
                with ui.column().classes("gap-0"):
                    ui.label(label).classes("kv-key")
                    ui.label(f"{value:,}").classes("text-lg font-semibold num")

        kill = store.kill_switch()
        kill_box.clear()
        with kill_box:
            names = {"off": ("good", "Trading"), "pause": ("warning", "Paused: no new entries"),
                     "close_all": ("serious", "Closing everything")}
            status_pill(*names.get(kill, ("idle", kill)))
            with ui.row().classes("gap-2"):
                ui.button("Resume", icon="play_arrow", on_click=lambda: confirm_kill("off")).props(
                    "outline dense").set_enabled(kill != "off")
                ui.button("Pause", icon="pause", on_click=lambda: confirm_kill("pause")).props(
                    "outline dense").set_enabled(kill != "pause")
                ui.button("Close all", icon="stop", on_click=lambda: confirm_kill("close_all")).props("outline dense color=negative")

        feed_box.clear()
        with feed_box:
            items = store.feed()
            if not items:
                empty("Nothing yet. Trades and warnings show up here.", "notifications_none")
            for item in items:
                with ui.row().classes("feed-row w-full items-start gap-3 no-wrap"):
                    ui.icon(item["icon"], size="18px").classes(FEED_COLORS.get(item["kind"], "") or "muted")
                    ui.label(item["text"]).classes(f"text-sm flex-1 {FEED_COLORS.get(item['kind'], '')}")
                    ui.label(when(item["ts"])).classes("muted text-xs num")

        health_box.clear()
        with health_box:
            for c in health["charts"]:
                with ui.row().classes("w-full justify-between items-center"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("circle", size="10px").style(
                            f"color:{STATUS['good'] if c['status'] == 'good' else STATUS['warning'] if c['status'] == 'warning' else p['muted']}")
                        ui.label(f"{c['symbol']} {c['timeframe']}").classes("text-sm")
                    ui.label(ago(c["age_s"])).classes("text-sm muted num")
            b = health["binance"]
            ui.separator()
            with ui.row().classes("w-full justify-between"):
                ui.label(f"{store.settings.venue} 1m candles").classes("text-sm")
                ui.label(ago(b["age_s"])).classes("text-sm muted num")

    refresh()
    ui.timer(5.0, refresh)
