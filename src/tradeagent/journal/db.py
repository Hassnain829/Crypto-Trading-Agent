"""SQLite journal: connection in WAL mode and versioned migrations."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from tradeagent.journal.migrations import MIGRATIONS

LATEST_VERSION = MIGRATIONS[-1][0]


def now_ms() -> int:
    return int(time.time() * 1000)


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # the dashboard can read while the agent writes
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply pending migrations in order, each in its own transaction. Returns the versions applied."""
    applied = []
    for version, name, sql in MIGRATIONS:
        if version <= schema_version(conn):
            continue
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
        except sqlite3.Error as exc:
            conn.rollback()
            raise RuntimeError(f"migration {version} ({name}) failed: {exc}") from exc
        applied.append(version)
    return applied


def write_status(conn: sqlite3.Connection, key: str, value: Any) -> None:
    """Upsert one agent_status row (the agent's heartbeat for the dashboard)."""
    with conn:
        conn.execute(
            "INSERT INTO agent_status (key, value_json, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
            (key, json.dumps(value), now_ms()),
        )


def log_event(
    conn: sqlite3.Connection, level: str, source: str, message: str, data: Any = None
) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO events (ts, level, source, message, data_json) VALUES (?, ?, ?, ?, ?)",
            (now_ms(), level, source, message, None if data is None else json.dumps(data)),
        )
    return cur.lastrowid
