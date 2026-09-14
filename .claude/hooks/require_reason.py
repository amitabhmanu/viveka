"""Stop hook: registry changes need a reason before the session finishes.

If this session made registry changes that no reason record covers, blocks the
stop (exit 2) and asks for /log-decision. To avoid an endless loop it blocks at
most MAX_BLOCKS times for the same set of pending changes, then lets the stop
through with a warning; the changes stay flagged in `viveka status`.

Unlike the guards this hook fails open: blocking every stop because the hook
itself is broken would trap the session, and nothing is lost by allowing it.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

MAX_BLOCKS = 2


def main() -> None:
    event = c.read_event()
    root = c.project_root(event)
    session_id = event.get("session_id")
    pending = c.unreasoned_changes(c.ledger_records(root), session_id)

    state_file = c.state_path(root, "stop_blocks.json")
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    key = c.safe_name(session_id)

    if not pending:
        if key in state:
            del state[key]
            state_file.write_text(json.dumps(state), encoding="utf-8")
        return

    fingerprint = hashlib.sha256("\n".join(sorted(pending)).encode()).hexdigest()
    entry = state.get(key) or {}
    count = entry.get("count", 0) if entry.get("fingerprint") == fingerprint else 0

    if count >= MAX_BLOCKS:
        print(json.dumps({"systemMessage": f"Viveka: {len(pending)} registry change(s) from this session "
                                           "still have no reason. They remain flagged in `viveka status`."}))
        return

    state[key] = {"fingerprint": fingerprint, "count": count + 1}
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state), encoding="utf-8")
    c.block(
        f"Viveka: this session changed the registry ({len(pending)} change(s): {', '.join(pending)}) "
        "without recording why. Run /log-decision with the reason, and the result that prompted the "
        "change, before finishing (principle H6)."
    )


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - fail open, see module docstring
        print(json.dumps({"systemMessage": f"Viveka: require_reason hook error ({type(exc).__name__}: {exc})."}))
        sys.exit(0)
