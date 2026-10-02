"""`tradeagent doctor`: checks that everything the agent needs is installed and connected."""

from __future__ import annotations

import asyncio
import importlib.metadata
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum

from tradeagent.config import Settings, load_settings
from tradeagent.journal import LATEST_VERSION, connect, log_event, migrate, schema_version
from tradeagent.journal.db import now_ms
from tradeagent.logging_setup import setup_logging
from tradeagent.tv.cdp import CDPError, TradingViewCDP

log = logging.getLogger("tradeagent.doctor")

REQUIRED_PACKAGES = ("aiohttp", "ccxt", "numpy", "pandas", "psutil", "pydantic", "python-dotenv", "pyyaml")
LAUNCH_HINT = r"Start TradingView with: powershell -ExecutionPolicy Bypass -File scripts\launch_tradingview_debug.ps1"

SAVED_LAYOUTS_JS = """
new Promise(function (resolve) {
  try {
    window.TradingViewApi.getSavedCharts(function (charts) {
      resolve((charts || []).map(function (c) { return {name: c.name, id: c.url}; }));
    });
  } catch (e) { resolve({error: String(e)}); }
  setTimeout(function () { resolve({error: 'timeout'}); }, 8000);
})
"""


class Status(str, Enum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class CheckResult:
    name: str
    status: Status
    detail: str
    hint: str | None = None


def check_python() -> CheckResult:
    v = sys.version_info
    version = f"{v.major}.{v.minor}.{v.micro}"
    if v < (3, 12):
        return CheckResult("Python", Status.FAIL, version, "Python 3.12 or newer is required.")
    return CheckResult("Python", Status.OK, version)


def check_packages() -> CheckResult:
    found, missing = [], []
    for name in REQUIRED_PACKAGES:
        try:
            found.append(f"{name} {importlib.metadata.version(name)}")
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
    if missing:
        return CheckResult(
            "Packages", Status.FAIL, "missing: " + ", ".join(missing), r"Run: .venv\Scripts\python -m pip install -e .[dev]"
        )
    return CheckResult("Packages", Status.OK, ", ".join(found))


def check_config(settings: Settings) -> CheckResult:
    detail = (
        f"{len(settings.exchange.symbols)} symbols ({', '.join(settings.exchange.symbols)}); "
        f"trade {'/'.join(settings.timeframes.trade)}, overview {'/'.join(settings.timeframes.overview)}; "
        f"signal version {settings.tradingview.signal_version}"
    )
    return CheckResult("Config", Status.OK, detail)


def check_catalog(settings: Settings) -> CheckResult:
    from tradeagent.tv.catalog import load_catalog

    path = settings.resolve(settings.tradingview.catalog)
    try:
        catalog = load_catalog(path)
    except Exception as exc:  # missing file, YAML error or validation error
        return CheckResult("Catalog", Status.FAIL, f"{path}: {' '.join(str(exc).split())[:200]}")
    if catalog.signal_version != settings.tradingview.signal_version:
        return CheckResult(
            "Catalog",
            Status.WARN,
            f"catalog is for signal version {catalog.signal_version}, settings say {settings.tradingview.signal_version}",
        )
    fields = sum(len(ind.fields) for ind in catalog.indicators.values())
    return CheckResult("Catalog", Status.OK, f"{len(catalog.indicators)} indicators, {fields} fields")


def check_secrets(settings: Settings) -> CheckResult:
    if settings.secrets.has_binance_keys:
        return CheckResult("Secrets", Status.OK, "Binance API keys found")
    return CheckResult("Secrets", Status.OK, "no Binance API keys (not needed until Phase 6)")


def check_journal(settings: Settings) -> CheckResult:
    path = settings.resolve(settings.journal.path)
    try:
        conn = connect(path)
        try:
            applied = migrate(conn)
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            version = schema_version(conn)
            # Write test that leaves nothing behind.
            conn.execute("SAVEPOINT doctor_write_test")
            conn.execute(
                "INSERT INTO events (ts, level, source, message) VALUES (?, 'INFO', 'doctor', 'write test')", (now_ms(),)
            )
            conn.execute("ROLLBACK TO doctor_write_test")
            conn.execute("RELEASE doctor_write_test")
        finally:
            conn.close()
    except Exception as exc:  # sqlite3.Error, OSError, or RuntimeError from a failed migration
        return CheckResult("Journal", Status.FAIL, f"{path}: {exc}")
    note = f", applied migrations {applied}" if applied else ""
    status = Status.OK if version == LATEST_VERSION and mode == "wal" else Status.FAIL
    return CheckResult("Journal", status, f"{path} (schema v{version}, {mode} mode{note})")


def check_binance(settings: Settings) -> CheckResult:
    import ccxt

    from tradeagent.market.binance import public_client

    client = public_client()
    prices, problems = [], []
    try:
        markets = client.load_markets()  # also warms up the connection before the clock measurement
        # Compare against the middle of the request so network latency is not counted as drift.
        sent = now_ms()
        server_ms = client.fetch_time()
        drift_ms = abs(server_ms - (sent + now_ms()) // 2)
        for name, symbol in settings.exchange.symbols.items():
            market = markets.get(symbol.ccxt)
            if market is None:
                problems.append(f"{symbol.ccxt} not listed")
                continue
            if not market.get("active", True):
                problems.append(f"{symbol.ccxt} not active")
            prices.append(f"{name} {client.fetch_ticker(symbol.ccxt)['last']}")
    except ccxt.BaseError as exc:
        return CheckResult(
            "Binance API",
            Status.FAIL,
            f"{type(exc).__name__}: {str(exc)[:160]}",
            "Check the internet connection. A 451 or 403 error means Binance blocks this location.",
        )
    detail = f"{', '.join(prices)}; clock drift {drift_ms} ms"
    if problems:
        return CheckResult(
            "Binance API", Status.FAIL, f"{detail}; {'; '.join(problems)}", "Check the symbols in config/settings.yaml."
        )
    if drift_ms > 1000:
        return CheckResult("Binance API", Status.WARN, detail, "Sync the Windows clock (Settings > Time > Sync now).")
    return CheckResult("Binance API", Status.OK, detail)


def check_tradingview(settings: Settings) -> CheckResult:
    return asyncio.run(_check_tradingview(settings))


async def _check_tradingview(settings: Settings) -> CheckResult:
    tv = settings.tradingview
    client = TradingViewCDP(tv.cdp_host, tv.cdp_port)
    try:
        version = await client.version()
        pages = await client.chart_pages()
        if not pages:
            return CheckResult(
                "TradingView", Status.FAIL, "debug port is open but no chart tab is open", "Open an AGENT layout."
            )
        saved = await client.evaluate(pages[0], SAVED_LAYOUTS_JS, await_promise=True)
    except CDPError as exc:
        return CheckResult("TradingView", Status.FAIL, str(exc), LAUNCH_HINT)
    if not isinstance(saved, list):
        return CheckResult("TradingView", Status.FAIL, f"could not read the saved layouts: {saved}")

    saved_ids = {item["name"]: item["id"] for item in saved}
    missing = [name for name, layout_id in tv.layouts.items() if saved_ids.get(name) != layout_id]
    name_by_id = {layout_id: name for name, layout_id in tv.layouts.items()}
    open_tabs = ", ".join(name_by_id.get(p.layout_id, p.layout_id or "?") for p in pages)
    detail = (
        f"{version.get('Browser', '?')}; AGENT layouts {len(tv.layouts) - len(missing)}/{len(tv.layouts)}; "
        f"open tabs: {open_tabs}"
    )
    if missing:
        return CheckResult(
            "TradingView",
            Status.FAIL,
            f"{detail}; missing or changed: {', '.join(missing)}",
            "Compare docs/TRADINGVIEW-SETUP.md with the layout ids in config/settings.yaml.",
        )
    return CheckResult("TradingView", Status.OK, detail)


def check_claude_cli() -> CheckResult:
    path = shutil.which("claude")
    if not path:
        return CheckResult(
            "Claude Code CLI",
            Status.WARN,
            "not on PATH",
            "Only needed for scheduled research (Phase 5); the VS Code extension covers interactive research.",
        )
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult("Claude Code CLI", Status.WARN, f"found at {path} but it did not run ({exc})")
    text = (out.stdout or out.stderr).strip()
    return CheckResult("Claude Code CLI", Status.OK, text.splitlines()[0] if text else path)


def check_node() -> CheckResult:
    path = shutil.which("node")
    if not path:
        return CheckResult(
            "Node.js",
            Status.WARN,
            "not installed (optional)",
            "Only needed to run the TradingView MCP server inside Claude Code research sessions.",
        )
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult("Node.js", Status.WARN, f"found at {path} but it did not run ({exc})")
    return CheckResult("Node.js", Status.OK, out.stdout.strip() or path)


def run_checks(settings: Settings, *, offline: bool = False) -> list[CheckResult]:
    results = [
        check_python(),
        check_packages(),
        check_config(settings),
        check_catalog(settings),
        check_secrets(settings),
        check_journal(settings),
    ]
    if offline:
        results.append(CheckResult("Binance API", Status.WARN, "skipped (--offline)"))
    else:
        results.append(check_binance(settings))
    results += [check_tradingview(settings), check_claude_cli(), check_node()]
    return results


def exit_code(results: list[CheckResult]) -> int:
    return 1 if any(r.status is Status.FAIL for r in results) else 0


def render(results: list[CheckResult]) -> str:
    width = max(len(r.name) for r in results)
    lines = ["Crypt-AI-Trading doctor", "=" * 23]
    for r in results:
        lines.append(f"{'[' + r.status.value + ']':<7}{r.name:<{width}}  {r.detail}")
        if r.hint and r.status is not Status.OK:
            lines.append(f"{'':<{7 + width}}  -> {r.hint}")
    fails = sum(r.status is Status.FAIL for r in results)
    warns = sum(r.status is Status.WARN for r in results)
    lines.append("")
    if fails:
        lines.append(f"Result: {fails} check(s) failed, {warns} warning(s).")
    else:
        lines.append(f"Result: all required checks passed ({warns} warning(s)).")
    return "\n".join(lines)


def main(*, offline: bool = False) -> int:
    try:
        settings = load_settings()
    except Exception as exc:  # missing file, YAML syntax error, or validation error
        message = " ".join(str(exc).split())[:300] or type(exc).__name__
        print(render([CheckResult("Config", Status.FAIL, message, "Fix config/settings.yaml.")]))
        return 1

    setup_logging(settings, console=False)
    results = run_checks(settings, offline=offline)
    for r in results:
        log.log(logging.INFO if r.status is Status.OK else logging.WARNING, "%s %s: %s", r.status.value, r.name, r.detail)
    print(render(results))
    _record(settings, results)
    return exit_code(results)


def _record(settings: Settings, results: list[CheckResult]) -> None:
    if any(r.status is Status.FAIL for r in results):
        level = "ERROR"
    elif any(r.status is Status.WARN for r in results):
        level = "WARNING"
    else:
        level = "INFO"
    summary = [{"name": r.name, "status": r.status.value, "detail": r.detail} for r in results]
    try:
        conn = connect(settings.resolve(settings.journal.path))
        try:
            log_event(conn, level, "doctor", "doctor run", summary)
        finally:
            conn.close()
    except Exception:
        log.exception("could not record the doctor run in the journal")
