"""SessionStart hook: put the project's status into the session's context.

Prints the registry state, change-ledger counts, runs and open decisions.
Claude Code adds stdout from a SessionStart hook to the conversation context.
Never blocks: a failure is reported as a line of context instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402


def main() -> None:
    try:
        event = c.read_event()
    except Exception:  # noqa: BLE001 - context is best effort
        event = {}
    root = c.project_root(event)
    try:
        print(c.status_summary(root))
    except Exception as exc:  # noqa: BLE001
        print(f"Viveka status unavailable ({type(exc).__name__}: {exc}). Run `uv run viveka status`.")


if __name__ == "__main__":
    main()
