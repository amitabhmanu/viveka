"""Repository layout: well-known paths, and locating the project root."""

from __future__ import annotations

import os
from pathlib import Path

REGISTRY = "registry"
FROZEN = "registry/FROZEN.json"
LEDGER = "ledger/changes.jsonl"
DECISIONS = "ledger/decisions.md"
RUNS = "runs"
DERIVED = "data/derived"


def find_root(start: Path) -> Path:
    """Nearest directory at or above ``start`` that contains a Viveka registry."""
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / REGISTRY).is_dir() and (candidate / "pyproject.toml").is_file():
            return candidate
    raise FileNotFoundError(f"no Viveka project found at or above {start}")


def rel_posix(path: Path, root: Path) -> str:
    """Repo-relative POSIX path, e.g. ``registry/thresholds.yaml``."""
    return os.path.relpath(path.resolve(), root.resolve()).replace("\\", "/")
