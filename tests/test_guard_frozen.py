import json

import pytest
from conftest import edit_event, sha


def test_blocks_frozen_file(project, freeze, hook):
    freeze(project, ["registry/thresholds.yaml"])
    result = hook("guard_frozen.py", project, edit_event(str(project / "registry" / "thresholds.yaml")))
    assert result.returncode == 2
    assert "frozen registry version 1" in result.stderr


def test_blocks_the_frozen_manifest_itself(project, freeze, hook):
    freeze(project, ["registry/thresholds.yaml"])
    result = hook("guard_frozen.py", project, edit_event("registry/FROZEN.json", tool="Write"))
    assert result.returncode == 2


@pytest.mark.parametrize("relpath", ["data/raw/source.json", "runs/r1/manifest.json", "ledger/changes.jsonl"])
def test_blocks_immutable_locations(project, hook, relpath):
    result = hook("guard_frozen.py", project, edit_event(str(project / relpath), tool="Write"))
    assert result.returncode == 2


def test_allows_registry_draft_and_records_hash_before(project, hook):
    target = project / "registry" / "instrument.yaml"
    result = hook("guard_frozen.py", project, edit_event(str(target), tool_use_id="toolu_abc"))
    assert result.returncode == 0, result.stderr
    snapshot = project / ".claude" / "state" / "pending" / "toolu_abc.json"
    assert json.loads(snapshot.read_text(encoding="utf-8"))["sha_before"] == sha(target)


def test_allows_paths_outside_registry_without_snapshot(project, hook):
    result = hook("guard_frozen.py", project, edit_event(str(project / "src" / "module.py"), tool_use_id="t9"))
    assert result.returncode == 0
    assert not (project / ".claude" / "state" / "pending" / "t9.json").exists()


def test_allows_paths_outside_the_project(project, hook, tmp_path):
    result = hook("guard_frozen.py", project, edit_event(str(tmp_path / "elsewhere.txt")))
    assert result.returncode == 0


def test_case_and_separator_variants_are_the_same_file(project, freeze, hook):
    freeze(project, ["registry/thresholds.yaml"])
    variant = str(project) + "\\REGISTRY\\Thresholds.YAML"
    result = hook("guard_frozen.py", project, edit_event(variant))
    assert result.returncode == 2


def test_notebook_path_is_checked(project, hook):
    event = edit_event("", tool="NotebookEdit")
    event["tool_input"] = {"notebook_path": str(project / "runs" / "analysis.ipynb")}
    assert hook("guard_frozen.py", project, event).returncode == 2


def test_fails_closed_on_malformed_input(project, hook):
    result = hook("guard_frozen.py", project, raw="this is not json")
    assert result.returncode == 2
    assert "failed closed" in result.stderr


def test_fails_closed_on_malformed_manifest(project, hook):
    (project / "registry" / "FROZEN.json").write_text("{broken", encoding="utf-8")
    result = hook("guard_frozen.py", project, edit_event(str(project / "registry" / "instrument.yaml")))
    assert result.returncode == 2
