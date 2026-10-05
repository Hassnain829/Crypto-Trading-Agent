"""Phase 5 learning loop: allowed changes, the experiment lifecycle, promotion, lessons and the research pack."""

import json

import pytest
import yaml

from tradeagent.journal import connect, migrate
from tradeagent.learning import experiments as ex
from tradeagent.learning.pack import build_pack, to_markdown, write_results
from tradeagent.learning.screen import MIN_HALF_TRADES, judge
from tradeagent.learning.space import SPACE, override_for, proposal_schema, validate_change
from tradeagent.setups.config import register_variants

BASE = {
    "timeframes": ["5m", "15m"],
    "trigger": {"indicator": "qtrend", "long": "buy", "short": "sell"},
    "confirmation": {"window": 3, "klinger": True, "candle_direction": True},
    "filters": {"vwap": False, "macd_trend": False, "htf": "none", "min_stop_pct": 1.5},
    "entry": {"mode": "limit"},
    "stop": {"lookback": 10},
    "exit": {"mode": "fixed", "take_profit_r": 1.5, "partial_r": 1.0, "partial_fraction": 0.5, "trail_lookback": 3},
}
T0 = 1_791_000_000_000
H = 3_600_000


@pytest.fixture
def lab(settings, tmp_path):
    setups = tmp_path / "setups.yaml"
    setups.write_text(yaml.safe_dump({"baseline": BASE, "variants": {"tf_15m": {"timeframes": ["15m"]}}}), encoding="utf-8")
    settings.shadow.setups = str(setups)
    settings._root = tmp_path  # lessons, packs and results.tsv go to the temp folder
    settings.paper_account.symbols = ["XRP", "SOL"]
    conn = connect(settings.resolve(settings.journal.path))
    migrate(conn)
    yield conn, settings
    conn.close()


def _variants(conn, settings):
    variants = ex.active_variants(settings, conn)
    register_variants(conn, variants)
    ex.sync_manual(conn, settings, variants)
    return variants


def _trades(conn, variant_id, r_values, start, symbol="XRP"):
    rows = []
    for i, r in enumerate(r_values):
        t = start + i * H
        rows.append(("exploration", variant_id, symbol, "5m", "long", 1, t, t, t, 1, None, "fixed", 100.0, 98.5, 102.25,
                     "closed", t + 60_000, "target" if r > 0 else "stop", r, 0.0, 0.0, 0.0, r, max(r, 0.2), -1.0, 0,
                     json.dumps({"htf": {"1h": "bull", "4h": "bear"}, "snapshot_id": i}), "{}", t, t))
    conn.executemany(f"INSERT INTO trades (book, variant_id, symbol, timeframe, side, signal_version, trigger_time,"
                     f" confirm_time, entry_time, taken, reason, exit_mode, entry_ref, stop_initial, target, status,"
                     f" exit_time, exit_reason, r_gross, fees_r, slippage_r, funding_r, r_net, mfe_r, mae_r, ambiguous,"
                     f" context_json, state_json, created_at, updated_at) VALUES ({','.join('?' * 30)})", rows)
    conn.commit()


def _proposal(name="floor_125", path="filters.min_stop_pct", value=1.25):
    return {"name": name, "change": {"path": path, "value": value},
            "hypothesis": "a slightly lower minimum stop keeps more trades without letting fees eat them",
            "expected": "+0.02R", "confidence": 0.3}


# ---- allowed changes ---------------------------------------------------------------------------

