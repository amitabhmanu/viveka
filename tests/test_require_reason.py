import json

from conftest import read_ledger


def _stop(session: str = "s1") -> dict:
    return {"session_id": session, "hook_event_name": "Stop"}


def _seed_change(root, change_id: str = "chg_1", session: str = "s1") -> None:
    with open(root / "ledger" / "changes.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": change_id, "type": "change", "session_id": session,
                             "path": "registry/instrument.yaml"}) + "\n")


def test_allows_stop_without_changes(project, hook):
    assert hook("require_reason.py", project, _stop()).returncode == 0


def test_blocks_stop_while_a_change_lacks_a_reason(project, hook):
    _seed_change(project)
    result = hook("require_reason.py", project, _stop())
    assert result.returncode == 2
    assert "/log-decision" in result.stderr
    assert "chg_1" in result.stderr


def test_allows_stop_once_a_reason_is_recorded(project, hook):
    _seed_change(project)
    with open(project / "ledger" / "changes.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "rsn_1", "type": "reason", "session_id": "s1", "for": ["chg_1"]}) + "\n")
    assert hook("require_reason.py", project, _stop()).returncode == 0


def test_other_sessions_do_not_block(project, hook):
    _seed_change(project, session="someone-else")
    assert hook("require_reason.py", project, _stop("s1")).returncode == 0


def test_blocks_at_most_twice_for_the_same_pending_set(project, hook):
    _seed_change(project)
    codes = [hook("require_reason.py", project, _stop()).returncode for _ in range(3)]
    assert codes == [2, 2, 0]
    assert len(read_ledger(project)) == 1


def test_a_new_pending_change_resets_the_count(project, hook):
    _seed_change(project, "chg_1")
    hook("require_reason.py", project, _stop())
    hook("require_reason.py", project, _stop())
    _seed_change(project, "chg_2")
    assert hook("require_reason.py", project, _stop()).returncode == 2


def test_fails_open_on_malformed_input(project, hook):
    assert hook("require_reason.py", project, raw="nope").returncode == 0
