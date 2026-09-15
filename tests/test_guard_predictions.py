import json
import os
import subprocess
import sys

import pytest
from conftest import HOOKS


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


def test_corpus_engineer_variant_also_blocks_prompts(project):
    def run(event, *args):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
        return subprocess.run([sys.executable, str(HOOKS / "guard_predictions.py"), *args], input=json.dumps(event),
                              capture_output=True, text=True, encoding="utf-8", env=env, check=False).returncode

    prompts = _event("Read", file_path="registry/prompts/stance.md")
    assert run(prompts, "--also-prompts") == 2
    assert run(_event("Glob", pattern="registry/predictions/*.yaml"), "--also-prompts") == 2
    assert run(_event("Read", file_path="registry/corpus.yaml"), "--also-prompts") == 0
    assert run(prompts) == 0