def test_validate_change_accepts_one_allowed_rule_and_rejects_the_rest():
    rules, problems = validate_change(BASE, "filters.min_stop_pct", 1.25)
    assert problems == [] and rules["filters"]["min_stop_pct"] == 1.25 and BASE["filters"]["min_stop_pct"] == 1.5
    assert "cannot be changed" in validate_change(BASE, "costs.maker_fee", 0.0)[1][0]
    assert "multiple of" in validate_change(BASE, "filters.min_stop_pct", 1.3)[1][0]
    assert "between" in validate_change(BASE, "exit.take_profit_r", 9)[1][0]
    assert "already" in validate_change(BASE, "filters.min_stop_pct", 1.5)[1][0]
    assert "already" in validate_change(BASE, "timeframes", ["5m", "15m"])[1][0]
    assert validate_change(BASE, "filters.session_utc", [13, 21])[1] == []
    assert "at least 4 hours" in validate_change(BASE, "filters.session_utc", [13, 15])[1][0]
    assert validate_change(BASE, "stop.min_pct", None)[1][0].startswith("stop.min_pct is already")
    assert override_for("stop.min_pct", 1.5) == {"stop": {"min_pct": 1.5}}


def test_the_schema_file_matches_the_allowed_changes(repo_root):
    schema = proposal_schema()
    assert schema["properties"]["proposals"]["items"]["properties"]["change"]["properties"]["path"]["enum"] == list(SPACE)
    on_disk = json.loads((repo_root / "research" / "proposal.schema.json").read_text(encoding="utf-8"))
    assert on_disk == schema, "regenerate research/proposal.schema.json from space.proposal_schema()"


# ---- proposals ----------------------------------------------------------------------------------

def test_a_proposal_is_validated_recorded_and_not_repeated(lab):
    conn, settings = lab
    _variants(conn, settings)
    exp_id, problems = ex.propose(conn, settings, _proposal())
    assert problems == []
    row = conn.execute("SELECT * FROM experiments WHERE id = ?", (exp_id,)).fetchone()
    assert row["status"] == "screening" and row["started_at"] is None
    assert json.loads(row["change_json"]) == {"filters": {"min_stop_pct": 1.25}}
    assert "taken" in ex.propose(conn, settings, _proposal())[1][0]
    assert "already tested" in ex.propose(conn, settings, _proposal(name="floor_again"))[1][0]
    assert "taken" in ex.propose(conn, settings, _proposal(name="tf_15m", path="exit.take_profit_r", value=2.0))[1][0]
    bad = {"name": "Bad Name", "change": {"path": "x", "value": 1, "extra": 2}, "hypothesis": ""}
    assert len(ex.propose(conn, settings, bad)[1]) == 3


def test_the_number_of_challengers_is_capped(lab):
    conn, settings = lab
    _variants(conn, settings)  # tf_15m from setups.yaml is one
    settings.learning.max_challengers = 2
    assert ex.propose(conn, settings, _proposal())[1] == []
    assert "max 2" in ex.propose(conn, settings, _proposal("tp_2", "exit.take_profit_r", 2.0))[1][0]


def test_screen_verdicts_start_or_reject_the_experiment(lab):
    conn, settings = lab
    _variants(conn, settings)
    a, _ = ex.propose(conn, settings, _proposal())
    b, _ = ex.propose(conn, settings, _proposal("tp_2", "exit.take_profit_r", 2.0))
    ex.finish_screen(conn, settings, a, {"passed": True, "why": "beat it"})
    ex.finish_screen(conn, settings, b, {"passed": False, "why": "half 1 worse"})
    assert conn.execute("SELECT status, started_at IS NOT NULL FROM experiments WHERE id = ?", (a,)).fetchone()[:] == ("running", 1)
    assert conn.execute("SELECT status FROM experiments WHERE id = ?", (b,)).fetchone()[0] == "rejected"
    names = [v.name for v in ex.active_variants(settings, conn)]
    assert names == ["v0", "tf_15m", "floor_125"]  # running ones trade; rejected and screening ones do not
    assert "half 1 worse" in ex.lessons_path(settings).read_text(encoding="utf-8")


