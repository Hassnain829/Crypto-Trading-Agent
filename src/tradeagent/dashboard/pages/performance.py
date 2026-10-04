"""Performance: the demo account's money view, the strategy's statistics, breakdowns and the go-live gate."""

from __future__ import annotations

from nicegui import ui

from tradeagent.dashboard.data import Store
from tradeagent.dashboard.widgets import (ChartOrEmpty, Tile, bar_options, card, chart, column, empty, histogram_options,
                                          kpi_grid, line_options, money, palette, pct, progress, rr, signed_slot)

PERIODS = {"forward": "Forward test", "30d": "Last 30 days", "all": "All history"}


def build(store: Store) -> None:
    with ui.row().classes("w-full items-end justify-between"):
        with ui.column().classes("gap-1"):
            ui.label("Performance").classes("page-title")
            ui.label("Money view of the demo account, and the strategy's statistics from the baseline's shadow trades "
                     "(every signal, after fees, slippage and funding).").classes("page-intro")
        period = ui.toggle(PERIODS, value="all").props("no-caps unelevated")

    ui.label("Demo account (since the forward test started)").classes("card-title mt-2")
    with kpi_grid():
        t_pnl, t_ret, t_win = Tile("Net PnL"), Tile("Account %"), Tile("Win rate")
        t_exp, t_pf, t_dd, t_fees = Tile("Expectancy"), Tile("Profit factor"), Tile("Max drawdown"), Tile("Fees paid")

    with ui.row().classes("w-full gap-4 items-stretch"):
        with card("Equity", "Demo balance after each closed trade", classes="flex-1 min-w-[420px]"):
            eq = ChartOrEmpty(line_options([{"name": "Balance", "data": []}], "USDT", area=True), "260px",
                              "Starts with the first closed demo trade.")
        with card("Drawdown", "Distance below the previous balance high", classes="flex-1 min-w-[420px]"):
            dd = ChartOrEmpty(line_options([{"name": "Drawdown", "data": []}], "%", area=True), "260px",
                              "Starts with the first closed demo trade.")
    with card("Daily PnL", "Closed demo trades per UTC day", classes="w-full"):
        daily = ChartOrEmpty(bar_options([], []), "220px", "One bar per day with closed demo trades.")

    strat_title = ui.label().classes("card-title mt-4")
    with kpi_grid():
        s_trades, s_win, s_exp, s_pf = Tile("Shadow trades"), Tile("Win rate"), Tile(
            "Expectancy", "Average net R per trade, with its 95% range."), Tile("Profit factor")
    with ui.row().classes("w-full gap-4 items-stretch"):
        with card("Cumulative R", "Running total of the baseline's net R", classes="flex-1 min-w-[420px]"):
            cum = chart(line_options([{"name": "Total R", "data": []}], "R"), "260px")
        with card("Result per trade", "How many trades ended in each R band", classes="flex-1 min-w-[420px]"):
            hist = chart(histogram_options([], [-1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2]), "260px")

    with card("Breakdowns", "The baseline's shadow trades split by one property at a time", classes="w-full"):
        breakdown_box = ui.column().classes("w-full")

    with card("Go-live gate", "All checks must pass before live trading; you still decide", classes="w-full"):
        gate_box = ui.column().classes("w-full gap-3")

    def refresh() -> None:
        p = palette()
        paper = store.paper()
        curve = store.equity_curve()
        t_pnl.set(money(paper["balance"] - paper["start"], sign=True), f"{paper['closed']} closed trades",
                  "profit" if paper["balance"] > paper["start"] else "loss" if paper["balance"] < paper["start"] else "")
        t_ret.set(pct(paper["return_pct"] / 100, 2, sign=True), f"from {money(paper['start'])}")
        t_win.set(pct(paper["win_rate"]), "of closed demo trades")
        t_exp.set(rr(paper["expectancy_r"]), "net R per trade")
        gate = store.gate()
        t_pf.set("–" if gate["profit_factor"] is None else f"{gate['profit_factor']:.2f}", "gross wins / gross losses")
        peak, worst, dd_points = None, 0.0, []
        for ts, bal in curve:
            peak = bal if peak is None else max(peak, bal)
            d = (bal - peak) / peak * 100 if peak else 0.0
            worst = min(worst, d)
            dd_points.append([ts, round(d, 2)])
        t_dd.set(f"{abs(worst):.1f}%", "largest drop from a high")
        t_fees.set(money(paper["fees"]), "entry and exit fees")
        eq.chart.options["series"][0]["data"] = [[ts, round(v, 2)] for ts, v in curve]
        eq.chart.update()
        eq.show(len(curve) > 1)
        series = dd.chart.options["series"][0]
        series["data"] = dd_points
        series["lineStyle"]["color"] = series["itemStyle"]["color"] = p["loss"]
        series["areaStyle"] = {"color": p["loss"], "opacity": 0.08}
        dd.chart.update()
        dd.show(len(curve) > 1)
        days = store.daily_pnl()
        daily.chart.options.update(bar_options([d for d, _ in days], [round(v, 2) for _, v in days]))
        daily.chart.update()
        daily.show(bool(days))

        per = period.value
        strat_title.set_text(f"Strategy · baseline shadow trades · {PERIODS[per].lower()}")
        s = store.strategy(per)
        s_trades.set(f"{s['trades']:,}", f"total {s['total_r']:+.1f}R")
        s_win.set(pct(s["win_rate"]), "of closed shadow trades")
        ci = s["ci"]
        s_exp.set(rr(s["expectancy_r"]), f"95% range {ci[0]:+.2f} … {ci[1]:+.2f}R" if ci else "needs more trades",
                  "profit" if (s["expectancy_r"] or 0) > 0 else "loss" if (s["expectancy_r"] or 0) < 0 else "")
        s_pf.set("–" if s["profit_factor"] is None else f"{s['profit_factor']:.2f}",
                 f"positive in {pct(s['positive_windows'], 0)} of 50-trade windows" if s["positive_windows"] is not None else "")
        cum.options["series"][0]["data"] = [[ts, round(v, 2)] for ts, v in s["cumulative_r"]]
        cum.update()
        hist.options.update(histogram_options(s["r_values"], [-1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2]))
        hist.update()

        breakdown_box.clear()
        with breakdown_box:
            groups = store.breakdowns(per)
            variants = store.variants()
            with ui.tabs().props("align=left dense") as tabs:
                names = ["Variant"] + list(groups)
                tab_items = {n: ui.tab(n) for n in names}
            with ui.tab_panels(tabs, value=tab_items["Variant"]).classes("w-full bg-transparent"):
                with ui.tab_panel(tab_items["Variant"]).classes("p-0"):
                    rows = [{"id": v["variant"], "group": v["name"] + (" (baseline)" if v["role"] == "baseline" else ""),
                             "trades": v["trades"], "win_rate": round((v["win_rate"] or 0) * 100, 1),
                             "expectancy_r": _round(v["expectancy_r"], 3), "total_r": round(v["total_r"], 1),
                             "profit_factor": _round(v["profit_factor"], 2), "delta": _round(v["delta_r"], 3)} for v in variants]
                    _group_table(rows, with_delta=True)
                for name, items in groups.items():
                    with ui.tab_panel(tab_items[name]).classes("p-0"):
                        rows = [{"id": g["group"], "group": g["group"], "trades": g["trades"],
                                 "win_rate": round((g["win_rate"] or 0) * 100, 1), "expectancy_r": _round(g["expectancy_r"], 3),
                                 "total_r": round(g["total_r"], 1), "profit_factor": _round(g["profit_factor"], 2)} for g in items]
                        if rows:
                            _group_table(rows)
                        else:
                            empty("No trades in this period yet.")

        gate_box.clear()
        with gate_box:
            met = sum(1 for c in gate["gate"] if c["ok"])
            ui.label(f"{met} of {len(gate['gate'])} checks met"
                     + (" · GATE MET: ready for your approval" if gate["gate_met"] else "")).classes("text-sm font-semibold")
            for c in gate["gate"]:
                with ui.row().classes("w-full items-center gap-4 no-wrap"):
                    ui.icon("check_circle" if c["ok"] else "radio_button_unchecked", size="20px").classes(
                        "profit" if c["ok"] else "muted")
                    ui.label(c["name"][:1].upper() + c["name"][1:]).classes("text-sm w-[300px]")
                    with ui.column().classes("flex-1"):
                        progress(c["progress"], c["ok"])
                    ui.label(c["value"]).classes("text-sm num w-[220px] text-right")

    period.on_value_change(lambda _: refresh())
    refresh()
    ui.timer(30.0, refresh)


def _round(v: float | None, digits: int) -> float | None:
    return None if v is None else round(v, digits)


def _group_table(rows: list[dict], with_delta: bool = False) -> None:
    cols = [column("group", "Group"), column("trades", "Trades", "right"), column("win_rate", "Win %", "right"),
            column("expectancy_r", "Expectancy", "right"), column("total_r", "Total R", "right"),
            column("profit_factor", "PF", "right")]
    if with_delta:
        cols.append(column("delta", "vs baseline", "right"))
    table = ui.table(rows=rows, columns=cols, row_key="id", pagination=20).classes("w-full").props("flat dense")
    signed_slot(table, "expectancy_r", "R", 3)
    signed_slot(table, "total_r", "R", 1)
    if with_delta:
        signed_slot(table, "delta", "R", 3)
