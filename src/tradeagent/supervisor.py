"""Starts, watches and stops the agent process for the dashboard.

The agent runs as its own process, so trading continues when the dashboard closes. The dashboard keeps it
running: it starts the agent when the dashboard starts and again after a crash, unless you stopped it on
purpose (the wanted state is kept in the journal, so a stopped agent stays stopped after a restart too).
The agent itself starts TradingView in debug mode when the debug port is closed (tv/watchdog.py).

Only one agent can run: it holds data/agent.lock while it runs, and the OS releases the lock if it dies.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from tradeagent.config import Settings
from tradeagent.journal import log_event, migrate
from tradeagent.journal.db import now_ms

log = logging.getLogger("tradeagent.supervisor")

WANTED_KEY = "agent_wanted"  # "running" | "stopped"
STOP_KEY = "agent_stop_request"  # ms; the agent stops when it sees a request made after it started
CHECK_EVERY_S = 15
RESTART_AFTER_S = 60  # at most one start per minute, so a crashing agent is not restarted in a tight loop
STOP_TIMEOUT_S = 90  # an agent that ignores a stop request this long is ended


class InstanceLock:
    """An OS lock on a file, held while the process runs and released automatically when it ends."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh = None

    def acquire(self, attempts: int = 1, wait_s: float = 0.5) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(attempts):
            fh = open(self.path, "a+b")
            try:
                if os.name == "nt":
                    import msvcrt

                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                fh.close()
                if attempt < attempts - 1:
                    time.sleep(wait_s)
                continue
            self._fh = fh
            return True
        return False

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self._fh.close()
        self._fh = None

    def held_elsewhere(self) -> bool:
        """Another process holds the lock (checked by taking and releasing it)."""
        if self._fh is not None:
            return False
        if self.acquire():
            self.release()
            return False
        return True


def lock_path(settings: Settings) -> Path:
    return settings.resolve(settings.journal.path).parent / "agent.lock"


# ---- wanted state and stop requests (journal settings table) --------------------------------------
def _get(conn: sqlite3.Connection, key: str):
    row = conn.execute("SELECT value_json FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def _set(conn: sqlite3.Connection, key: str, value, source: str | None = None) -> None:
    old = _get(conn, key)
    now = now_ms()
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
            (key, json.dumps(value), now),
        )
        if source:
            conn.execute(
                "INSERT INTO settings_audit (ts, key, old_json, new_json, source) VALUES (?, ?, ?, ?, ?)",
                (now, key, json.dumps(old), json.dumps(value), source),
            )


def wanted_state(conn: sqlite3.Connection) -> str:
    return _get(conn, WANTED_KEY) or "running"


def set_wanted_state(conn: sqlite3.Connection, state: str, source: str = "dashboard") -> None:
    if state not in ("running", "stopped"):
        raise ValueError("state must be running or stopped")
    if wanted_state(conn) != state or _get(conn, WANTED_KEY) is None:
        _set(conn, WANTED_KEY, state, source)


def request_stop(conn: sqlite3.Connection) -> None:
    _set(conn, STOP_KEY, now_ms())


def stop_requested_at(conn: sqlite3.Connection) -> int | None:
    return _get(conn, STOP_KEY)


# ---- the agent process --------------------------------------------------------------------------
def _is_agent_process(pid: int) -> bool:
    try:
        proc = psutil.Process(pid)
        if "python" not in proc.name().lower():
            return False
        try:
            cmd = proc.cmdline()
        except psutil.AccessDenied:
            return True
        return "tradeagent" in cmd and "agent" in cmd
    except psutil.Error:
        return False


def agent_pid(conn: sqlite3.Connection) -> int | None:
    """Process id of the running agent, from the status it writes at start (None when it is not running)."""
    row = conn.execute("SELECT value_json FROM agent_status WHERE key = 'agent'").fetchone()
    pid = json.loads(row[0]).get("pid") if row else None
    return pid if pid and _is_agent_process(pid) else None