def test_manual_challengers_are_tracked_and_stopped_when_removed(lab):
    conn, settings = lab
    _variants(conn, settings)
    row = conn.execute("SELECT source, status, change_json FROM experiments WHERE name = 'tf_15m'").fetchone()
    assert tuple(row) == ("setups.yaml", "running", '{"timeframes":["15m"]}')
    path = settings.resolve(settings.shadow.setups)
    path.write_text(yaml.safe_dump({"baseline": BASE, "variants": {}}), encoding="utf-8")
    assert ex.sync_manual(conn, settings, ex.active_variants(settings, conn)) == ["stopped tf_15m (removed from setups.yaml)"]


# ---- judging and promotion ----------------------------------------------------------------------

def test_a_winner_is_reconfirmed_then_promoted(lab):
    conn, settings = lab
    settings.learning.screen_on_history = False
    settings.learning.min_trades = 10
    settings.learning.reconfirm_trades = 10
    variants = _variants(conn, settings)
    exp_id, _ = ex.propose(conn, settings, _proposal())
    conn.execute("UPDATE experiments SET started_at = ? WHERE name IN ('floor_125', 'tf_15m')", (T0,))
    conn.commit()
    variants = _variants(conn, settings)
    base, ch = variants[0], next(v for v in variants if v.name == "floor_125")
    _trades(conn, base.id, [1.5, -1, -1, 1.5, -1, -1, 1.5, -1, -1, 1.5], T0)  # +0.0 R a trade
    _trades(conn, ch.id, [1.5, -1, 1.5, -1, 1.5, -1, 1.5, -1, 1.5, -1], T0)  # +0.25 R a trade
    actions = ex.evaluate(conn, settings, variants)
    assert any("floor_125 won the first round" in a for a in actions)
    assert not any("tf_15m" in a for a in actions)  # no trades of its own yet: no verdict
    reconfirm_from = conn.execute("SELECT reconfirm_from FROM experiments WHERE id = ?", (exp_id,)).fetchone()[0]
    _trades(conn, base.id, [1.5, -1, -1] * 4, reconfirm_from + 1, symbol="SOL")
    _trades(conn, ch.id, [1.5, -1] * 6, reconfirm_from + 1, symbol="SOL")
    actions = ex.evaluate(conn, settings, variants)
    assert actions == ["floor_125 promoted to baseline v3.2"]
    assert ex.effective_baseline(settings, conn)["filters"]["min_stop_pct"] == 1.25
    new = ex.active_variants(settings, conn)
    assert new[0].params.filters.min_stop_pct == 1.25 and new[0].id != base.id
    assert [v.name for v in new] == ["v0", "tf_15m"]  # floor_125 is now the baseline
    history = conn.execute("SELECT version, variant_id FROM baseline_history ORDER BY adopted_at DESC").fetchone()
    assert tuple(history) == ("v3.2", new[0].id)
    lessons = ex.lessons_path(settings).read_text(encoding="utf-8")
    assert "Promoted to baseline v3.2" in lessons


def test_a_loser_is_closed_with_a_lesson(lab):
    conn, settings = lab
    settings.learning.min_trades = 10
    variants = _variants(conn, settings)
    conn.execute("UPDATE experiments SET started_at = ? WHERE name = 'tf_15m'", (T0,))
    conn.commit()
    _trades(conn, variants[0].id, [1.5, -1] * 5, T0)
    _trades(conn, variants[1].id, [1.5, -1, -1] * 3 + [-1], T0)
    assert ex.evaluate(conn, settings, variants)[0].startswith("tf_15m lost: expectancy")
    assert conn.execute("SELECT status FROM experiments WHERE name = 'tf_15m'").fetchone()[0] == "lost"
    assert "Did not beat the baseline" in ex.lessons_path(settings).read_text(encoding="utf-8")


