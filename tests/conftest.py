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
    """Write a format-1 FROZEN.json directly (hook tests); real freezes use viveka.registry.freeze."""

    def _freeze(root: Path, files: list[str], version: int = 1, name: str = "thresholds") -> None:
        from viveka.hashing import tree_hash

        file_sha = {f: sha(root / f) if (root / f).is_file() else "sha256:" + "0" * 64 for f in files}
        manifest = {
            "format": 1,
            "version": version,
            "components": {name: {"sha256": tree_hash(file_sha), "files": files, "file_sha256": file_sha,
                                  "frozen_in": version, "frozen_at": "2026-09-14T00:00:00+00:00",
                                  "ledger_id": "frz_0"}},
        }
        (root / "registry" / "FROZEN.json").write_text(json.dumps(manifest), encoding="utf-8")

    return _freeze


def _copy_registry(root: Path) -> Path:
    # The copy starts unfrozen: tests freeze what they need, independent of the real registry version.
    shutil.copytree(REPO / "registry", root / "registry", ignore=shutil.ignore_patterns("FROZEN.json"))
    (root / "ledger").mkdir(parents=True)
    (root / "ledger" / "changes.jsonl").write_bytes(b"")
    shutil.copy(REPO / "ledger" / "decisions.md", root / "ledger" / "decisions.md")
    (root / "runs").mkdir()
    # Run manifests travel with the registry, so source_run references in the copy still resolve.
    for manifest in (REPO / "runs").glob("*/manifest.json"):
        (root / "runs" / manifest.parent.name).mkdir()
        shutil.copy(manifest, root / "runs" / manifest.parent.name / "manifest.json")
    shutil.copy(REPO / ".gitattributes", root / ".gitattributes")
    return root


@pytest.fixture
def registry_root(tmp_path: Path) -> Path:
    """A copy of the real registry and ledger outside git."""
    return _copy_registry(tmp_path / "reg")


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                            encoding="utf-8", check=True)
    return result.stdout


@pytest.fixture
def git_project(tmp_path: Path) -> Path:
    """A copy of the real registry and ledger in a fresh git repository with one commit."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    root = _copy_registry(tmp_path / "repo")
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Viveka Test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "core.autocrlf", "false")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "config", "tag.gpgsign", "false")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "initial")
    return root


def write_lf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


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
