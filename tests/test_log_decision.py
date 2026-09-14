import json

from conftest import read_ledger

from viveka.ledger import decision_status


def _seed_change(root, change_id="chg_1", session="s1"):
    with open(root / "ledger" / "changes.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": change_id, "type": "change", "session_id": session}) + "\n")


def test_reason_covers_this_sessions_pending_changes(project, log_decision):
    _seed_change(project, "chg_1", "s1")
    _seed_change(project, "chg_2", "other")
    ledger = project / "ledger" / "changes.jsonl"
    original = ledger.read_bytes()

    result = log_decision(project, "--session", "s1", "--reason", "tighten coverage after census")

    assert result.returncode == 0, result.stderr
    assert ledger.read_bytes().startswith(original)
    reason = read_ledger(project)[-1]
    assert reason["type"] == "reason"
    assert reason["for"] == ["chg_1"]
    assert reason["reason"] == "tighten coverage after census"


def test_resolving_a_decision_appends_and_changes_status(project, log_decision):
    decisions = project / "ledger" / "decisions.md"
    original = decisions.read_bytes()

    result = log_decision(project, "--session", "s1", "--reason", "Use WSL2", "--decision", "D-1", "--resolve")

    assert result.returncode == 0, result.stderr
    assert decisions.read_bytes().startswith(original)
    assert decision_status(project)["D-1"] == ("DECIDED", "Use WSL2")
    assert decision_status(project)["D-2"][0] == "OPEN"


def test_note_without_resolve_keeps_status(project, log_decision):
    result = log_decision(project, "--session", "s1", "--reason", "pricing still unknown", "--decision", "D-6")
    assert result.returncode == 0, result.stderr
    assert decision_status(project)["D-6"] == ("OPEN", "pricing still unknown")


def test_nothing_to_record(project, log_decision):
    result = log_decision(project, "--session", "s1", "--reason", "no changes")
    assert result.returncode == 1


def test_unknown_decision_is_rejected(project, log_decision):
    result = log_decision(project, "--session", "s1", "--reason", "x", "--decision", "D-99")
    assert result.returncode == 2


def test_resolve_requires_a_decision(project, log_decision):
    _seed_change(project)
    assert log_decision(project, "--session", "s1", "--reason", "x", "--resolve").returncode == 2