def agent_running(settings: Settings, conn: sqlite3.Connection) -> bool:
    # The lock covers agents started any way; the pid check also covers agents started before the lock existed.
    return InstanceLock(lock_path(settings)).held_elsewhere() or agent_pid(conn) is not None


def spawn_agent(settings: Settings) -> int:
    """Start `python -m tradeagent agent` in the background, without a window. Returns its process id."""
    log_file = settings.resolve(settings.logging.file).with_name("agent-console.log")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    out = open(log_file, "ab")
    out.write(f"\n--- {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} started by the dashboard ---\n".encode())
    out.flush()
    kwargs = dict(cwd=settings.root, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, close_fds=True,
                  env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    cmd = [sys.executable, "-m", "tradeagent", "agent"]
    try:
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            try:  # leave the dashboard's job object, so closing the dashboard's console does not end the agent
                proc = subprocess.Popen(cmd, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kwargs)
            except OSError:
                proc = subprocess.Popen(cmd, creationflags=flags, **kwargs)
        else:
            proc = subprocess.Popen(cmd, start_new_session=True, **kwargs)
    finally:
        out.close()
    return proc.pid


def end_process(pid: int, timeout_s: float = 15) -> None:
    """End a process and its children (used only when the agent ignored a stop request)."""
    try:
        proc = psutil.Process(pid)
        procs = proc.children(recursive=True) + [proc]
    except psutil.Error:
        return
    for p in procs:
        try:
            p.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(procs, timeout=timeout_s)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass


class Supervisor:
    """Runs in the dashboard process: keeps the agent in its wanted state (checked every 15 s)."""

    def __init__(self, settings: Settings, *, watch: bool = True) -> None:
        self.settings = settings
        self.watch = watch  # False (dashboard --no-agent): only the buttons start or stop the agent
        # Used by the check thread and by the dashboard's buttons, always under self._lock.
        self.conn = sqlite3.connect(settings.resolve(settings.journal.path), timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        migrate(self.conn)
        self._lock = threading.Lock()
        self._last_start = float("-inf")
        self._started_once = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="agent-supervisor", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while True:
            if self.watch:
                try:
                    self.tick()
                except Exception:  # never let the supervisor thread die
                    log.exception("supervisor check failed")
            time.sleep(CHECK_EVERY_S)

    def tick(self) -> str | None:
        """One check. Returns what was done, if anything."""
        with self._lock:
            running = agent_running(self.settings, self.conn)
            if wanted_state(self.conn) == "running":
                if not running and time.monotonic() - self._last_start >= RESTART_AFTER_S:
                    return self._spawn()
                return None
            requested = stop_requested_at(self.conn) or 0
            pid = agent_pid(self.conn)
            if running and pid and now_ms() - requested > STOP_TIMEOUT_S * 1000:
                end_process(pid)
                log_event(self.conn, "WARNING", "supervisor", f"agent (pid {pid}) did not stop in {STOP_TIMEOUT_S} s; ended it")
                return "ended"
            return None

    def _spawn(self) -> str:
        pid = spawn_agent(self.settings)
        self._last_start = time.monotonic()
        if self._started_once:
            log_event(self.conn, "WARNING", "supervisor", f"agent was not running; started it again (pid {pid})")
        else:
            log_event(self.conn, "INFO", "supervisor", f"agent started by the dashboard (pid {pid})")
        self._started_once = True
        return "started"

    # ---- buttons ----------------------------------------------------------------------------
    def start_agent(self) -> str:
        with self._lock:
            set_wanted_state(self.conn, "running")
            if agent_running(self.settings, self.conn):
                return "already running"
            return self._spawn()

    def stop_agent(self) -> None:
        with self._lock:
            set_wanted_state(self.conn, "stopped")
            request_stop(self.conn)

    def restart_agent(self) -> None:
        """Stop the agent; the next check after it stopped starts it again."""
        with self._lock:
            set_wanted_state(self.conn, "running")
            request_stop(self.conn)
            self._last_start = float("-inf")
