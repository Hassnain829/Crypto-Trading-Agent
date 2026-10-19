"""Messages to the user's phone through ntfy (the free ntfy app): problems, notices, demo trades, a dead-man ping.

The dashboard shows everything, but only when someone looks. These messages arrive when it matters:
- problems: failing TradingView reads, a drifting clock, an agent that stopped (sent by the dashboard),
  each sent once, repeated at most every `alerts.repeat_hours`, with a message when it is solved;
- notices: a new signal version, a TradingView restart or update, and (with `alerts.trades`) every demo trade;
- a ping to HEALTHCHECK_URL after every cycle (optional, for example healthchecks.io), which alerts the user
  from outside when the whole VPS is down and nothing here can send anything.

ntfy needs NTFY_TOPIC in .env: a long random name the phone app subscribes to (anyone who knows it can read the
messages, so it works like a password). NTFY_SERVER is optional (default https://ntfy.sh). Telegram is not used:
it is blocked from the Pakistani VPS (2026-10-19). Sending never blocks or breaks the agent: it runs in a
background thread with a timeout, and failures are only logged.
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.request
from typing import Any

from tradeagent.config import Settings

log = logging.getLogger("tradeagent.alerts")

TIMEOUT_S = 10
MAX_TEXT = 3500  # ntfy keeps messages up to 4096 bytes as text
DEFAULT_SERVER = "https://ntfy.sh"
TITLE = "Crypt-AI Agent"


def _secret(value: Any) -> str | None:
    return value.get_secret_value() if value is not None else None


def _secrets(settings: Settings) -> Any:
    """The keys as .env holds them now: keys added later work without restarting the agent or the dashboard."""
    from tradeagent.config import _load_secrets

    return _load_secrets(settings.root / ".env")


def topic(settings: Settings) -> str | None:
    return _secret(_secrets(settings).ntfy_topic)


def ready(settings: Settings) -> bool:
    return bool(topic(settings))


def send_now(settings: Settings, text: str, *, priority: str = "default", tags: str = "") -> str | None:
    """Send one ntfy message (blocking). Returns an error message, or None when it was sent."""
    if not settings.alerts.enabled:
        return "alerts are off (alerts.enabled)"
    secrets = _secrets(settings)
    name = _secret(secrets.ntfy_topic)
    if not name:
        return "NTFY_TOPIC is not set in .env"
    server = (_secret(secrets.ntfy_server) or DEFAULT_SERVER).rstrip("/")
    headers = {"Title": TITLE, "Priority": priority, "User-Agent": "crypt-ai-agent"}
    if tags:
        headers["Tags"] = tags
    request = urllib.request.Request(f"{server}/{name}", data=text[:MAX_TEXT].encode("utf-8"), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp:
            status = resp.status
    except Exception as exc:  # the URL holds the topic: log only the error type and reason
        return f"ntfy not reached: {type(exc).__name__}: {getattr(exc, 'code', '') or getattr(exc, 'reason', '')}"
    return None if status == 200 else f"ntfy answered HTTP {status}"


def send(settings: Settings, text: str, *, priority: str = "default", tags: str = "") -> None:
    """Send in the background: the caller never waits and never sees an error."""
    def run() -> None:
        problem = send_now(settings, text, priority=priority, tags=tags)
        if problem and settings.alerts.enabled and ready(settings):
            log.warning("alert not sent: %s", problem)
    threading.Thread(target=run, name="alert", daemon=True).start()


def ping_healthcheck(settings: Settings) -> None:
    """Tell the outside monitor the agent completed a cycle (background, optional)."""
    url = _secret(_secrets(settings).healthcheck_url)
    if not url:
        return

    def run() -> None:
        try:
            urllib.request.urlopen(url, timeout=TIMEOUT_S).close()
        except Exception as exc:
            log.debug("healthcheck ping failed: %s", type(exc).__name__)
    threading.Thread(target=run, name="healthcheck", daemon=True).start()


def _price(value: float | None) -> str:
    return f"{value:.6g}" if value is not None else "-"


def trade_messages(conn: Any, since_ms: int) -> tuple[list[str], int]:
    """Messages for the demo account's decisions written after `since_ms`: opened, skipped and closed positions.
    Returns the messages and the newest write time seen (the next `since_ms`)."""
    rows = conn.execute(
        "SELECT a.*, t.target FROM account_trades a LEFT JOIN trades t ON t.id = a.trade_id"
        " WHERE a.account = 'paper' AND a.updated_at > ? ORDER BY a.updated_at, a.id", (since_ms,)
    ).fetchall()
    messages, newest = [], since_ms
    for t in rows:
        newest = max(newest, t["updated_at"])
        name = f"{t['symbol']} {t['timeframe']} {t['side']}"
        if t["status"] == "rejected":
            messages.append(f"Demo skipped {name}: {t['reject_reason']}")
            continue
        if t["created_at"] > since_ms:
            distance = abs(t["entry_fill"] - t["stop"]) / t["entry_fill"] * 100
            share = t["risk_usd"] / t["balance_before"] * 100 if t["balance_before"] else 0.0
            notes = f" ({t['notes']})" if t["notes"] else ""
            messages.append(f"Demo opened {name}\nEntry {_price(t['entry_fill'])}, SL {_price(t['stop'])} ({distance:.2f}% away), "
                            f"TP {_price(t['target'])}\nRisk {t['risk_usd']:.2f} USDT = {share:.1f}% of the balance{notes}")
        if t["status"] == "closed":
            messages.append(f"Demo closed {name}: {t['exit_reason']}, {t['r_net']:+.2f}R, {t['pnl_usd']:+.2f} USDT. "
                            f"Balance {t['balance_after']:.2f} USDT")
    return messages, newest


def status_text(conn: Any, settings: Settings, prices: dict[str, float] | None = None, now_ms: int | None = None) -> str:
    """The demo account now: every open position with entry, SL, TP, the current price and its profit or loss,
    then balance, equity and open risk. `prices` (symbol -> live price) wins over the newest stored 1m close."""
    from tradeagent.account.engine import AccountEngine, position_pnl

    engine = AccountEngine(settings, conn)
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    balance = engine._load()["balance"]
    rows = conn.execute(
        "SELECT a.*, t.target FROM account_trades a LEFT JOIN trades t ON t.id = a.trade_id"
        " WHERE a.account = 'paper' AND a.status = 'open' ORDER BY a.entry_time, a.id"
    ).fetchall()
    lines = [f"Demo status {time.strftime('%H:%M', time.gmtime(now / 1000))} UTC: "
             + (f"{len(rows)} open position{'s' if len(rows) != 1 else ''}" if rows else "no open positions")]
    unrealized = 0.0
    for p in rows:
        price = (prices or {}).get(p["symbol"])
        if price is None:
            last = engine._last_price(p["symbol"])
            price = last[1] if last else None
        name = f"{p['symbol']} {p['timeframe']} {p['side']}"
        hours = (now - p["entry_time"]) / 3_600_000
        if price is None:
            lines.append(f"\n{name} ({hours:.0f}h open)\nEntry {_price(p['entry_fill'])}  SL {_price(p['stop'])}  TP {_price(p['target'])}")
            continue
        pnl = position_pnl(p, engine.broker.close_now(p["trade_id"], now, price))[0]
        unrealized += pnl
        lines.append(f"\n{name} ({hours:.0f}h open)\nEntry {_price(p['entry_fill'])}  SL {_price(p['stop'])}  TP {_price(p['target'])}\n"
                     f"Now {_price(price)}: {pnl:+.2f} USDT ({pnl / p['risk_usd']:+.2f}R)")
    risk = sum(p["risk_usd"] or 0.0 for p in rows)
    budget = settings.paper_account.max_open_risk
    lines.append(f"\nBalance {balance:.2f} USDT, equity {balance + unrealized:.2f} USDT"
                 + (f", open risk {risk / balance:.1%} of {budget:.0%}" if rows and budget and balance > 0 else ""))
    return "\n".join(lines)


class CommandListener:
    """Answers what the user writes to the ntfy topic from the phone app: 'status' (or 's', '?') gets the demo
    status, 'help' the list. The agent's own messages carry its title and are ignored. Polls every `every_s`
    seconds from a background thread; a failure just waits for the next poll."""

    STATUS = ("status", "s", "?")

    def __init__(self, settings: Settings, answer: Any, every_s: float = 20.0) -> None:
        self.settings = settings
        self.answer = answer  # () -> str: the status text (called in the listener's thread)
        self.every_s = every_s
        self.since = str(int(time.time()))  # messages written before the agent started are not answered

    def start(self) -> None:
        threading.Thread(target=self._run, name="ntfy-commands", daemon=True).start()

    def _run(self) -> None:
        while True:
            try:
                self.poll_once()
            except Exception as exc:
                log.debug("ntfy command poll failed: %s", type(exc).__name__)
            time.sleep(self.every_s)

    def _fetch(self, name: str, server: str) -> list[dict[str, Any]]:
        import json

        url = f"{server}/{name}/json?poll=1&since={self.since}"
        request = urllib.request.Request(url, headers={"User-Agent": "crypt-ai-agent"})
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp:
            lines = resp.read().decode("utf-8").splitlines()
        return [m for m in (json.loads(line) for line in lines if line.strip()) if m.get("event") == "message"]

    def poll_once(self) -> list[str]:
        """Answer new commands. Returns the commands it answered (for tests)."""
        if not self.settings.alerts.enabled:
            return []
        secrets = _secrets(self.settings)
        name = _secret(secrets.ntfy_topic)
        if not name:
            return []
        server = (_secret(secrets.ntfy_server) or DEFAULT_SERVER).rstrip("/")
        answered = []
        for message in self._fetch(name, server):
            self.since = message.get("id") or self.since
            if message.get("title") == TITLE:
                continue  # our own alerts and replies
            command = (message.get("message") or "").strip().lower()
            if command in self.STATUS:
                send(self.settings, self.answer(), tags="clipboard")
                answered.append(command)
            elif command == "help":
                send(self.settings, "Write 'status' (or s) to get the open demo positions: entry, SL, TP, the current "
                                    "price and the profit or loss, plus balance and equity.", tags="information_source")
                answered.append(command)
        return answered


class Alerter:
    """Problem alerts that are sent once, repeated at most every alerts.repeat_hours, and closed with a message
    when solved. One per process (the agent's and the dashboard's keep their own problems)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._open: dict[str, float] = {}  # problem key -> when it was last sent (monotonic seconds)

    def problem(self, key: str, text: str) -> bool:
        """Report a problem. Returns True when a message went out now."""
        last = self._open.get(key)
        if last is not None and time.monotonic() - last < self.settings.alerts.repeat_hours * 3600:
            return False
        self._open[key] = time.monotonic()
        send(self.settings, f"PROBLEM: {text}" if last is None else f"STILL A PROBLEM: {text}",
             priority="high", tags="warning")
        return True

    def solved(self, key: str, text: str) -> bool:
        if self._open.pop(key, None) is None:
            return False
        send(self.settings, f"SOLVED: {text}", tags="white_check_mark")
        return True

    def notice(self, text: str, tags: str = "information_source") -> None:
        send(self.settings, text, tags=tags)

    def forget(self, key: str) -> None:
        """Drop a problem without a message (for example: the user stopped the agent on purpose)."""
        self._open.pop(key, None)

    def is_open(self, key: str) -> bool:
        return key in self._open
