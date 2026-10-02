"""Journal schema migrations, applied in order. Never edit a released migration; add a new one.

Each entry is (version, name, sql). Later phases add their own tables (snapshots, candles,
trades, ...) as new migrations when those tables are designed.
"""

MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "initial",
        """
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,              -- milliseconds since epoch, UTC
    level TEXT NOT NULL,              -- INFO / WARNING / ERROR
    source TEXT NOT NULL,             -- e.g. doctor, reader, watchdog
    message TEXT NOT NULL,
    data_json TEXT
);
CREATE INDEX idx_events_ts ON events (ts);

-- Dashboard overrides of settings.yaml values (Phase 4).
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE settings_audit (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,
    key TEXT NOT NULL,
    old_json TEXT,
    new_json TEXT,
    source TEXT NOT NULL              -- dashboard / cli / research
);
""",
    ),
]
