"""Kill switch, stored in the journal's settings table (the dashboard will use the same key)."""

from __future__ import annotations

import json
import sqlite3

from tradeagent.journal.db import now_ms

KEY = "kill_switch"
MODES = ("off", "pause", "close_all")  # pause: no new entries; close_all: close everything, then pause


def get_kill_switch(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value_json FROM settings WHERE key = ?", (KEY,)).fetchone()
    return json.loads(row[0]) if row else "off"


def set_kill_switch(conn: sqlite3.Connection, mode: str, source: str) -> None:
    if mode not in MODES:
        raise ValueError(f"kill switch mode must be one of {MODES}")
    old = get_kill_switch(conn)
    now = now_ms()
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
            (KEY, json.dumps(mode), now),
        )
        conn.execute(
            "INSERT INTO settings_audit (ts, key, old_json, new_json, source) VALUES (?, ?, ?, ?, ?)",
            (now, KEY, json.dumps(old), json.dumps(mode), source),
        )
