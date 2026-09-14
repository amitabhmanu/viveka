from conftest import edit_event, read_ledger, sha


def test_records_hash_before_and_after(project, hook):
    target = project / "registry" / "instrument.yaml"
    before = sha(target)
    event = edit_event(str(target), tool_use_id="toolu_77", session="sess-A")

    assert hook("guard_frozen.py", project, event).returncode == 0
    target.write_text("version: 1\n", encoding="utf-8")
    event["hook_event_name"] = "PostToolUse"
    result = hook("log_change.py", project, event)

    assert result.returncode == 0, result.stderr
    [record] = read_ledger(project)
    assert record["type"] == "change"
    assert record["path"] == "registry/instrument.yaml"
    assert record["session_id"] == "sess-A"
    assert record["sha_before"] == before
    assert record["sha_after"] == sha(target)
    assert record["id"].startswith("chg_")
    assert not (project / ".claude" / "state" / "pending" / "toolu_77.json").exists()


def test_new_registry_file_has_no_hash_before(project, hook):
    target = project / "registry" / "events" / "claim.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("events: []\n", encoding="utf-8")
    result = hook("log_change.py", project, edit_event(str(target), tool="Write", tool_use_id="t2"))
    assert result.returncode == 0, result.stderr
    [record] = read_ledger(project)
    assert record["sha_before"] is None
    assert record["sha_after"] == sha(target)


def test_ignores_paths_outside_registry(project, hook):
    assert hook("log_change.py", project, edit_event(str(project / "src" / "x.py"))).returncode == 0
    assert read_ledger(project) == []


def test_appends_without_rewriting(project, hook):
    ledger = project / "ledger" / "changes.jsonl"
    ledger.write_text('{"id": "chg_old", "type": "change", "session_id": "s0"}\n', encoding="utf-8")
    original = ledger.read_bytes()
    hook("log_change.py", project, edit_event(str(project / "registry" / "instrument.yaml"), tool_use_id="t3"))
    assert ledger.read_bytes().startswith(original)
    assert len(read_ledger(project)) == 2
