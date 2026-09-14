"""Thin wrapper around the git command line, used for provenance and registry tags."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# Pipeline output directories: a new run or derived artefact must not make the
# tree count as dirty for the next run.
_DIRTY_EXCLUDES = (":(exclude)runs", ":(exclude)data")


class GitError(RuntimeError):
    pass


def available() -> bool:
    return shutil.which("git") is not None


def _git(root: Path, *args: str, check: bool = True, binary: bool = False) -> subprocess.CompletedProcess:
    if not available():
        raise GitError("git is not installed")
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=not binary,
        encoding=None if binary else "utf-8",
        check=False,
    )
    if check and result.returncode != 0:
        stderr = result.stderr if isinstance(result.stderr, str) else result.stderr.decode("utf-8", "replace")
        raise GitError(f"git {' '.join(args)} failed: {stderr.strip()}")
    return result


def is_repo(root: Path) -> bool:
    if not available():
        return False
    return _git(root, "rev-parse", "--is-inside-work-tree", check=False).returncode == 0


def head_commit(root: Path) -> str | None:
    result = _git(root, "rev-parse", "--verify", "-q", "HEAD", check=False)
    return result.stdout.strip() or None if result.returncode == 0 else None


def is_dirty(root: Path) -> bool:
    """Uncommitted or untracked changes, ignoring pipeline output under runs/ and data/."""
    result = _git(root, "status", "--porcelain", "--", ".", *_DIRTY_EXCLUDES)
    return bool(result.stdout.strip())


def tag_exists(root: Path, tag: str) -> bool:
    return _git(root, "rev-parse", "-q", "--verify", f"refs/tags/{tag}", check=False).returncode == 0


def commit_paths(root: Path, message: str, paths: list[str]) -> str:
    """Stage and commit only ``paths`` (other staged work is left alone). Returns the new commit."""
    _git(root, "add", "--", *paths)
    _git(root, "commit", "-q", "-m", message, "--", *paths)
    commit = head_commit(root)
    if commit is None:
        raise GitError("commit did not produce a HEAD")
    return commit


def create_tag(root: Path, tag: str, message: str) -> None:
    _git(root, "tag", "-a", tag, "-m", message)


def show_file(root: Path, rev: str, path: str) -> bytes | None:
    """Bytes of ``path`` at ``rev``, or None if it does not exist there."""
    result = _git(root, "show", f"{rev}:{path}", check=False, binary=True)
    return result.stdout if result.returncode == 0 else None
