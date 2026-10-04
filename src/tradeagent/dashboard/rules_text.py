"""Strategy rules in plain English (from a variant's parameters)."""

from __future__ import annotations

from typing import Any

INDICATORS = {"qtrend": "Q-Trend", "zerolag": "Zero Lag", "atp_macd": "ATP MACD"}


def describe(p: dict[str, Any]) -> list[tuple[str, str]]:
    t, c, f, s, x = p["trigger"], p["confirmation"], p["filters"], p["stop"], p["exit"]
    entry = (p.get("entry") or {}).get("mode", "market")
    confirm = []
    if c.get("klinger"):
        confirm.append("Klinger histogram in the trade's direction")
    if c.get("candle_direction"):
        confirm.append("a candle closing in the trade's direction")
    window = "on the signal candle" if c["window"] == 0 else f"within {c['window']} candles of the signal"
    filters = []
    if f.get("min_stop_pct"):
        filters.append(f"skip setups whose swing stop is closer than {f['min_stop_pct']:g}%")
    if f.get("session_utc"):
        a, b = f["session_utc"]
        filters.append(f"only entries between {a:02d}:00 and {b:02d}:00 UTC")
    if f.get("vwap"):
        filters.append("longs above VWAP, shorts below")
    if f.get("macd_trend"):
        filters.append("ATP MACD line on the trade's side of zero")
    if f.get("zl_own"):
        filters.append("the chart's own Zero Lag trend must agree")
    htf = f.get("htf", "none")
    if htf == "against_4h":
        filters.append("only against the 4h Zero Lag trend")
    elif htf != "none":
        filters.append(f"the {htf} Zero Lag trend must agree")
    stop = f"lowest low (longs) / highest high (shorts) of the last {s['lookback']} candles"
    if s.get("anchor") == "1h":
        stop += ", and beyond the last closed 1h candles"
    if s.get("multiplier", 1) != 1:
        stop += f", moved to {s['multiplier']:g}x that distance"
    if x["mode"] == "fixed":
        exit_text = f"take profit at {x['take_profit_r']:g}R"
    elif x["mode"] == "hybrid":
        exit_text = f"close {x['partial_fraction']:.0%} at {x['partial_r']:g}R, then trail"
    else:
        exit_text = "hybrid when 1h and 4h agree, otherwise fixed"
    extras = []
    if x.get("breakeven_r"):
        extras.append(f"stop to break-even after +{x['breakeven_r']:g}R")
    if x.get("opposite_signal"):
        extras.append("close on an opposite signal")
    if x.get("max_candles"):
        extras.append(f"close after {x['max_candles']} candles")
    return [
        ("Charts", ", ".join(p["timeframes"])),
        ("Signal", f"{INDICATORS.get(t['indicator'], t['indicator'])} {t['long']} → long, {t['short']} → short"),
        ("Confirmation", f"{' and '.join(confirm) or 'none'}, {window}"),
        ("Filters", "; ".join(filters) or "none"),
        ("Entry", "limit order at the next 1m open; it fills only if the price trades through it within that minute"
         if entry == "limit" else "market order at the next 1m open"),
        ("Stop", stop),
        ("Exit", exit_text + ("; " + "; ".join(extras) if extras else "") + "; 72h time limit"),
    ]
