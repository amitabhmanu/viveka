"""PreToolUse guard for Edit, Write and NotebookEdit.

Blocks (exit 2) any edit to a file listed in registry/FROZEN.json, to the
manifest itself, to anything under data/raw/ or runs/, or to the change
ledger. For allowed edits under registry/, records the file's hash before
the edit so log_change.py can write a complete ledger entry afterwards.
Fails closed: any internal error blocks the edit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402


def main() -> None:
    event = c.read_event()
    root = c.project_root(event)
    tool_input = event.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    key = c.rel_key(path, root)

    reason = c.protection_reason(key, root)
    if reason:
        c.block(
            f"Viveka: blocked {event.get('tool_name', 'edit')} on {path} because {reason}. "
            "Frozen registry files change only through a version bump (`viveka registry bump`); "
            "raw data, runs and the change ledger are never edited. Record the need with /log-decision."
        )

    if c.is_registry_path(key) and event.get("tool_use_id"):
        target = Path(path) if Path(path).is_absolute() else root / path
        snapshot = c.state_path(root, "pending", c.safe_name(event["tool_use_id"]) + ".json")
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(
            json.dumps({"path": c.rel_display(path, root), "sha_before": c.sha256_file(target),
                        "time": c.now_iso()}),
            encoding="utf-8",
        )


if __name__ == "__main__":
    c.run_guard(main)
