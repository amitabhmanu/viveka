import pytest


def _event(tool: str, **tool_input) -> dict:
    return {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}


@pytest.mark.parametrize(
    "event",
    [
        _event("Read", file_path="registry/predictions/pilot.yaml"),
        _event("Grep", pattern="kill", path="registry/predictions"),
        _event("Glob", pattern="registry/predictions/**/*.yaml"),
    ],
)
def test_blocks_predictions(project, hook, event):
    assert hook("guard_predictions.py", project, event).returncode == 2


@pytest.mark.parametrize(
    "event",
    [
        _event("Read", file_path="registry/thresholds.yaml"),
        _event("Grep", pattern="delta", path="src"),
        _event("Glob", pattern="registry/prompts/*.md"),
    ],
)
def test_allows_everything_else(project, hook, event):
    assert hook("guard_predictions.py", project, event).returncode == 0
