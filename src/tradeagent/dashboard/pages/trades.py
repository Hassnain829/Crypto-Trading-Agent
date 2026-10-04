"""Trades: the demo account and the shadow book, with filters and a detail view per trade."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from tradeagent.dashboard.data import DAY, Store, day_start, now_ms
from tradeagent.dashboard.rules_text import describe
from tradeagent.dashboard.widgets import (card, chart, chip_slot, column, empty, kv, money, palette, pct, rr,
                                          signed_slot, tz_label, when)

PERIODS = {"today": "Today", "7d": "Last 7 days", "30d": "Last 30 days", "all": "All"}


def period_start(period: str) -> int | None:
    return {"today": day_start(now_ms()), "7d": now_ms() - 7 * DAY, "30d": now_ms() - 30 * DAY}.get(period)


def build(store: Store) -> None:
    with ui.column().classes("gap-1"):
        ui.label("Trades").classes("page-title")
        ui.label("Every trade with the indicator values that triggered it. Click a row for the details.").classes("page-intro")

    choices = store.choices()
    with ui.tabs().classes("w-full").props("align=left dense") as tabs:
        tab_paper = ui.tab("Demo account", icon="account_balance_wallet")
        tab_shadow = ui.tab("Shadow book (all variants)", icon="science")
        ui.tab("Live", icon="bolt").props("disable").tooltip("Phase 6")
    with ui.tab_panels(tabs, value=tab_paper).classes("w-full bg-transparent"):
        with ui.tab_panel(tab_paper).classes("p-0 gap-3"):
            paper_view(store, choices)
        with ui.tab_panel(tab_shadow).classes("p-0 gap-3"):
            shadow_view(store, choices)


def _filters(choices: dict[str, list[str]], variant: bool) -> dict[str, Any]:
    f: dict[str, Any] = {}
    with ui.row().classes("w-full gap-3 items-center"):
        f["coin"] = ui.select({None: "All coins", **{c: c for c in choices["coins"]}}, value=None, label="Coin").classes("w-32")
        f["tf"] = ui.select({None: "All", **{t: t for t in choices["timeframes"]}}, value=None, label="Timeframe").classes("w-28")
        if variant:
            options = {v: v.rsplit("-", 1)[0] + (" (baseline)" if i == 0 else "") for i, v in enumerate(choices["variants"])}
            f["variant"] = ui.select(options, value=choices["variants"][0] if choices["variants"] else None,
                                     label="Variant").classes("w-56")
            f["taken"] = ui.select({None: "Taken and filtered", "taken": "Taken", "filtered": "Filtered (counterfactual)"},
                                   value="taken", label="Rule decision").classes("w-52")
        f["result"] = ui.select({None: "All results", "win": "Wins", "loss": "Losses", "open": "Open"}, value=None,
                                label="Result").classes("w-32")
        f["period"] = ui.select(PERIODS, value="all", label="Period").classes("w-36")
    return f


def _summary(label: ui.label, rows: list[dict[str, Any]], pnl: bool) -> None:
    closed = [r for r in rows if r["r"] is not None]
    wins = sum(1 for r in closed if r["r"] > 0)
    total_r = sum(r["r"] for r in closed)
    text = f"{len(rows)} trades · {len(closed)} closed · win {pct(wins / len(closed)) if closed else '–'} · total {total_r:+.2f}R"
    if pnl:
        text += f" · net {money(sum(r['pnl'] or 0 for r in closed), sign=True)}"
    label.set_text(text)


def paper_view(store: Store, choices: dict[str, list[str]]) -> None:
    f = _filters(choices, variant=False)
    rejected = ui.switch("Show skipped signals", value=False).props("dense")
    summary = ui.label().classes("text-2 text-sm")
    table = ui.table(rows=[], row_key="id", pagination=15, columns=[
        column("time_text", f"Entry ({tz_label()})"), column("coin", "Coin"), column("tf", "TF"), column("side", "Side"),
        column("status", "Status"), column("entry", "Entry", "right"), column("stop", "Stop", "right"),
        column("target", "Target", "right"), column("exit", "Exit / reason"), column("r", "R", "right"),
        column("pnl", "PnL $", "right"), column("fees", "Fees $", "right"),
    ]).classes("w-full").props("flat")
    signed_slot(table, "r", "R")
    signed_slot(table, "pnl")
    chip_slot(table, "status")
    table.on("rowClick", lambda e: open_detail(store, e.args[1]["trade_id"]))

    def load() -> None:
        rows = store.paper_trades(f["coin"].value, f["tf"].value, f["result"].value, period_start(f["period"].value),
                                  rejected.value)
        for r in rows:
            r.update(time_text=when(r["time"]), entry=_p(r["entry"]), stop=_p(r["stop"]), target=_p(r["target"]),
                     r=None if r["r"] is None else round(r["r"], 2), pnl=None if r["pnl"] is None else round(r["pnl"], 2),
                     fees=None if r["fees"] is None else round(r["fees"], 2))
        table.rows = rows
        table.update()
        _summary(summary, [r for r in rows if r["status"] != "rejected"], pnl=True)

    for el in (*f.values(), rejected):
        el.on_value_change(lambda _: load())
    load()
    ui.timer(15.0, load)


def shadow_view(store: Store, choices: dict[str, list[str]]) -> None:
    f = _filters(choices, variant=True)
    summary = ui.label().classes("text-2 text-sm")
    table = ui.table(rows=[], row_key="id", pagination=15, columns=[
        column("time_text", f"Entry ({tz_label()})"), column("variant", "Variant"), column("coin", "Coin"), column("tf", "TF"),
        column("side", "Side"), column("status", "Status"), column("entry", "Entry", "right"), column("stop", "Stop", "right"),
        column("target", "Target", "right"), column("exit", "Exit"), column("r", "R", "right"), column("taken", "Rules"),
    ]).classes("w-full").props("flat")
    signed_slot(table, "r", "R")
    chip_slot(table, "status")
    table.on("rowClick", lambda e: open_detail(store, e.args[1]["trade_id"]))

    def load() -> None:
        rows = store.shadow_trades(f["coin"].value, f["tf"].value, f["variant"].value, f["result"].value,
                                   period_start(f["period"].value), f["taken"].value)
        for r in rows:
            r.update(time_text=when(r["time"]), entry=_p(r["entry"]), stop=_p(r["stop"]), target=_p(r["target"]),
                     r=None if r["r"] is None else round(r["r"], 2))
        table.rows = rows
        table.update()
        _summary(summary, rows, pnl=False)

    for el in f.values():
        el.on_value_change(lambda _: load())
    load()
    ui.timer(30.0, load)


def _p(v: float | None) -> str:
    return "–" if v is None else f"{v:g}"


def open_detail(store: Store, trade_id: int) -> None:
    d = store.trade_detail(trade_id)
    if d is None:
        ui.notify("Trade not found", type="warning")
        return
    with ui.dialog() as dialog, ui.card().classes("card gap-4 w-[1100px] max-w-[96vw]"):
        detail(store, d, close=dialog.close)
    dialog.open()


def page(store: Store, trade_id: str) -> None:
    """The same detail as a page: /trade/<id> (a link that can be shared or bookmarked)."""
    d = store.trade_detail(int(trade_id)) if trade_id.isdigit() else None
    if d is None:
        empty(f"Trade {trade_id} not found.", "search_off")
        return
    with ui.column().classes("card gap-4 w-full"):
        detail(store, d, close=None)


def detail(store: Store, d: dict[str, Any], close) -> None:
    t, ctx, paper = d["trade"], d["context"], d["paper"]
    p = palette()
    with ui.row().classes("w-full items-center justify-between"):
        with ui.column().classes("gap-0"):
            name = f"baseline {store.baseline_version()}" if d["variant"] == store.baseline_id else d["variant"].rsplit("-", 1)[0]
            ui.label(f"{t['symbol']} {t['timeframe']} {t['side']} · {name}").classes("text-lg font-semibold")
            ui.label(f"Shadow trade #{t['id']} · signal version {t['signal_version']} · "
                     f"{'taken by the rules' if t['taken'] else 'filtered: ' + (t['reason'] or '')}").classes("muted text-sm")
        with ui.row().classes("items-center gap-3"):
            r = t["r_net"]
            ui.label(rr(r) if r is not None else t["status"]).classes(
                "text-2xl font-bold num " + ("profit" if r and r > 0 else "loss" if r and r < 0 else ""))
            if close:
                ui.button(icon="open_in_new", on_click=lambda: ui.navigate.to(f"/trade/{t['id']}", new_tab=True)).props(
                    "flat round").tooltip("Open as a page")
                ui.button(icon="close", on_click=close).props("flat round")

    with ui.row().classes("w-full gap-6"):
        for k, v in (("Signal candle", when(t["confirm_time"])), ("Entry", when(t["entry_time"])),
                     ("Entry price", _p(t["entry_ref"])), ("Stop", _p(t["stop_initial"])), ("Target", _p(t["target"])),
                     ("Exit", f"{t['exit_reason'] or '–'} · {when(t['exit_time'])}"),
                     ("Duration", _duration(t["entry_time"], t["exit_time"])),
                     ("MFE / MAE", f"{_r(t['mfe_r'])} / {_r(t['mae_r'])}"),
                     ("Fees / slippage", f"{_r(t['fees_r'])} / {_r(t['slippage_r'])}")):
            kv(k, v)
    if paper:
        with ui.row().classes("w-full gap-6"):
            for k, v in (("Demo size", f"{paper['qty']:g} ({money(paper['notional'])}, {paper['leverage'] or 0:.1f}x)"
                          if paper["qty"] else "skipped: " + (paper["reject_reason"] or "")),
                         ("Risk", money(paper["risk_usd"])), ("Balance before", money(paper["balance_before"])),
                         ("Demo PnL", money(paper["pnl_usd"], sign=True)), ("Demo fees", money(paper["fees_usd"]))):
                kv(k, v, "profit" if k == "Demo PnL" and (paper["pnl_usd"] or 0) > 0 else
                   "loss" if k == "Demo PnL" and (paper["pnl_usd"] or 0) < 0 else "")

    with card(f"Price ({d['candle_tf']} candles, {store.settings.venue})", "Entry, stop and target lines; the shaded band is the trade",
              classes="w-full"):
        if d["candles"]:
            cats = [c[0] for c in d["candles"]]
            marks = [{"yAxis": t["entry_ref"], "name": "Entry", "lineStyle": {"color": p["accent"]}},
                     {"yAxis": t["stop_initial"], "name": "Stop", "lineStyle": {"color": p["loss"]}}]
            if t["target"]:
                marks.append({"yAxis": t["target"], "name": "Target", "lineStyle": {"color": p["profit"]}})
            chart({
                "xAxis": {"type": "category", "data": [when(c) for c in cats],
                          "axisLabel": {"color": p["muted"]}},
                "yAxis": {"type": "value", "scale": True},
                "tooltip": {"trigger": "axis"},
                "series": [{
                    "type": "candlestick", "name": t["symbol"], "data": [[c[1], c[2], c[3], c[4]] for c in d["candles"]],
                    "itemStyle": {"color": p["profit"], "color0": p["loss"], "borderColor": p["profit"], "borderColor0": p["loss"]},
                    "markLine": {"symbol": "none", "label": {"color": p["text_2"], "formatter": "{b}: {c}",
                                                             "position": "insideEndTop"},
                                 "lineStyle": {"type": "solid", "width": 1}, "data": marks},
                    "markArea": {"itemStyle": {"color": p["accent"], "opacity": 0.06}, "data": [[
                        {"xAxis": _nearest(cats, t["entry_time"])},
                        {"xAxis": _nearest(cats, t["exit_time"] or cats[-1])}]]},
                }],
            }, "320px")
        else:
            empty("No candles stored for this period.")

    with ui.row().classes("w-full gap-4 items-start"):
        with card("Indicators at the signal", "Values of the confirming candle on TradingView", classes="flex-[3] min-w-[420px]"):
            names = {"qtrend": "Q-Trend", "klinger": "Klinger", "vwap": "VWAP", "zerolag": "Zero Lag", "atp_macd": "ATP MACD"}
            with ui.element("div").classes("kpi-grid"):
                for ind, fields in (ctx.get("values") or {}).items():
                    with ui.column().classes("step-box gap-1"):
                        ui.label(names.get(ind, ind)).classes("font-semibold text-sm")
                        for k, v in (fields or {}).items():
                            flag = isinstance(v, int) and v == 1  # a signal flag that fired on this candle
                            text = "–" if v is None else (f"{v:,.6g}" if isinstance(v, float) else str(v))
                            with ui.row().classes("w-full justify-between no-wrap gap-2"):
                                ui.label(k.replace("_", " ")).classes("text-xs text-2")
                                ui.label(text).classes("text-xs num" + (" profit font-bold" if flag and v == 1 else ""))
        with card("Context", classes="flex-[2] min-w-[300px]"):
            htf = ctx.get("htf") or {}
            kv("1h Zero Lag trend", htf.get("1h") or "–")
            kv("4h Zero Lag trend", htf.get("4h") or "–")
            kv("Filters failed", ", ".join(ctx.get("filters_failed") or []) or "none")
            candle = ctx.get("candle")
            kv("Signal candle O/H/L/C", " / ".join(f"{x:g}" for x in candle) if candle else "–")
            ui.separator()
            ui.label("Rules of this variant").classes("card-title")
            for k, v in describe(d["params"]) if d["params"] else []:
                with ui.column().classes("gap-0"):
                    ui.label(k).classes("kv-key")
                    ui.label(v).classes("text-sm")
    if d["legs"]:
        with card("Exit legs"):
            ui.table(rows=[{"id": i, "time": when(leg["time"]), "reason": leg["reason"], "price": f"{leg['ref']:g}",
                            "fill": f"{leg['fill']:.6g}", "part": f"{leg['fraction']:.0%}"} for i, leg in enumerate(d["legs"])],
                     row_key="id", columns=[column("time", f"Time ({tz_label()})"), column("reason", "Reason"),
                                            column("price", "Level", "right"), column("fill", "Fill", "right"),
                                            column("part", "Share", "right")]).classes("w-full").props("flat dense")


def _nearest(cats: list[int], ms: int) -> int:
    return min(range(len(cats)), key=lambda i: abs(cats[i] - ms)) if cats else 0


def _r(v: float | None) -> str:
    return "–" if v is None else f"{v:+.2f}R"


def _duration(a: int | None, b: int | None) -> str:
    if not a or not b:
        return "open"
    minutes = (b - a) / 60_000
    return f"{minutes:.0f} min" if minutes < 120 else f"{minutes / 60:.1f} h"