def test_a_promotion_restarts_the_other_comparisons(lab):
    conn, settings = lab
    settings.learning.screen_on_history = False
    variants = _variants(conn, settings)
    a, _ = ex.propose(conn, settings, _proposal())
    b, _ = ex.propose(conn, settings, _proposal("tp_2", "exit.take_profit_r", 2.0))
    ex.promote(conn, settings, a, {"challenger": {"trades": 120, "expectancy_r": 0.3}})
    variants = ex.active_variants(settings, conn)
    actions = ex.evaluate(conn, settings, variants)
    assert "tp_2: new baseline, comparison restarted" in actions
    row = conn.execute("SELECT baseline_id, variant_id FROM experiments WHERE id = ?", (b,)).fetchone()
    assert row["baseline_id"] == variants[0].id
    assert row["variant_id"] == next(v.id for v in variants if v.name == "tp_2")


def test_screen_judge_needs_the_whole_history_and_both_halves(settings):
    def s(trades, exp, pf=1.5, dd=5.0):
        return {"trades": trades, "expectancy_r": exp, "profit_factor": pf, "max_drawdown_r": dd}

    good = {"all": {"challenger": s(60, 0.35), "baseline": s(80, 0.25)},
            "halves": [{"challenger": s(30, 0.3), "baseline": s(40, 0.3)}, {"challenger": s(30, 0.4), "baseline": s(40, 0.2)}]}
    assert judge(good, settings) == (True, "")
    worse_half = json.loads(json.dumps(good))
    worse_half["halves"][0]["challenger"]["expectancy_r"] = 0.2
    assert "half 1" in judge(worse_half, settings)[1]
    thin = json.loads(json.dumps(good))
    thin["halves"][1]["challenger"]["trades"] = MIN_HALF_TRADES - 1
    assert "only" in judge(thin, settings)[1]
    small_edge = json.loads(json.dumps(good))
    small_edge["all"]["challenger"]["expectancy_r"] = 0.27
    assert "expectancy" in judge(small_edge, settings)[1]


# ---- research pack --------------------------------------------------------------------------------

def test_the_research_pack_has_the_numbers_claude_needs(lab):
    conn, settings = lab
    variants = _variants(conn, settings)
    _trades(conn, variants[0].id, [1.5, -1, -1, 1.5], T0)
    _trades(conn, variants[0].id, [-1, -1], T0, symbol="LINK")  # not a demo coin: left out
    pack = build_pack(settings, conn, variants)
    assert pack["coins"] == ["XRP", "SOL"]
    assert pack["variants"][0]["history"]["trades"] == 4
    assert pack["baseline_breakdown"]["by_htf"] == {"only 1h with": pack["variants"][0]["history"]}
    assert pack["baseline_breakdown"]["streaks"]["longest_losing"] == 2
    assert pack["allowed_changes"]["filters.min_stop_pct"]["now"] == 1.5
    assert pack["experiments"][0]["name"] == "tf_15m"
    md = to_markdown(pack)
    assert "## Allowed changes" in md and "`filters.min_stop_pct` now `1.5`" in md
    tsv = write_results(settings, conn).read_text(encoding="utf-8").splitlines()
    assert tsv[0].startswith("id\tcreated\tname") and "\ttf_15m\tsetups.yaml\t" in tsv[1]


# ---- promotion into setups.yaml -------------------------------------------------------------------

def test_a_promotion_edits_only_the_changed_lines_of_the_real_setups_file(repo_root, tmp_path):
    from tradeagent.learning.setups_file import promote_in_file

    original = (repo_root / "config" / "setups.yaml").read_text(encoding="utf-8")
    path = tmp_path / "setups.yaml"
    path.write_text(original, encoding="utf-8")
    change = {"filters": {"session_utc": [13, 21], "trend_15m": True}, "stop": {"min_pct": 1.5}}
    backup = promote_in_file(path, change, "session_13_21", "v3.2 (2026-10-05): test note", tmp_path / "backups")
    new = path.read_text(encoding="utf-8")
    assert backup.read_text(encoding="utf-8") == original
    data = yaml.safe_load(new)
    assert data["baseline"]["filters"]["session_utc"] == [13, 21] and data["baseline"]["filters"]["trend_15m"] is True
    assert data["baseline"]["stop"]["min_pct"] == 1.5 and "session_13_21" not in data["variants"]
    assert "    session_utc: [13, 21]    # [start, end): only entries whose UTC hour is inside" in new.splitlines()
    assert "#   v3.2 (2026-10-05): test note" in new
    changed = set(new.splitlines()) - set(original.splitlines())
    assert len(changed) == 4  # session_utc, trend_15m, min_pct and the history note; every other line untouched


