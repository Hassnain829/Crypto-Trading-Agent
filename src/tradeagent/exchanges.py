"""Exchange API keys: what each exchange needs, saving them to the local .env, and a read-only connection test.

Keys never leave this machine. They are written to .env (which git ignores), shown masked afterwards,
and never logged. The test only reads the futures balance; it cannot place orders or withdraw.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, set_key, unset_key


@dataclass(frozen=True)
class CredentialField:
    name: str  # ccxt credential name: apiKey | secret | password
    label: str
    env: str  # variable in .env
    pattern: str  # what a pasted value should look like (a soft check)
    hint: str


@dataclass(frozen=True)
class ExchangeSpec:
    key: str
    name: str
    ccxt_id: str
    market: str
    fields: tuple[CredentialField, ...]
    options: dict[str, Any] = field(default_factory=dict)
    steps: tuple[str, ...] = ()
    url: str = ""


_KEY = r"^[A-Za-z0-9_\-]{16,128}$"
EXCHANGES: dict[str, ExchangeSpec] = {
    "binance": ExchangeSpec(
        key="binance", name="Binance", ccxt_id="binanceusdm", market="USDT-M futures",
        fields=(
            CredentialField("apiKey", "API key", "BINANCE_API_KEY", _KEY, "64 letters and digits"),
            CredentialField("secret", "Secret key", "BINANCE_API_SECRET", _KEY, "64 letters and digits; shown only once by Binance"),
        ),
        steps=(
            "Binance > Profile > API Management > Create API > System generated.",
            "Enable Reading and Enable Futures. Leave Enable Withdrawals OFF.",
            "Restrict access to trusted IPs (your PC or VPS address).",
            "Copy the API key and the Secret key (the secret is shown only once).",
        ),
        url="https://www.binance.com/en/my/settings/api-management",
    ),
    "bitget": ExchangeSpec(
        key="bitget", name="Bitget", ccxt_id="bitget", market="USDT-M futures", options={"defaultType": "swap"},
        fields=(
            CredentialField("apiKey", "API key", "BITGET_API_KEY", _KEY, "starts with bg_"),
            CredentialField("secret", "Secret key", "BITGET_API_SECRET", _KEY, "64 letters and digits"),
            CredentialField("password", "Passphrase", "BITGET_API_PASSPHRASE", r"^\S{6,64}$",
                            "the passphrase you chose when creating the key"),
        ),
        steps=(
            "Bitget > Profile > API Management > Create API key > System-generated.",
            "Set a passphrase and note it: Bitget needs it with every request.",
            "Permissions: Read-only + Futures (Orders, Holdings). No withdrawals.",
            "Bind your IP address, then copy the API key and the Secret key.",
        ),
        url="https://www.bitget.com/account/newapi",
    ),
    "mexc": ExchangeSpec(
        key="mexc", name="MEXC", ccxt_id="mexc", market="USDT-M futures", options={"defaultType": "swap"},
        fields=(
            CredentialField("apiKey", "Access key", "MEXC_API_KEY", _KEY, "starts with mx0"),
            CredentialField("secret", "Secret key", "MEXC_API_SECRET", _KEY, "32 letters and digits"),
        ),
        steps=(
            "MEXC > Profile > API Management > Create new API key.",
            "Permissions: Read + Trade (Futures). Never enable withdrawals.",
            "Link your IP address (keys without an IP expire after 90 days).",
            "Copy the Access key and the Secret key.",
        ),
        url="https://www.mexc.com/user/openapi",
    ),
}


def mask(value: str | None) -> str:
    if not value:
        return ""
    return value[:4] + "•" * 8 + value[-4:] if len(value) > 10 else "•" * len(value)


def read(env_file: Path, exchange: str) -> dict[str, str | None]:
    """Current values for one exchange (environment variables win over .env, as in config.py)."""
    file_values = dotenv_values(env_file) if env_file.is_file() else {}
    return {f.name: os.environ.get(f.env) or file_values.get(f.env) or None for f in EXCHANGES[exchange].fields}


def status(env_file: Path) -> dict[str, dict[str, Any]]:
    """Per exchange: whether all keys are set, and their masked values (never the full key)."""
    out = {}
    for key, spec in EXCHANGES.items():
        values = read(env_file, key)
        out[key] = {"configured": all(values.values()), "masked": {f.label: mask(values[f.name]) for f in spec.fields}}
    return out


def check(exchange: str, values: dict[str, str]) -> list[str]:
    """Soft format checks before saving: empty fields are errors, odd-looking values are warnings."""
    problems = []
    for f in EXCHANGES[exchange].fields:
        value = (values.get(f.name) or "").strip()
        if not value:
            problems.append(f"{f.label} is empty")
        elif not re.match(f.pattern, value):
            problems.append(f"{f.label} does not look right ({f.hint}); check for spaces or a missing part")
    return problems


def save(env_file: Path, exchange: str, values: dict[str, str]) -> None:
    if not env_file.exists():
        env_file.touch()
    for f in EXCHANGES[exchange].fields:
        set_key(str(env_file), f.env, values[f.name].strip(), quote_mode="never")


def remove(env_file: Path, exchange: str) -> None:
    if env_file.exists():
        for f in EXCHANGES[exchange].fields:
            unset_key(str(env_file), f.env, quote_mode="never")


def test_connection(exchange: str, values: dict[str, str | None]) -> tuple[bool, str]:
    """Read-only check: load the markets and read the futures balance. Blocking; run it in a thread."""
    import ccxt

    spec = EXCHANGES[exchange]
    if not all(values.values()):
        return False, "Keys are missing"
    client = getattr(ccxt, spec.ccxt_id)({**{k: v for k, v in values.items()}, "enableRateLimit": True,
                                          "timeout": 15000, "options": dict(spec.options)})
    try:
        balance = client.fetch_balance()
    except ccxt.AuthenticationError as exc:
        return False, f"Rejected by {spec.name}: {_short(exc)}"
    except ccxt.PermissionDenied as exc:
        return False, f"Key lacks a permission or your IP is not whitelisted: {_short(exc)}"
    except ccxt.NetworkError as exc:
        return False, f"Could not reach {spec.name}: {_short(exc)}"
    except ccxt.BaseError as exc:
        return False, f"{spec.name} error: {_short(exc)}"
    usdt = (balance.get("total") or {}).get("USDT")
    return True, f"Connected to {spec.name} {spec.market}. USDT balance: {usdt if usdt is not None else 0:.2f}"


def _short(exc: Exception) -> str:
    text = str(exc)
    return text[:220] + ("…" if len(text) > 220 else "")
