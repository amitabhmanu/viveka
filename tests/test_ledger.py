import json
import subprocess
import sys

import pytest
from conftest import HOOKS, git

from viveka import ledger


def _change(cid: str, session: str = "s1") -> dict:
    return {"id": cid, "type": "change", "time": "t", "session_id": session, "tool": "Edit",
            "path": "registry/instrument.yaml", "sha_before": None, "sha_after": None}


def test_append_validates_and_only_appends(registry_root):
    path = registry_root / "ledger" / "changes.jsonl"
    ledger.append(registry_root, _change("chg_a1"))
    before = path.read_bytes()
    ledger.append(registry_root, _change("chg_b2"))
    assert path.read_bytes().startswith(before)
    with pytest.raises(ledger.LedgerError):
        ledger.append(registry_root, {"id": "chg_c3", "type": "change", "time": "t"})
    with pytest.raises(ledger.LedgerError):
        ledger.append(registry_root, {"id": "x", "type": "gossip", "time": "t"})


def test_verify_finds_duplicates_dangling_reasons_and_bad_lines(registry_root):
    path = registry_root / "ledger" / "changes.jsonl"
    lines = [_change("chg_a1"), _change("chg_a1"),
             {"id": "rsn_1", "type": "reason", "time": "t", "session_id": "s1", "for": ["chg_ff"], "reason": "r"}]
    path.write_bytes("".join(json.dumps(r) + "\n" for r in lines).encode())
    problems = ledger.verify(registry_root)
    assert any("duplicate id chg_a1" in p for p in problems)
    assert any("unknown change chg_ff" in p for p in problems)

    path.write_bytes(b"{not json\n")
    assert "not valid JSON" in ledger.verify(registry_root)[0]


def test_verify_detects_rewritten_committed_lines(git_project):
    ledger.append(git_project, _change("chg_a1"))
    git(git_project, "commit", "-q", "-am", "ledger entry")
    ledger.append(git_project, _change("chg_b2"))
    assert ledger.verify(git_project) == []

    path = git_project / "ledger" / "changes.jsonl"
    path.write_bytes(path.read_bytes().replace(b"chg_a1", b"chg_a9"))
    assert any("rewritten or deleted" in p for p in ledger.verify(git_project))


def test_hook_copy_and_package_agree_on_unreasoned_changes():
    recs = [
        _change("chg_a1", "s1"), _change("chg_b2", "s1"), _change("chg_c3", "s2"),
        {"id": "rsn_1", "type": "reason", "time": "t", "session_id": "s1", "for": ["chg_a1"], "reason": "r"},
    ]
    script = (
        "import json, sys; sys.path.insert(0, sys.argv[1]); import _common as c; "
        "recs = json.load(sys.stdin); "
        "print(json.dumps([c.unreasoned_changes(recs), c.unreasoned_changes(recs, 's1')]))"
    )
    out = subprocess.run([sys.executable, "-c", script, str(HOOKS)], input=json.dumps(recs),
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    assert json.loads(out) == [ledger.unreasoned(recs), ledger.unreasoned(recs, "s1")]
