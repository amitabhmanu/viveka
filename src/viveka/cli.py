"""Viveka command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from viveka import ledger
from viveka.paths import find_root
from viveka.provenance import ProvenanceError, verify_run
from viveka.registry import manifest as mf
from viveka.registry import verify as vf
from viveka.registry.errors import RegistryError
from viveka.registry.freeze import bump, freeze
from viveka.registry.validate import validate
from viveka.status import status_summary


def _short(sha: str) -> str:
    return sha.removeprefix("sha256:")[:12]


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=None, help="Project root (default: search upwards)")

    parser = argparse.ArgumentParser(prog="viveka", description="Viveka research harness")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", parents=[common], help="Registry, ledger, run and decision status (read-only)")

    registry = sub.add_parser("registry", help="Validate, freeze, verify or bump registry components")
    rsub = registry.add_subparsers(dest="action", required=True)
    p = rsub.add_parser("validate", parents=[common], help="Check registry files (read-only)")
    p.add_argument("components", nargs="*")
    p = rsub.add_parser("verify", parents=[common], help="Check frozen components against FROZEN.json (read-only)")
    p.add_argument("components", nargs="*")
    p = rsub.add_parser("freeze", parents=[common], help="Freeze components, record, commit and tag")
    p.add_argument("components", nargs="+")
    p.add_argument("--reason", required=True)
    p.add_argument("--no-git", action="store_true", help="Development only: do not commit or tag")
    p = rsub.add_parser("bump", parents=[common], help="Return frozen components to draft")
    p.add_argument("components", nargs="+")
    p.add_argument("--reason", required=True)
    p.add_argument("--prompted-by", required=True, help="The run or result that prompted the change")

    led = sub.add_parser("ledger", help="Change-ledger tools")
    lsub = led.add_subparsers(dest="action", required=True)
    lsub.add_parser("verify", parents=[common], help="Check the change ledger's integrity (read-only)")

    p = sub.add_parser("verify", parents=[common], help="Check a run's recorded inputs and outputs (read-only)")
    p.add_argument("run_id")

    from viveka.corpus.commands import add_parsers as add_corpus_parsers
    from viveka.sim.commands import add_parser as add_sim_parser
    from viveka.social.commands import add_parser as add_social_parser

    add_sim_parser(sub, common)
    add_corpus_parsers(sub, common)
    add_social_parser(sub, common)

    p = sub.add_parser("code", parents=[common],
                       help="S8: direction (T7) or stance (T1) labels for one commitment, by the qualified pool")
    p.add_argument("--task", required=True, choices=["T7", "T1"])
    p.add_argument("--field", required=True)
    p.add_argument("--commitment", required=True)
    p.add_argument("--fold", required=True)
    p.add_argument("--max-live-calls", type=int, help="Per coder; archived answers still replay")
    p.add_argument("--dry-run", action="store_true", help="Count items and calls; no coder is called")
    return parser


def _cmd_registry(args: argparse.Namespace, root: Path) -> int:
    if args.action == "validate":
        problems = validate(root, args.components or None)
        if problems:
            print("registry validation failed:")
            print("\n".join(f"  - {p}" for p in problems))
            return 1
        print("registry valid")
        return 0

    if args.action == "verify":
        frozen = mf.read(root)["components"]
        not_frozen = [n for n in args.components if n not in frozen]
        mismatches = vf.check(root, args.components or None)
        for name in not_frozen:
            print(f"  - {name}: not frozen")
        for name, issues in sorted(mismatches.items()):
            print(f"  - {name}: {'; '.join(issues)}")
        if not_frozen or mismatches:
            return 1
        checked = args.components or sorted(frozen)
        print(f"{len(checked)} frozen component(s) verify" if checked else "no frozen components")
        return 0

    if args.action == "freeze":
        result = freeze(root, args.components, args.reason, use_git=not args.no_git)
        print(f"froze registry version {result.version}:")
        for name, sha in result.components.items():
            print(f"  - {name} {_short(sha)}")
        print(f"ledger {result.ledger_id}" + (f"; tag {result.tag}" if result.tag else "; no git"))
        return 0

    result = bump(root, args.components, args.reason, args.prompted_by)
    print(f"returned to draft from version {result.from_version}: {', '.join(result.components)}")
    if result.cascaded:
        print(f"cascaded (downstream): {', '.join(result.cascaded)}")
    print(f"ledger {result.ledger_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # registry text includes δ, κ, ℓ; cp1252 consoles can't encode them
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = _parser().parse_args(argv)

    try:
        root = args.root.resolve() if args.root else find_root(Path.cwd())
    except FileNotFoundError as exc:
        print(f"viveka: {exc}", file=sys.stderr)
        return 1

    try:
        if args.command == "status":
            print(status_summary(root))
            return 0
        if args.command == "registry":
            return _cmd_registry(args, root)
        if args.command == "ledger":
            problems = ledger.verify(root)
            if problems:
                print("ledger problems:")
                print("\n".join(f"  - {p}" for p in problems))
                return 1
            print(f"ledger intact ({len(ledger.records(root))} records)")
            return 0
        if args.command == "sim":
            from viveka.sim.commands import run as run_sim

            return run_sim(args, root)
        if args.command in ("social", "eligibility"):
            from viveka.social.commands import run as run_social

            return run_social(args, root)
        if args.command in ("corpus", "case", "field", "census"):
            from viveka.corpus.commands import run as run_corpus

            return run_corpus(args, root)
        if args.command == "code":
            from viveka.cases import CaseError
            from viveka.coders.coding import CodingRefused, run_coding

            try:
                run_coding(root, args.task, args.field, args.commitment, args.fold,
                           max_live_calls=args.max_live_calls, dry_run=args.dry_run)
            except (CodingRefused, CaseError) as exc:
                print(f"viveka: {exc}")
                return 1
            return 0
        if args.command == "verify":
            problems = verify_run(root, args.run_id)
            if problems:
                print(f"run {args.run_id} does not verify:")
                print("\n".join(f"  - {p}" for p in problems))
                return 1
            print(f"run {args.run_id} verifies")
            return 0
    except (RegistryError, ledger.LedgerError, ProvenanceError) as exc:
        print(f"viveka: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
