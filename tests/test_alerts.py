"""Phone alerts (ntfy): problems are sent once and closed when solved; demo trades become messages; nothing is
sent when alerts are off or not set up."""

import pytest

from tradeagent import alerts, supervisor
from tradeagent.journal import connect, migrate
from tradeagent.journal.db import now_ms, write_status
from tradeagent.tv.snapshots import Snapshot


@pytest.fixture
def sent(monkeypatch):
    messages: list[str] = []
    monkeypatch.setattr(alerts, "send", lambda settings, text, **kw: messages.append(text))
    return messages


@pytest.fixture
def conn(settings):
    c = connect(settings.resolve(settings.journal.path))
    migrate(c)
    yield c
    c.close()


def test_a_problem_is_sent_once_repeated_later_and_closed_when_solved(settings, sent, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(alerts.time, "monotonic", lambda: clock[0])
    alerter = alerts.Alerter(settings)
    assert alerter.problem("reads", "reads fail")
    assert not alerter.problem("reads", "reads fail")  # no flood every cycle
    clock[0] += settings.alerts.repeat_hours * 3600
    assert alerter.problem("reads", "reads fail")
    assert alerter.solved("reads", "good again")
    assert not alerter.solved("reads", "good again")  # nothing open any more
    assert sent == ["PROBLEM: reads fail", "STILL A PROBLEM: reads fail", "SOLVED: good again"]
    alerter.problem("agent", "silent")
    alerter.forget("agent")
    assert not alerter.solved("agent", "back") and len(sent) == 4


def test_nothing_is_sent_when_alerts_are_off_or_not_set_up(settings, tmp_path):
    assert alerts.send_now(settings, "x") == "alerts are off (alerts.enabled)"  # the tests' settings turn them off
    settings.alerts.enabled = True
    settings._root = tmp_path  # a project without NTFY_TOPIC in .env
    assert "NTFY_TOPIC" in alerts.send_now(settings, "x")
    assert not alerts.ready(settings)


def test_a_message_is_posted_to_the_ntfy_topic(settings, tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("NTFY_TOPIC=cryptai-test-topic\n", encoding="utf-8")
    settings._root, settings.alerts.enabled = tmp_path, True
    posted = []

    class Reply:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout):
        posted.append((request.full_url, dict(request.header_items()), request.data.decode("utf-8")))
        return Reply()
    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_urlopen)
    assert alerts.send_now(settings, "PROBLEM: reads fail", priority="high", tags="warning") is None
    url, headers, body = posted[0]
    assert url == "https://ntfy.sh/cryptai-test-topic" and body == "PROBLEM: reads fail"
    assert headers["Priority"] == "high" and headers["Tags"] == "warning" and headers["Title"] == "Crypt-AI Agent"


def _account_trade(conn, trade_id, status, created, updated, **values):
    row = {"account": "paper", "trade_id": trade_id, "variant_id": "v0", "symbol": "SOL", "timeframe": "15m",
           "side": "long", "status": status, "entry_time": created, "created_at": created, "updated_at": updated,
           **values}
    conn.execute(f"INSERT INTO account_trades ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
    conn.commit()


def test_demo_decisions_become_messages_once(conn):
    t0 = 1_791_000_000_000
    opened = {"entry_fill": 100.0, "stop": 97.0, "risk_usd": 6.0, "balance_before": 200.0, "notes": "quality A: 3.0% risk"}
    _account_trade(conn, 1, "open", t0 + 1, t0 + 1, **opened)
    _account_trade(conn, 2, "rejected", t0 + 2, t0 + 2, reject_reason="open risk budget used")
    _account_trade(conn, 3, "closed", t0 - 50, t0 + 3, **opened, exit_reason="target", r_net=1.45, pnl_usd=8.7,
                   balance_after=208.7)
    messages, newest = alerts.trade_messages(conn, t0)
    assert messages == [
        "Demo opened SOL 15m long\nEntry 100, SL 97 (3.00% away), TP -\nRisk 6.00 USDT = 3.0% of the balance (quality A: 3.0% risk)",
        "Demo skipped SOL 15m long: open risk budget used",
        "Demo closed SOL 15m long: target, +1.45R, +8.70 USDT. Balance 208.70 USDT",  # opened before: only the close
    ]
    assert newest == t0 + 3 and alerts.trade_messages(conn, newest) == ([], newest)


def test_the_reader_alerts_after_failed_cycles_in_a_row_and_when_reads_are_good_again(settings, sent):
    from tradeagent.tv.catalog import load_catalog
    from tradeagent.tv.reader import SignalReader

    class Clock:
        offset_ms = 0

        def now_ms(self):
            return 1_791_000_000_000

    conn = connect(settings.resolve(settings.journal.path))
    migrate(conn)
    reader = SignalReader(settings, load_catalog(settings.resolve(settings.tradingview.catalog)), conn,
                          cdp=object(), clock=Clock())
    reader.alerter = alerts.Alerter(settings)
    bad = [Snapshot("XRP", "5m", 0, 1, 1, problems=["chart tab is not open"])]
    for _ in range(settings.alerts.failed_cycles - 1):
        reader._record_cycle(1_791_000_000, bad)
    assert sent == []  # one or two bad cycles: TradingView often recovers by itself
    reader._record_cycle(1_791_000_000, bad)
    assert len(sent) == 1 and sent[0].startswith("PROBLEM: 3 cycles in a row") and "chart tab is not open" in sent[0]
    reader._record_cycle(1_791_000_000, [Snapshot("XRP", "5m", 0, 1, 1)])
    assert sent[-1].startswith("SOLVED: TradingView reads are good again")


def test_the_dashboard_alerts_when_the_agent_finishes_no_cycles(settings, sent, monkeypatch, conn):
    monkeypatch.setattr(supervisor, "agent_running", lambda s, c: True)
    sup = supervisor.Supervisor(settings)
    write_status(conn, "heartbeat", {"at": now_ms()})
    sup.tick()
    assert sent == []
    stale = now_ms() - int((settings.alerts.stale_minutes + 1) * 60_000)
    conn.execute("UPDATE agent_status SET updated_at = ? WHERE key = 'heartbeat'", (stale,))
    conn.commit()
    sup.tick()
    assert len(sent) == 1 and "has not finished a cycle" in sent[0]
    write_status(conn, "heartbeat", {"at": now_ms()})
    sup.tick()
    assert sent[-1] == "SOLVED: the agent is finishing its cycles again"


def test_status_written_in_the_app_gets_an_answer(settings, sent, tmp_path):
    (tmp_path / ".env").write_text("NTFY_TOPIC=cryptai-test-topic", encoding="utf-8")
    settings._root, settings.alerts.enabled = tmp_path, True
    listener = alerts.CommandListener(settings, lambda: "Demo status: 1 open position")
    listener._fetch = lambda name, server: [
        {"id": "a1", "event": "message", "title": alerts.TITLE, "message": "status"},  # our own message
        {"id": "a2", "event": "message", "message": " Status "},
        {"id": "a3", "event": "message", "message": "hello"},
        {"id": "a4", "event": "message", "message": "help"},
    ]
    assert listener.poll_once() == ["status", "help"]
    assert listener.since == "a4"  # the next poll starts after these
    assert sent[0] == "Demo status: 1 open position" and "Write 'status'" in sent[1]
    settings.alerts.enabled = False
    assert listener.poll_once() == []
