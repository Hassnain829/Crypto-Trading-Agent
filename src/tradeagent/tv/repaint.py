"""Repaint audit: re-read stored snapshots and report indicator values that changed afterwards."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from typing import Any

from tradeagent.tv import js
from tradeagent.tv.cdp import CDPError
from tradeagent.tv.reader import SignalReader
from tradeagent.tv.schedule import TV_INTERVAL


def compare_values(stored: dict[str, dict[str, Any]], fresh: dict[str, dict[str, Any]]) -> list[str]:
    """Names (indicator.field) whose values differ. Floats are compared with a tiny tolerance."""
    diffs = []
    for key in sorted(set(stored) | set(fresh)):
        a_fields, b_fields = stored.get(key, {}), fresh.get(key, {})
        for name in sorted(set(a_fields) | set(b_fields)):
            a, b = a_fields.get(name), b_fields.get(name)
            if a is None and b is None:
                continue
            if a is None or b is None or not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12):
                diffs.append(f"{key}.{name}")
    return diffs


async def repaint_audit(reader: SignalReader, hours: float, limit: int) -> dict[str, Any]:
    """Compare up to `limit` recent good snapshots per symbol and timeframe with a fresh read."""
    since = reader.clock.now_ms() - int(hours * 3600 * 1000)
    groups: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    for symbol, timeframe, bar_time, values_json in reader.conn.execute(
        """
        SELECT symbol, timeframe, bar_time, values_json FROM snapshots
        WHERE problems_json IS NULL AND bar_time >= ? ORDER BY bar_time DESC
        """,
        (since,),
    ):
        if len(groups[(symbol, timeframe)]) < limit:
            groups[(symbol, timeframe)].append((bar_time, values_json))

    pages = await reader.watchdog.pages()
    fields: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    compared = unavailable = changed = 0
    for (symbol, timeframe), rows in sorted(groups.items(), key=lambda item: (item[0][1], item[0][0])):
        overview = timeframe in reader.settings.timeframes.overview
        layout = reader.settings.htf_layout if overview else reader.settings.layout_for(symbol)
        page = pages.get(layout)
        if page is None:
            unavailable += len(rows)
            continue
        switch = reader.settings.exchange.symbols[symbol].tradingview if overview else None
        prep = await reader.cdp.evaluate(
            page, js.prepare(switch, reader.settings.tradingview.min_bars, reader._timeout_ms), await_promise=True
        )
        index = {c["interval"]: c["index"] for c in prep["charts"]}.get(TV_INTERVAL[timeframe])
        if index is None:
            unavailable += len(rows)
            continue
        spec = reader.catalog.js_spec(reader.template_for(timeframe))
        for bar_time, values_json in rows:
            try:
                raw = await reader.cdp.evaluate(page, js.read_closed(spec, index, bar_time // 1000))
            except CDPError:
                unavailable += 1
                continue
            if raw.get("problems") or raw.get("error"):
                unavailable += 1
                continue
            compared += 1
            diffs = compare_values(json.loads(values_json), raw["values"])
            if diffs:
                changed += 1
                fields.update(diffs)
                if len(examples) < 5:
                    examples.append({"symbol": symbol, "timeframe": timeframe, "bar_time": bar_time, "fields": diffs})
    return {
        "compared": compared,
        "changed": changed,
        "unavailable": unavailable,
        "fields": dict(fields.most_common()),
        "examples": examples,
    }
