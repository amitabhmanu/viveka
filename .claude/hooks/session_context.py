"""SessionStart hook: put the project's status into the session's context.

Prefers the full `viveka status` (registry integrity, ledger integrity, runs),
run without syncing the environment and with a timeout. If that is unavailable
(no project environment, broken install, timeout), falls back to the
standard-library summary in _common.py. Claude Code adds stdout from a
SessionStart hook to the conversation context. Never blocks.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

TIMEOUT_SECONDS = 20


def full_status(root: Path) -> str | None:
    uv = shutil.which("uv")
    if uv is None or not (root / "pyproject.toml").is_file():
        return None
    try:
        result = subprocess.run(
            [uv, "run", "--no-sync", "--project", str(root), "viveka", "status", "--root", str(root)],
            capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = result.stdout.strip()
    return out if result.returncode == 0 and out.startswith("Viveka status") else None


def main() -> None:
    try:
        event = c.read_event()
    except Exception:  # noqa: BLE001 - context is best effort
        event = {}
    root = c.project_root(event)
    try:
        print(full_status(root) or c.status_summary(root))
    except Exception as exc:  # noqa: BLE001
        print(f"Viveka status unavailable ({type(exc).__name__}: {exc}). Run `uv run viveka status`.")


if __name__ == "__main__":
    main()
