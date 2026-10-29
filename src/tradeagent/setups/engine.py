"""Setup engine: turns snapshots into setups and exploration trades, for every variant.

For each closed trading-timeframe candle (in time order, once):
1. A trigger flag starts a pending setup (and cancels pending setups on the other side).
2. A pending setup confirms on the first candle within its window that passes the confirmation rules,
   or expires when the window is over.
3. A confirmed setup becomes a trade: entry at the Binance 1m open right after the confirming candle
   closes (or, with entry.dip_5m_minutes, after the first 5m candle that closes against the trade), stop from
   the last N candles, filters checked. A trade that fails a filter is still simulated as a counterfactual
   (taken = 0) so the value of every filter can be measured.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections import Counter
from typing import Any

import numpy as np

from tradeagent.config import Settings
from tradeagent.journal.db import now_ms
from tradeagent.market.candles import SETTLE_MS, tf_ms
from tradeagent.market.fear_greed import value_at as fear_greed_at

MINUTE_MS = 60_000
from tradeagent.setups import chart_patterns
from tradeagent.setups.config import SetupParams, Variant
from tradeagent.sim.simulator import Costs, TradeState, open_trade

log = logging.getLogger("tradeagent.engine")

BOOK = "exploration"
M15_MS = 900_000
M5_MS = 300_000
DIP_SUFFIX = ":dip"  # the progress keys of the dip-entry pass ("engine:<coin>:<tf>:dip")
REFERENCE = "BTC"  # the market whose shocks filters.btc_shock_wait_minutes watches
BATCH = 5000  # snapshots read at a time (a live cycle has a few; a replay of years has hundreds of thousands)
QUALITY_BARS = 8  # a Trendline breakout in the last 8 closed 15m candles (2 hours) makes a trade quality A
OI_RISE = 0.01  # ...and so does open interest up more than 1% over the 4 hours before the decision
OI_WINDOW_MS = 4 * 3_600_000
SQZ_ON, SQZ_OFF = 5, 6  # Squeeze Momentum [LazyBear] state codes (the colorer's palette values)
SQZ_BARS = 6  # recorded, not used for sizing yet: a squeeze released in the last 6 candles (research 2026-10-20)
H4_MS = 4 * 3_600_000
CHART_DAYS = 40  # 4h candles of the last 40 days (from the 15m candles) feed the chart-pattern breakouts
CHART_BARS = 2  # a breakout in the last 2 closed 4h candles counts


def costs_from(settings: Settings) -> Costs:
    return Costs(settings.costs.maker_fee, settings.costs.taker_fee, settings.costs.slippage)


def zerolag_trend(values: dict[str, Any]) -> str | None:
    """Zero Lag draws only the lower band in a bullish trend and only the upper band in a bearish one."""
    zl = values.get("zerolag") or {}
    if zl.get("lower_band") is not None:
        return "bull"
    if zl.get("upper_band") is not None:
        return "bear"
    return None


class SetupEngine:
    def __init__(self, settings: Settings, variants: list[Variant], conn: sqlite3.Connection) -> None:
        self.settings = settings
        self.variants = variants
        self.conn = conn
        self.costs = costs_from(settings)
        # Variants that wait for a 5m dip before entering run in their own pass with their own progress
        # ("engine:<coin>:<tf>:dip"): a candle is handled there once each of their entries is known, and the other
        # variants do not wait with them.
        self.dip_variants = [v for v in variants if v.params.entry.dip_5m_minutes]
        self._dips: dict[tuple[str, str, int, int], tuple[int, bool]] = {}
        self._charts: dict[tuple[str, int], int | None] = {}

    def _get_state(self, key: str) -> int:
        row = self.conn.execute("SELECT value FROM engine_state WHERE key = ?", (key,)).fetchone()
        return int(row[0]) if row else 0

    def _set_state(self, key: str, value: int) -> None:
        self.conn.execute(
            "INSERT INTO engine_state (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )

    def process(self) -> Counter[str]:
        """Handle every new snapshot whose entry candle is available. Safe to call repeatedly."""
        counts: Counter[str] = Counter()
        plain = [v for v in self.variants if not v.params.entry.dip_5m_minutes]
        # The dip pass first: a new one starts where the other variants were before this run, so it sees this run's candles.
        for group, suffix in ((self.dip_variants, DIP_SUFFIX), (plain, "")):
            if group:
                self._process(group, suffix, counts)
        return counts

    def _process(self, variants: list[Variant], suffix: str, counts: Counter[str]) -> None:
        timeframes = sorted({tf for v in variants for tf in v.params.timeframes}, key=tf_ms)
        # A limit order may rest several minutes: a candle is handled once all of them are known.
        wait_ms = (max((v.params.entry.limit_minutes for v in variants if v.params.entry.mode == "limit"),
                       default=1) - 1) * MINUTE_MS
        for symbol in self.settings.exchange.symbols:
            newest_1m = self.conn.execute(
                "SELECT max(open_time) FROM candles WHERE symbol = ? AND timeframe = '1m'", (symbol,)
            ).fetchone()[0]
            if newest_1m is None:
                continue
            for tf in timeframes:
                step = tf_ms(tf)
                key = f"engine:{symbol}:{tf}{suffix}"
                if suffix and self._get_state(key) == 0 and self._get_state(f"engine:{symbol}:{tf}"):
                    # a new dip pass starts where the other variants are, like any new variant (no history replay)
                    with self.conn:
                        self._set_state(key, self._get_state(f"engine:{symbol}:{tf}"))
                waiting = False
                while not waiting:  # in batches, so a long replay (years of candles) does not load them all at once
                    rows = self.conn.execute(
                        """
                        SELECT s.id, s.bar_time, s.open, s.high, s.low, s.close, s.values_json, s.signal_version
                        FROM snapshots s
                        WHERE s.symbol = ? AND s.timeframe = ? AND s.bar_time > ? AND s.problems_json IS NULL
                          AND s.signal_version = (SELECT max(x.signal_version) FROM snapshots x
                                                  WHERE x.symbol = s.symbol AND x.timeframe = s.timeframe
                                                    AND x.bar_time = s.bar_time AND x.problems_json IS NULL)
                        ORDER BY s.bar_time LIMIT ?
                        """,
                        (symbol, tf, self._get_state(key), BATCH),
                    ).fetchall()
                    for row in rows:
                        entry_time = row["bar_time"] + step
                        if entry_time + wait_ms > newest_1m:
                            waiting = True  # wait until the entry candle (and a resting limit order's minutes) closed and synced
                            break
                        entry = self.conn.execute(
                            "SELECT open, high, low FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time = ?",
                            (symbol, entry_time),
                        ).fetchone()
                        if entry is None and entry_time > newest_1m - SETTLE_MS:
                            waiting = True  # a quiet minute gets its flat candle once settled (sparse venues): wait for it
                            break
                        if suffix and entry is not None and self._waiting_for_dip(symbol, tf, row, newest_1m, wait_ms):
                            waiting = True  # a dip entry of this candle is not known yet (at most dip_5m_minutes)
                            break
                        with self.conn:  # one transaction per candle: restart-safe
                            if entry is None:
                                counts["no_entry_candle"] += 1
                            else:
                                for v in variants:
                                    if tf in v.params.timeframes:
                                        self._on_candle(v, symbol, tf, row, entry, counts)
                            self._set_state(key, row["bar_time"])
                        counts["candles"] += 1
                    if len(rows) < BATCH:
                        break

    def _on_candle(self, v: Variant, symbol: str, tf: str, row: sqlite3.Row, entry: sqlite3.Row, counts: Counter[str]) -> None:
        p = v.params
        values = json.loads(row["values_json"])
        trigger_values = values.get(p.trigger.indicator) or {}
        for side, field in (("long", p.trigger.long), ("short", p.trigger.short)):
            if trigger_values.get(field) == 1:
                opposite = "short" if side == "long" else "long"
                self.conn.execute(
                    "UPDATE setups SET status = 'cancelled'"
                    " WHERE variant_id = ? AND symbol = ? AND timeframe = ? AND side = ? AND status = 'pending'",
                    (v.id, symbol, tf, opposite),
                )
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO setups (variant_id, symbol, timeframe, side, trigger_time, status, signal_version)"
                    " VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                    (v.id, symbol, tf, side, row["bar_time"], row["signal_version"]),
                )
                counts["triggers"] += cur.rowcount
                if p.exit.opposite_signal:
                    self._schedule_exits(v, symbol, tf, opposite, row["bar_time"] + tf_ms(tf), counts)

        step = tf_ms(tf)
        pending = self.conn.execute(
            "SELECT id, side, trigger_time FROM setups"
            " WHERE variant_id = ? AND symbol = ? AND timeframe = ? AND status = 'pending' ORDER BY trigger_time",
            (v.id, symbol, tf),
        ).fetchall()
        for setup in pending:
            if row["bar_time"] > setup["trigger_time"] + p.confirmation.window * step:
                self.conn.execute("UPDATE setups SET status = 'expired' WHERE id = ?", (setup["id"],))
                counts["expired"] += 1
            elif self._confirmed(p, setup["side"], values, row):
                self._open_trade(v, setup, symbol, tf, row, values, entry, counts)
                self.conn.execute(
                    "UPDATE setups SET status = 'confirmed', confirm_time = ? WHERE id = ?", (row["bar_time"], setup["id"])
                )

    @staticmethod
    def _confirmed(p: SetupParams, side: str, values: dict[str, Any], row: sqlite3.Row) -> bool:
        if p.confirmation.klinger:
            hist = (values.get("klinger") or {}).get("hist")
            if hist is None or (side == "long" and hist < 0) or (side == "short" and hist >= 0):
                return False
        if p.confirmation.candle_direction:
            if side == "long" and not row["close"] > row["open"]:
                return False
            if side == "short" and not row["close"] < row["open"]:
                return False
        return True

    def _btc_move(self, at: int, minutes: int) -> float | None:
        """BTC's biggest move within one 5m candle among those that closed in the `minutes` before `at`."""
        row = self.conn.execute(
            "SELECT max(abs(close / open - 1)), count(*) FROM candles WHERE symbol = ? AND timeframe = '5m'"
            " AND open_time >= ? AND open_time + ? <= ? AND open > 0",
            (REFERENCE, at - minutes * MINUTE_MS - M5_MS, M5_MS, at)).fetchone()
        return row[0] if row and row[1] else None

    def _dip_entry(self, symbol: str, side: str, order_time: int, minutes: int) -> tuple[int, bool] | None:
        """(entry time, dip found) of a dip entry decided at `order_time`: the open of the 5m candle after the first
        one that closes against the trade, or the end of the wait. None while the 5m candles it needs are not synced."""
        key = (symbol, side, order_time, minutes)
        if key in self._dips:
            return self._dips[key]
        end = order_time + minutes * MINUTE_MS
        sign = 1 if side == "long" else -1
        newest = self.conn.execute(
            "SELECT max(open_time) FROM candles WHERE symbol = ? AND timeframe = '5m'", (symbol,)).fetchone()[0]
        bars = {r["open_time"]: r for r in self.conn.execute(
            "SELECT open_time, open, close FROM candles WHERE symbol = ? AND timeframe = '5m' AND open_time >= ?"
            " AND open_time < ?", (symbol, order_time, end))}
        result = (end, False)
        t = order_time
        while t + M5_MS <= end:
            bar = bars.get(t)
            if bar is None:
                if newest is None or t > newest:
                    return None  # not synced yet
            elif sign * (bar["close"] - bar["open"]) < 0:
                result = (t + M5_MS, True)
                break
            t += M5_MS
        self._dips[key] = result
        return result

    def _waiting_for_dip(self, symbol: str, tf: str, row: sqlite3.Row, newest_1m: int, wait_ms: int) -> bool:
        """True while a dip-entry variant would open a trade on this candle whose entry is not known yet."""
        if not self.dip_variants:
            return False
        values = json.loads(row["values_json"])
        order_time = row["bar_time"] + tf_ms(tf)
        for v in self.dip_variants:
            p = v.params
            if tf not in p.timeframes:
                continue
            trigger = values.get(p.trigger.indicator) or {}
            sides = {side for side, field in (("long", p.trigger.long), ("short", p.trigger.short)) if trigger.get(field) == 1}
            sides |= {r["side"] for r in self.conn.execute(
                "SELECT side FROM setups WHERE variant_id = ? AND symbol = ? AND timeframe = ? AND status = 'pending'"
                " AND trigger_time >= ?", (v.id, symbol, tf, row["bar_time"] - p.confirmation.window * tf_ms(tf)))}
            for side in sides:
                if not self._confirmed(p, side, values, row):
                    continue
                dip = self._dip_entry(symbol, side, order_time, p.entry.dip_5m_minutes)
                if dip is None or dip[0] + wait_ms > newest_1m:
                    return True
                candle = self.conn.execute(
                    "SELECT 1 FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time = ?", (symbol, dip[0])).fetchone()
                if candle is None and dip[0] > newest_1m - SETTLE_MS:
                    return True
        return False

    def _schedule_exits(self, v: Variant, symbol: str, tf: str, side: str, at: int, counts: Counter[str]) -> None:
        """An opposite trigger closes this variant's open `side` trades on this chart at market, at `at`."""
        for trade in self.conn.execute(
            "SELECT id, state_json FROM trades WHERE book = ? AND variant_id = ? AND symbol = ? AND timeframe = ?"
            " AND side = ? AND status = 'open' AND entry_time < ?",
            (BOOK, v.id, symbol, tf, side, at),
        ).fetchall():
            state = TradeState.from_json(json.loads(trade["state_json"]))
            if state.exit_at is None or state.exit_at > at:
                state.exit_at = at
                self.conn.execute("UPDATE trades SET state_json = ?, updated_at = ? WHERE id = ?",
                                  (json.dumps(state.to_json()), now_ms(), trade["id"]))
                counts["exits_scheduled"] += 1

    def _htf_trend(self, symbol: str, timeframe: str, at: int) -> str | None:
        """Zero Lag trend of the newest closed higher-timeframe candle at `at` (None if missing or stale)."""
        step = tf_ms(timeframe)
        row = self.conn.execute(
            "SELECT bar_time, values_json FROM snapshots WHERE symbol = ? AND timeframe = ? AND problems_json IS NULL"
            " AND bar_time + ? <= ? ORDER BY bar_time DESC LIMIT 1",
            (symbol, timeframe, step, at),
        ).fetchone()
        if row is None or at - (row["bar_time"] + step) > step:
            return None
        return zerolag_trend(json.loads(row["values_json"]))

    def _oi_change(self, symbol: str, at: int) -> float | None:
        """Open interest change over the OI_WINDOW_MS before `at`, from the newest 15m snapshot at or before it (one
        missing snapshot is tolerated). None without the data (another venue, or not synced yet)."""
        row = self.conn.execute(
            "SELECT time, amount FROM open_interest WHERE symbol = ? AND time <= ? AND time > ? ORDER BY time DESC LIMIT 1",
            (symbol, at, at - 2 * M15_MS),
        ).fetchone()
        if row is None:
            return None
        before = self.conn.execute("SELECT amount FROM open_interest WHERE symbol = ? AND time = ?",
                                   (symbol, row["time"] - OI_WINDOW_MS)).fetchone()
        return row["amount"] / before[0] - 1 if before and before[0] else None

    def _squeeze(self, symbol: str, tf: str, side: str, bar_time: int) -> tuple[bool | None, float | None]:
        """(squeeze fired, momentum) on the trade's own chart at the confirming candle: True when a squeeze released
        (state on -> off) within its last SQZ_BARS candles and the momentum points the trade's way. Research
        2026-10-20: those taken trades made +0.40R against +0.21R (not confirmed on the skipped signals), so it is
        recorded for the forward check only. None when the candles lack the squeeze values."""
        step = tf_ms(tf)
        rows = self.conn.execute(
            "SELECT bar_time, values_json FROM snapshots WHERE symbol = ? AND timeframe = ? AND problems_json IS NULL"
            " AND bar_time >= ? AND bar_time <= ? ORDER BY bar_time, signal_version",
            (symbol, tf, bar_time - SQZ_BARS * step, bar_time),
        ).fetchall()
        by_time = {r["bar_time"]: (json.loads(r["values_json"]).get("squeeze") or {}) for r in rows}
        bars = [by_time.get(bar_time - k * step) for k in range(SQZ_BARS, -1, -1)]
        if any(b is None or b.get("state") is None for b in bars) or bars[-1].get("momentum") is None:
            return None, None
        momentum = bars[-1]["momentum"]
        released = any(bars[k - 1]["state"] == SQZ_ON and bars[k]["state"] == SQZ_OFF for k in range(1, len(bars)))
        sign = 1 if side == "long" else -1
        return released and sign * momentum > 0, momentum

    def _btc_change(self, at: int, hours: int) -> float | None:
        """BTC's change from the close `hours` before `at` to the last close at `at` (5m candles that closed by then;
        each must be at most 15 minutes old). None without its candles."""
        def close(t: int) -> float | None:
            row = self.conn.execute(
                "SELECT close FROM candles WHERE symbol = ? AND timeframe = '5m' AND open_time + ? <= ? AND open_time + ? > ?"
                " ORDER BY open_time DESC LIMIT 1", (REFERENCE, M5_MS, t, M5_MS + M15_MS, t)).fetchone()
            return row[0] if row and row[0] else None
        now, before = close(at), close(at - hours * 3_600_000)
        return now / before - 1 if now and before else None

    def _chart_4h(self, symbol: str, at: int) -> int | None:
        """Direction (+1 / -1) of a 4h chart-pattern breakout in the last CHART_BARS closed 4h candles at `at` (the
        newest one wins), 0 for none, None without enough candles. Built from the 15m candles, once per 4h candle."""
        last = at // H4_MS * H4_MS  # the newest closed 4h candle ends here
        key = (symbol, last)
        if key not in self._charts:
            rows = self.conn.execute(
                "SELECT open_time, open, high, low, close FROM candles WHERE symbol = ? AND timeframe = '15m'"
                " AND open_time >= ? AND open_time < ? ORDER BY open_time",
                (symbol, last - CHART_DAYS * 86_400_000, last)).fetchall()
            bars: dict[int, list[float]] = {}
            for t, o, h, lo, c in rows:  # 4h candles from UTC midnight, as in the research
                b = bars.get(t // H4_MS)
                if b is None:
                    bars[t // H4_MS] = [o, h, lo, c]
                else:
                    b[1], b[2], b[3] = max(b[1], h), min(b[2], lo), c
            if len(bars) < 80 or max(bars) != last // H4_MS - 1:
                self._charts[key] = None
            else:
                arr = np.array([bars[k] for k in sorted(bars)], dtype=float)
                bull, bear = chart_patterns.breakout_masks(arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], include_last=True)
                self._charts[key] = 0
                for j in range(1, CHART_BARS + 1):
                    if bull[-j] != bear[-j]:
                        self._charts[key] = 1 if bull[-j] else -1
                        break
        return self._charts[key]

    def _quality(self, symbol: str, side: str, at: int) -> tuple[str, str | None, float | None, int | None, float | None]:
        """Quality tier of a trade decided at `at`, its reasons, the 4-hour open interest change, the 4h chart
        breakout direction and BTC's change over settings.quality.btc_move_hours. "A" when one of the reasons that
        settings.quality turns on holds:
        - trendline: the 15m chart showed a same-direction Trendline breakout in the last QUALITY_BARS closed candles
          (research 2026-10-18: those trades won 66% at +0.59R against +0.23R)
        - open_interest: open interest rose more than OI_RISE in the 4 hours before (research 2026-10-19: +0.63R
          against +0.22R, and +0.04R against -0.22R on the skipped signals)
        - chart_4h: a 4h chart-pattern breakout in the trade's direction in the last CHART_BARS closed 4h candles
        - btc_move: BTC moved at least that share the trade's way over btc_move_hours (research 2026-10-24)
        else "B". The 4h breakout and BTC's change are recorded on every trade either way."""
        q = self.settings.quality
        field = "long" if side == "long" else "short"
        sign = 1 if side == "long" else -1
        reasons = []
        if q.trendline:
            for row in self.conn.execute(
                "SELECT bar_time, values_json FROM snapshots WHERE symbol = ? AND timeframe = '15m' AND problems_json IS NULL"
                " AND bar_time >= ? AND bar_time + ? <= ? ORDER BY bar_time DESC, signal_version DESC",
                (symbol, at - QUALITY_BARS * M15_MS, M15_MS, at),
            ):
                if ((json.loads(row["values_json"]).get("trendline") or {}).get(field)) == 1:
                    reasons.append(f"15m trendline {field} breakout at {time.strftime('%H:%M', time.gmtime(row['bar_time'] / 1000))} UTC")
                    break
        oi = self._oi_change(symbol, at)
        if q.open_interest and oi is not None and oi > OI_RISE:
            reasons.append(f"open interest {oi:+.1%} in the last 4 h")
        chart = self._chart_4h(symbol, at)
        if q.chart_4h and chart == sign:
            reasons.append("4h chart-pattern breakout the trade's way")
        btc = self._btc_change(at, q.btc_move_hours)
        if q.btc_move and btc is not None and sign * btc >= q.btc_move:
            reasons.append(f"BTC {btc:+.1%} in the last {q.btc_move_hours} h")
        return ("A" if reasons else "B"), "; ".join(reasons) or None, oi, chart, btc

    def _open_trade(
        self, v: Variant, setup: sqlite3.Row, symbol: str, tf: str, row: sqlite3.Row,
        values: dict[str, Any], entry: sqlite3.Row, counts: Counter[str],
    ) -> None:
        p = v.params
        side = setup["side"]
        sign = 1 if side == "long" else -1
        order_price = entry_ref = entry["open"]
        limit = p.entry.mode == "limit"
        trend = "bull" if side == "long" else "bear"
        entry_time = order_time = row["bar_time"] + tf_ms(tf)  # decisions use order_time; entry_time = the fill

        problems: list[str] = []
        stop: float | None = None
        recent = self.conn.execute(
            "SELECT high, low FROM candles WHERE symbol = ? AND timeframe = ? AND open_time <= ?"
            " ORDER BY open_time DESC LIMIT ?",
            (symbol, tf, row["bar_time"], p.stop.lookback),
        ).fetchall()
        if len(recent) < p.stop.lookback:
            problems.append("not enough candles for the stop")
        else:
            stop = min(c["low"] for c in recent) if sign > 0 else max(c["high"] for c in recent)
            if sign * (entry_ref - stop) <= 0:
                problems.append("stop on the wrong side of the entry")
        # The chart's swing sets the target (reference risk); anchor and multiplier only move the stop.
        reference = abs(entry_ref - stop) if stop is not None and not problems else None
        if reference is not None and p.stop.min_pct and reference / order_price * 100 < p.stop.min_pct:
            reference = order_price * p.stop.min_pct / 100  # stop floor: a tight swing gets a wider stop
            stop = order_price - sign * reference
        if reference is not None and p.stop.anchor == "1h":
            hourly = self.conn.execute(
                "SELECT high, low FROM candles WHERE symbol = ? AND timeframe = '1h' AND open_time + 3600000 <= ?"
                " ORDER BY open_time DESC LIMIT ?",
                (symbol, order_time, p.stop.lookback),
            ).fetchall()
            if len(hourly) < p.stop.lookback:
                problems.append("not enough 1h candles for the stop")
            else:  # beyond the 1h swing, and never closer than the chart's own swing
                level = min(c["low"] for c in hourly) if sign > 0 else max(c["high"] for c in hourly)
                stop = min(stop, level) if sign > 0 else max(stop, level)
        if reference is not None and p.stop.multiplier != 1.0:
            stop = entry_ref - sign * p.stop.multiplier * abs(entry_ref - stop)

        # Dip entry: wait for the first 5m candle against the trade (process() made sure the entry is known). The stop
        # and the targets stay the planned ones; a setup that reaches its stop or target while waiting is not entered.
        dip: tuple[int, bool] | None = None
        dip_missed: str | None = None
        planned: tuple[float, float] | None = None
        if p.entry.dip_5m_minutes and reference is not None and stop is not None and not problems:
            planned = (order_price + sign * p.exit.take_profit_r * reference, order_price + sign * p.exit.partial_r * reference)
            dip = self._dip_entry(symbol, side, order_time, p.entry.dip_5m_minutes)
            assert dip is not None, "process() handles a candle only once its dip entries are known"
            entry_time = dip[0]
            lo, hi = self.conn.execute(
                "SELECT min(low), max(high) FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time >= ?"
                " AND open_time < ?", (symbol, order_time, entry_time)).fetchone()
            at_entry = self.conn.execute(
                "SELECT open, high, low FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time = ?",
                (symbol, entry_time)).fetchone()
            if lo is not None and (lo <= stop if sign > 0 else hi >= stop):
                dip_missed = "stop reached before the dip entry"
            elif lo is not None and (hi >= planned[0] if sign > 0 else lo <= planned[0]):
                dip_missed = "target reached before the dip entry"
            elif at_entry is None:
                dip_missed = "no 1m candle at the dip entry"
            else:
                entry, entry_ref = at_entry, at_entry["open"]
                partial_passed = p.exit.mode != "fixed" and sign * (planned[1] - entry_ref) <= 0
                if sign * (entry_ref - stop) <= 0 or sign * (planned[0] - entry_ref) <= 0 or partial_passed:
                    dip_missed = "the price left the planned range before the dip entry"

        # The limit price: the open, or offset_r of the way toward the stop. It fills in the first minute (within
        # limit_minutes) that trades strictly through it; the trade starts in that minute.
        if limit and p.entry.offset_r and reference is not None:
            entry_ref = order_price - sign * p.entry.offset_r * reference
        filled = not limit or (entry["low"] < entry_ref if sign > 0 else entry["high"] > entry_ref)
        if limit and not filled and p.entry.limit_minutes > 1:
            start = entry_time  # the minute the order is placed: right after the signal, or at the dip entry
            for c in self.conn.execute(
                "SELECT open_time, high, low FROM candles WHERE symbol = ? AND timeframe = '1m' AND open_time > ?"
                " AND open_time < ? ORDER BY open_time",
                (symbol, start, start + p.entry.limit_minutes * MINUTE_MS),
            ):
                if c["low"] < entry_ref if sign > 0 else c["high"] > entry_ref:
                    filled, entry_time = True, c["open_time"]
                    break

        htf = {name: self._htf_trend(symbol, name, order_time) for name in ("1h", "4h")}
        failed: list[str] = []
        if p.filters.vwap:
            vwap = (values.get("vwap") or {}).get("vwap")
            if vwap is None or sign * (row["close"] - vwap) < 0:
                failed.append("vwap")
        if p.filters.macd_trend:
            macd = (values.get("atp_macd") or {}).get("macd")
            if macd is None or sign * macd <= 0:
                failed.append("macd_trend")
        if p.filters.htf == "against_4h":
            if htf["4h"] is None or htf["4h"] == trend:
                failed.append("htf_against_4h")
        elif p.filters.htf != "none":
            needed = ["1h"] if p.filters.htf == "1h" else ["1h", "4h"]
            if any(htf[name] != trend for name in needed):
                failed.append(f"htf_{p.filters.htf}")
        if p.filters.min_stop_pct > 0 and reference is not None and reference / order_price * 100 < p.filters.min_stop_pct:
            failed.append("min_stop_pct")
        if p.filters.zl_own and zerolag_trend(values) != trend:
            failed.append("zl_own")
        if p.filters.trend_15m and tf == "5m" and self._htf_trend(symbol, "15m", order_time) != trend:
            failed.append("trend_15m")
        if p.filters.session_utc is not None:
            start, end = p.filters.session_utc
            if not start <= time.gmtime(order_time / 1000).tm_hour < end:
                failed.append("session")
        btc_move = self._btc_move(order_time, max(p.filters.btc_shock_wait_minutes, 60))
        if p.filters.btc_shock_wait_minutes:
            recent = self._btc_move(order_time, p.filters.btc_shock_wait_minutes)
            if recent is not None and recent >= p.filters.btc_shock_pct / 100:
                failed.append("btc_shock")
        fear_greed = fear_greed_at(self.conn, order_time)
        if p.filters.fear_greed_extremes is not None and fear_greed is not None:
            low, high = p.filters.fear_greed_extremes
            if not low <= fear_greed <= high:
                failed.append("fear_greed")
        if p.filters.btc_against_pct:
            against = self._btc_change(order_time, p.filters.btc_against_hours)
            if against is not None and -sign * against >= p.filters.btc_against_pct / 100:
                failed.append("btc_against")

        mode = p.exit.mode
        if mode == "htf_rule":
            mode = "hybrid" if htf["1h"] == trend and htf["4h"] == trend else "fixed"
        quality, quality_reason, oi_change, chart_4h, btc_change = self._quality(symbol, side, order_time)
        sqz_fire, sqz_momentum = self._squeeze(symbol, tf, side, row["bar_time"])
        context = {
            "values": values,
            "candle": [row["open"], row["high"], row["low"], row["close"]],
            "htf": htf,
            "filters_failed": failed,
            "snapshot_id": row["id"],
            "params_hash": v.params_hash,
            "quality": quality,  # A = a 15m Trendline breakout or rising open interest; the account may risk more on it
            "quality_reason": quality_reason,
            "oi_change_4h": oi_change,  # recorded on every trade, for the forward check of the OI flag
            "sqz_fire": sqz_fire,  # recorded for the forward check (2026-10-20); not used for sizing yet
            "sqz_momentum": sqz_momentum,
            "btc_move_5m": btc_move,  # BTC's biggest 5m move in the hour before the decision (None without its candles)
            "fear_greed": fear_greed,  # the Fear & Greed Index known at the decision
            "chart_4h": chart_4h,  # +1/-1: a 4h chart-pattern breakout up/down in the last 2 closed 4h candles; 0 none
            "btc_change": btc_change,  # BTC's change over settings.quality.btc_move_hours before the decision
        }
        if dip is not None:
            context["dip_entry"] = {"minutes": (dip[0] - order_time) // MINUTE_MS, "dip_found": dip[1], "missed": dip_missed}
        if problems:
            status, taken, reason, state, target = "invalid", 0, "; ".join(problems), {}, None
            stop_value = stop if stop is not None else entry_ref
        elif dip_missed or not filled:
            status, taken, state, target = "missed", int(not failed), {}, None
            reason = ", ".join([*failed, dip_missed or "limit not filled"])
            stop_value = stop
        else:
            assert stop is not None and reference is not None
            scale = reference / abs(entry_ref - stop)  # 1 unless the stop moved or the limit was offset
            take_profit_r, partial_r = (p.exit.take_profit_r + p.entry.offset_r) * scale, p.exit.partial_r * scale
            if planned is not None:  # dip entry: the planned target and partial prices, measured from the fill
                take_profit_r, partial_r = (sign * (level - entry_ref) / abs(entry_ref - stop) for level in planned)
            sim = open_trade(  # the target stays the planned price: order price + take_profit_r x the swing risk
                side=side, mode=mode, entry_time=entry_time, entry_ref=entry_ref, stop=stop,
                take_profit_r=take_profit_r, partial_r=partial_r,
                partial_fraction=p.exit.partial_fraction, trail_lookback=p.exit.trail_lookback, costs=self.costs,
                breakeven_r=p.exit.breakeven_r,
                time_stop_at=entry_time + p.exit.max_candles * tf_ms(tf) if p.exit.max_candles else None,
                limit_entry=limit,
            )
            status, taken, reason, state, target = "open", int(not failed), ", ".join(failed) or None, sim.to_json(), sim.target
            stop_value = stop
        now = now_ms()
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO trades (book, variant_id, symbol, timeframe, side, setup_id, signal_version,
                trigger_time, confirm_time, entry_time, taken, reason, exit_mode, entry_ref, stop_initial, target,
                status, context_json, state_json, venue, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                BOOK, v.id, symbol, tf, side, setup["id"], row["signal_version"], setup["trigger_time"],
                row["bar_time"], entry_time, taken, reason, mode, entry_ref, stop_value, target, status,
                json.dumps(context, sort_keys=True), json.dumps(state), self.settings.venue, now, now,
            ),
        )
        if cur.rowcount:
            kind = status if status in ("invalid", "missed") else ("taken" if taken else "counterfactual")
            counts[f"trades_{kind}"] += 1
