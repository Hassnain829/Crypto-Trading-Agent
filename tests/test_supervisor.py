import asyncio
import json
import time

import pytest

from tradeagent import agent as agent_module
from tradeagent import supervisor
from tradeagent.agent import Agent
from tradeagent.journal import migrate
from tradeagent.journal.db import connect, now_ms, write_status
from tradeagent.supervisor import (InstanceLock, Supervisor, lock_path, request_stop, set_wanted_state,
                                   stop_requested_at, wanted_state)


@pytest.fixture
def conn(settings):
    c = connect(settings.resolve(settings.journal.path))
    migrate(c)
    yield c
    c.close()


def test_lock_allows_one_holder(tmp_path):
    path = tmp_path / "agent.lock"
    first, second = InstanceLock(path), InstanceLock(path)
    assert first.acquire()
    assert second.held_elsewhere()
    assert not second.acquire()
    first.release()
    assert not second.held_elsewhere()
    assert second.acquire()
    second.release()


def test_wanted_state_defaults_to_running_and_is_audited(conn):
    assert wanted_state(conn) == "running"
    set_wanted_state(conn, "stopped")
    assert wanted_state(conn) == "stopped"
    audit = conn.execute("SELECT key, new_json, source FROM settings_audit").fetchall()
    assert [tuple(r) for r in audit] == [("agent_wanted", '"stopped"', "dashboard")]
    with pytest.raises(ValueError):
        set_wanted_state(conn, "paused")


def _supervisor(settings, monkeypatch, running: bool, pid: int | None = None):
    spawned, ended = [], []
    monkeypatch.setattr(supervisor, "agent_running", lambda s, c: running)
    monkeypatch.setattr(supervisor, "agent_pid", lambda c: pid)
    monkeypatch.setattr(supervisor, "spawn_agent", lambda s: spawned.append(1) or 4242)
    monkeypatch.setattr(supervisor, "end_process", lambda p: ended.append(p))
    return Supervisor(settings), spawned, ended


def test_supervisor_starts_a_missing_agent_once_per_minute(settings, monkeypatch):
    sup, spawned, _ = _supervisor(settings, monkeypatch, running=False)
    assert sup.tick() == "started"
    assert sup.tick() is None  # still not running a moment later: no tight restart loop
    assert len(spawned) == 1
    events = sup.conn.execute("SELECT level, message FROM events").fetchall()
    assert events[0]["message"] == "agent started by the dashboard (pid 4242)"


def test_supervisor_leaves_a_stopped_agent_alone(settings, monkeypatch):
    sup, spawned, ended = _supervisor(settings, monkeypatch, running=False)
    set_wanted_state(sup.conn, "stopped")
    assert sup.tick() is None
    assert spawned == [] and ended == []


def test_supervisor_ends_an_agent_that_ignores_a_stop_request(settings, monkeypatch):
    sup, _, ended = _supervisor(settings, monkeypatch, running=True, pid=999)
    sup.stop_agent()
    assert sup.tick() is None  # it gets time to finish its step
    sup.conn.execute("UPDATE settings SET value_json = ? WHERE key = ?",
                     (json.dumps(now_ms() - (supervisor.STOP_TIMEOUT_S + 5) * 1000), supervisor.STOP_KEY))
    assert sup.tick() == "ended"
    assert ended == [999]


def test_start_button_does_not_start_a_second_agent(settings, monkeypatch):
    sup, spawned, _ = _supervisor(settings, monkeypatch, running=True)
    set_wanted_state(sup.conn, "stopped")
    assert sup.start_agent() == "already running"
    assert spawned == []
    assert wanted_state(sup.conn) == "running"


def test_agent_stops_on_a_request_made_after_it_started(conn, monkeypatch):
    monkeypatch.setattr(agent_module, "STOP_POLL_S", 0.01)

    class Stub:
        pass
    stub = Stub()
    stub.conn = conn
    request_stop(conn)  # an old request (before the start) is ignored
    started = stop_requested_at(conn) + 1

    async def scenario() -> bool:
        stop = asyncio.Event()
        task = asyncio.create_task(Agent._watch_stop_requests(stub, stop, started))
        await asyncio.sleep(0.05)
        ignored = not stop.is_set()
        time.sleep(0.002)
        request_stop(conn)
        await asyncio.wait_for(task, timeout=2)
        return ignored and stop.is_set()

    assert asyncio.run(scenario())


def test_agent_pid_ignores_processes_that_are_not_the_agent(conn):
    import os

    write_status(conn, "agent", {"pid": os.getpid()})  # the test runner is python, but not "tradeagent agent"
    assert supervisor.agent_pid(conn) is None


def test_lock_file_lives_next_to_the_journal(settings):
    assert lock_path(settings) == settings.resolve(settings.journal.path).parent / "agent.lock"
