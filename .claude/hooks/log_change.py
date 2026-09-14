"""PostToolUse hook for Edit, Write and NotebookEdit.

Appends one change record to ledger/changes.jsonl for every edit under
registry/, with the file hash before (captured by guard_frozen.py) and after.
The record has no reason; require_reason.py asks for one before the session
stops, and /log-decision supplies it as a separate appended record.
If logging fails, exits 2 so the error is shown to Claude: an unlogged
registry change breaks principle H6.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402


def main() -> None:
    event = c.read_event()
    root = c.project_root(event)
    tool_input = event.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    key = c.rel_key(path, root)
    if not c.is_registry_path(key):
        return

    sha_before = None
    snapshot = None
    if event.get("tool_use_id"):
        snapshot = c.state_path(root, "pending", c.safe_name(event["tool_use_id"]) + ".json")
        if snapshot.exists():
            sha_before = json.loads(snapshot.read_text(encoding="utf-8")).get("sha_before")

    target = Path(path) if Path(path).is_absolute() else root / path
    c.append_jsonl(
        root / c.LEDGER,
        {
            "id": "chg_" + uuid.uuid4().hex,
            "type": "change",
            "time": c.now_iso(),
            "session_id": event.get("session_id"),
            "tool": event.get("tool_name"),
            "path": c.rel_display(path, root),
            "sha_before": sha_before,
            "sha_after": c.sha256_file(target),
        },
    )
    if snapshot is not None and snapshot.exists():
        snapshot.unlink()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"Viveka: registry change was NOT logged ({type(exc).__name__}: {exc}). "
              "Record it with /log-decision and fix the hook.", file=sys.stderr)
        sys.exit(2)
