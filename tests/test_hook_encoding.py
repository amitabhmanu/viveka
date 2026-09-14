"""Hooks must work when their output streams use a non-UTF-8 code page.

Claude Code pipes hook output. On Windows a piped Python stream defaults to the
ANSI code page, and an encoding error inside a guard would exit 1, which lets
the action through. These tests force such a code page.
"""

import shutil

from conftest import edit_event

CP1252 = {"PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}


def test_session_context_prints_non_latin_text(project, hook):
    decisions = project / "ledger" / "decisions.md"
    with open(decisions, "a", encoding="utf-8") as fh:
        fh.write("- 2026-09-14 · D-9 · OPEN · Thresholds δ and κ\n")
    result = hook("session_context.py", project, {"hook_event_name": "SessionStart"}, extra_env=CP1252)
    assert result.returncode == 0
    assert "Viveka status unavailable" not in result.stdout
    assert "D-9 (Thresholds δ and κ)" in result.stdout


def test_guard_still_blocks_when_the_message_has_unencodable_characters(project, freeze, hook, tmp_path):
    root = tmp_path / "projδ"
    shutil.copytree(project, root)
    freeze(root, ["registry/thresholds.yaml"])
    result = hook("guard_frozen.py", root, edit_event(str(root / "registry" / "thresholds.yaml")), extra_env=CP1252)
    assert result.returncode == 2
    assert "frozen registry version 1" in result.stderr


def test_shell_guard_blocks_with_unencodable_path(project, hook, tmp_path):
    root = tmp_path / "projκ"
    shutil.copytree(project, root)
    event = {"session_id": "s1", "tool_name": "Bash",
             "tool_input": {"command": f"rm {root}/ledger/changes.jsonl"}}
    assert hook("guard_shell.py", root, event, extra_env=CP1252).returncode == 2
