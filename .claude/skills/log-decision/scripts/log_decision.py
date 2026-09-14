"""Append a reason record and/or a decision line to Viveka's ledgers.

Both ledgers are append-only: this script never rewrites an existing line.

* A reason record covers every change record from the given session that has
  no reason yet: {"id", "type": "reason", "time", "session_id", "for", "reason", "decision"}.
* A decision line is appended to ledger/decisions.md. With --resolve its status
  is DECIDED; without it the decision keeps its current status and the line is a note.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import uuid
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parents[3] / "hooks"
sys.path.insert(0, str(HOOKS_DIR))
import _common as c  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, help="Claude Code session id")
    parser.add_argument("--reason", required=True, help="One-line reason")
    parser.add_argument("--decision", help="Decision id such as D-1")
    parser.add_argument("--resolve", action="store_true", help="Mark the decision DECIDED")
    parser.add_argument("--root", type=Path, help="Project root (default: CLAUDE_PROJECT_DIR or the script's project)")
    args = parser.parse_args(argv)

    root = (args.root or Path(os.environ.get("CLAUDE_PROJECT_DIR") or HOOKS_DIR.parents[1])).resolve()
    reason = " ".join(args.reason.split())
    if not reason:
        parser.error("--reason must not be empty")
    if args.resolve and not args.decision:
        parser.error("--resolve requires --decision")

    decisions = c.decision_status(root)
    if args.decision and args.decision not in decisions:
        parser.error(f"unknown decision {args.decision!r}; known: {', '.join(sorted(decisions)) or 'none'}")

    pending = c.unreasoned_changes(c.ledger_records(root), args.session)
    if not pending and not args.decision:
        print("Nothing to record: this session has no registry changes without a reason, and no decision was given.")
        return 1

    if pending:
        c.append_jsonl(
            root / c.LEDGER,
            {
                "id": "rsn_" + uuid.uuid4().hex,
                "type": "reason",
                "time": c.now_iso(),
                "session_id": args.session,
                "for": pending,
                "reason": reason,
                "decision": args.decision,
            },
        )
        print(f"Recorded a reason for {len(pending)} change(s): {', '.join(pending)}")

    if args.decision:
        status = "DECIDED" if args.resolve else decisions[args.decision][0]
        path = root / c.DECISIONS
        existing = path.read_bytes()
        prefix = b"" if existing.endswith(b"\n") or not existing else b"\n"
        today = dt.datetime.now(dt.UTC).date().isoformat()
        line = f"- {today} · {args.decision} · {status} · {reason}\n"
        with open(path, "ab") as fh:
            fh.write(prefix + line.encode("utf-8"))
        print(f"Appended to {c.DECISIONS}: {line.strip()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
