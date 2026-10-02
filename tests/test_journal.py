import pytest

from tradeagent.journal import db


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "journal.db")
    yield connection
    connection.close()


def test_migrate_creates_schema_in_wal_mode(conn):
    assert db.migrate(conn) == [version for version, _, _ in db.MIGRATIONS]
    assert db.schema_version(conn) == db.LATEST_VERSION
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"events", "settings", "settings_audit"} <= tables


def test_migrate_twice_applies_nothing_the_second_time(conn):
    db.migrate(conn)
    assert db.migrate(conn) == []


def test_log_event_roundtrip(conn):
    db.migrate(conn)
    db.log_event(conn, "INFO", "test", "hello", {"a": 1})
    row = conn.execute("SELECT level, source, message, data_json FROM events").fetchone()
    assert tuple(row) == ("INFO", "test", "hello", '{"a": 1}')


def test_failed_migration_rolls_back_completely(conn, monkeypatch):
    broken = (2, "broken", "CREATE TABLE half_done (x INTEGER);\nTHIS IS NOT SQL;")
    monkeypatch.setattr(db, "MIGRATIONS", [db.MIGRATIONS[0], broken])

    with pytest.raises(RuntimeError, match="migration 2"):
        db.migrate(conn)

    assert db.schema_version(conn) == 1
    assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name = 'half_done'").fetchone()[0] == 0
