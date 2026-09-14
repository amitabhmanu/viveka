"""Viveka command line. Milestone M0 provides `status` only."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from viveka.status import find_root, status_summary


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # registry text includes δ, κ, ℓ; cp1252 consoles can't encode them
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="viveka", description="Viveka research harness")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="Show registry, ledger, run and decision status (read-only)")
    status.add_argument("--root", type=Path, default=None, help="Project root (default: search upwards)")

    args = parser.parse_args(argv)

    if args.command == "status":
        try:
            root = args.root.resolve() if args.root else find_root(Path.cwd())
        except FileNotFoundError as exc:
            print(f"viveka: {exc}", file=sys.stderr)
            return 1
        print(status_summary(root))
        return 0

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
