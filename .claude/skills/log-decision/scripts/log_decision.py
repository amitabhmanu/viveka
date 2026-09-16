"""Append a reason record and/or a decision line to Viveka's ledgers.

Both ledgers are append-only: this script never rewrites an existing line.

* A reason record covers every change record from the given session that has
  no reason yet: {"id", "type": "reason", "time", "session_id", "for", "reason", "decision"}.
  It is validated against the ledger record schema before it is written.
* A decision line is appended to ledger/decisions.md. With --resolve its status
  is DECIDED; without it the decision keeps its current status and the line is a note.
  With --open, --decision names a new decision, registered OPEN and titled by --reason.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

from viveka import ledger
from viveka.paths import DECISIONS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, help="Claude Code session id")
    parser.add_argument("--reason", required=True, help="One-line reason")
    parser.add_argument("--decision", help="Decision id such as D-1")
    parser.add_argument("--resolve", action="store_true", help="Mark the decision DECIDED")
    parser.add_argument("--open", action="store_true",
                        help="Register --decision as a new OPEN decision titled by --reason")
    parser.add_argument("--root", type=Path, help="Project root (default: CLAUDE_PROJECT_DIR or the script's project)")
    args = parser.parse_args(argv)

    default_root = os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[4]
    root = Path(args.root or default_root).resolve()
    reason = " ".join(args.reason.split())
    if not reason:
        parser.error("--reason must not be empty")
    if (args.resolve or args.open) and not args.decision:
        parser.error("--resolve and --open require --decision")
    if args.resolve and args.open:
        parser.error("--open registers a decision as OPEN; resolve it with a later call")

    decisions = ledger.decision_status(root)
    if args.open:
        if not re.fullmatch(r"D-\d+", args.decision):
            parser.error(f"decision ids look like D-9, not {args.decision!r}")
        if args.decision in decisions:
            parser.error(f"decision {args.decision} already exists; add a note or resolve it instead")
    elif args.decision and args.decision not in decisions:
        parser.error(f"unknown decision {args.decision!r}; known: {', '.join(sorted(decisions)) or 'none'}")

    pending = ledger.unreasoned(ledger.records(root), args.session)
    if not pending and not args.decision:
        print("Nothing to record: this session has no registry changes without a reason, and no decision was given.")
        return 1

    if pending:
        ledger.append(root, {
            "id": ledger.new_id("rsn"),
            "type": "reason",
            "time": ledger.now_iso(),
            "session_id": args.session,
            "for": pending,
            "reason": reason,
            "decision": args.decision,
        })
        print(f"Recorded a reason for {len(pending)} change(s): {', '.join(pending)}")

    if args.decision:
        status = "DECIDED" if args.resolve else "OPEN" if args.open else decisions[args.decision][0]
        path = root / DECISIONS
        existing = path.read_bytes()
        prefix = b"" if existing.endswith(b"\n") or not existing else b"\n"
        line = f"- {dt.datetime.now(dt.UTC).date().isoformat()} · {args.decision} · {status} · {reason}\n"
        with open(path, "ab") as fh:
            fh.write(prefix + line.encode("utf-8"))
        print(f"Appended to {DECISIONS}: {line.strip()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
