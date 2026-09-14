"""Shared fixtures: a throwaway Viveka project tree and a runner for hook scripts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOOKS = REPO / ".claude" / "hooks"
LOG_DECISION = REPO / ".claude" / "skills" / "log-decision" / "scripts" / "log_decision.py"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "registry").mkdir(parents=True)
    (root / "ledger").mkdir()
    (root / "runs").mkdir()
    (root / "ledger" / "changes.jsonl").write_text("", encoding="utf-8")
    shutil.copy(REPO / "ledger" / "decisions.md", root / "ledger" / "decisions.md")
    (root / "registry" / "thresholds.yaml").write_text("version: 0\n", encoding="utf-8")
    (root / "registry" / "instrument.yaml").write_text("version: 0\n", encoding="utf-8")
    return root


@pytest.fixture
def freeze():
    def _freeze(root: Path, files: list[str], version: int = 1) -> None:
        manifest = {"version": version, "components": {"test": {"sha256": "sha256:0", "files": files}}}
        (root / "registry" / "FROZEN.json").write_text(json.dumps(manifest), encoding="utf-8")

    return _freeze


@pytest.fixture
def hook():
    def _run(name: str, root: Path, event: dict | None = None, raw: str | None = None,
             extra_env: dict | None = None):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root), **(extra_env or {})}
        data = raw if raw is not None else json.dumps(event or {})
        return subprocess.run(
            [sys.executable, str(HOOKS / name)],
            input=data, capture_output=True, text=True, encoding="utf-8", env=env, check=False,
        )

    return _run


@pytest.fixture
def log_decision():
    def _run(root: Path, *args: str):
        return subprocess.run(
            [sys.executable, str(LOG_DECISION), "--root", str(root), *args],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )

    return _run


def edit_event(path: str, tool: str = "Edit", tool_use_id: str = "toolu_1", session: str = "s1") -> dict:
    return {
        "session_id": session,
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_use_id": tool_use_id,
        "tool_input": {"file_path": path},
    }


def shell_event(command: str, tool: str = "PowerShell") -> dict:
    return {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": tool,
            "tool_input": {"command": command}}


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read_ledger(root: Path) -> list[dict]:
    text = (root / "ledger" / "changes.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]