def test_timeframes_and_values_are_written_in_the_files_style():
    from tradeagent.learning.setups_file import fmt, set_baseline_rule

    text = 'baseline:\n  timeframes: ["5m", "15m"]\n  trigger:\n    long: buy        # flag\n\nvariants:\n  a: {x: 1}\n'
    out = set_baseline_rule(set_baseline_rule(text, "timeframes", ["15m"]), "trigger.long", "strong_buy")
    assert out == 'baseline:\n  timeframes: ["15m"]\n  trigger:\n    long: strong_buy # flag\n\nvariants:\n  a: {x: 1}\n'
    assert (fmt(None), fmt(True), fmt(1.25), fmt("against_4h"), fmt("1h"), fmt("yes"), fmt([13, 21])) == \
        ("null", "true", "1.25", "against_4h", '"1h"', '"yes"', "[13, 21]")
    block = "baseline:\n  timeframes:\n  - 5m\n  - 15m\n  exit:\n    take_profit_r: 1.5\n"
    assert set_baseline_rule(block, "timeframes", ["15m"]) == \
        'baseline:\n  timeframes: ["15m"]\n  exit:\n    take_profit_r: 1.5\n'


def test_an_early_promotion_by_hand_is_allowed_only_on_purpose(lab):
    conn, settings = lab
    variants = _variants(conn, settings)
    exp_id = conn.execute("SELECT id FROM experiments WHERE name = 'tf_15m'").fetchone()[0]
    with pytest.raises(ValueError, match="won twice"):
        ex.promote(conn, settings, exp_id, by="dashboard")
    assert ex.promote(conn, settings, exp_id, by="dashboard", early=True) == "tf_15m promoted to baseline v3.2"
    data = yaml.safe_load(settings.resolve(settings.shadow.setups).read_text(encoding="utf-8"))
    assert data["baseline"]["timeframes"] == ["15m"] and not data["variants"]
    row = conn.execute("SELECT status, result_json FROM experiments WHERE id = ?", (exp_id,)).fetchone()
    assert row["status"] == "promoted" and json.loads(row["result_json"])["phase"] == "early"
    assert "before the judge's rules were met" in ex.lessons_path(settings).read_text(encoding="utf-8")
    assert list((settings.root / "data" / "backups").glob("setups-*-before-tf_15m.yaml"))
    assert ex.active_variants(settings, conn)[0].params.timeframes == ["15m"] != variants[0].params.timeframes


def test_the_gate_counts_the_winners_forward_trades_after_its_promotion(lab):
    from tradeagent.account.report import forward_sample

    conn, settings = lab
    variants = _variants(conn, settings)
    ch = next(v for v in variants if v.name == "tf_15m")
    _trades(conn, variants[0].id, [1.5, -1], T0)
    _trades(conn, ch.id, [1.5, 1.5, -1], T0 + 10 * H)
    assert forward_sample(conn, T0, ["XRP"]) == [1.5, -1]
    exp_id = conn.execute("SELECT id FROM experiments WHERE name = 'tf_15m'").fetchone()[0]
    ex.promote(conn, settings, exp_id, by="cli", early=True)
    register_variants(conn, ex.active_variants(settings, conn))  # the agent does this in its next cycle
    assert forward_sample(conn, T0, ["XRP"]) == [1.5, 1.5, -1]  # same rules, so its trades count for the gate
