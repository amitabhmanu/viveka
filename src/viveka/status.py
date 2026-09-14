"""Read-only project status for `viveka status` and session context."""

from __future__ import annotations

from pathlib import Path

from viveka import ledger
from viveka.provenance import recent_runs
from viveka.registry import components as comp
from viveka.registry import manifest as mf
from viveka.registry import verify as vf
from viveka.registry.errors import RegistryError
from viveka.registry.thresholds import PARAMETERS, load_thresholds


def _registry_lines(root: Path) -> list[str]:
    try:
        manifest = mf.read(root)
    except RegistryError as exc:
        return [f"- registry: FROZEN.json unreadable ({exc})"]
    frozen = mf.frozen_names(manifest)
    drafts = sorted(set(comp.discover(root)) - set(frozen))
    if not frozen:
        lines = ["- registry: no frozen registry (drafts only)"]
    else:
        try:
            mismatches = vf.check(root)
        except RegistryError as exc:
            mismatches = {"manifest": [str(exc)]}
        state = "all verify" if not mismatches else "MISMATCH in " + ", ".join(sorted(mismatches))
        lines = [f"- registry: version {manifest['version']}; frozen: {', '.join(frozen)} ({state})"]
    lines.append(f"- draft components: {', '.join(drafts) if drafts else 'none'}")
    try:
        unset = load_thresholds(root).unset()
        lines.append(f"- thresholds: {len(PARAMETERS) - len(unset)} of {len(PARAMETERS)} set")
    except (RegistryError, OSError) as exc:
        lines.append(f"- thresholds: unreadable ({exc})")
    return lines


def _ledger_lines(root: Path) -> list[str]:
    try:
        recs = ledger.records(root)
    except ledger.LedgerError as exc:
        return [f"- change ledger: unreadable ({exc})"]
    problems = ledger.verify(root)
    integrity = "intact" if not problems else f"{len(problems)} problem(s), run `viveka ledger verify`"
    pending = len(ledger.unreasoned(recs))
    return [f"- change ledger: {len(recs)} records, {pending} changes without a reason; {integrity}"]


def _run_lines(root: Path) -> list[str]:
    runs = recent_runs(root)
    runs_dir = root / "runs"
    count = sum(1 for p in runs_dir.iterdir() if p.is_dir()) if runs_dir.is_dir() else 0
    lines = [f"- runs: {count}"]
    lines.extend(f"  - {r['run_id']} ({r['fold']}, {r['status']})" for r in runs)
    return lines


def _decision_lines(root: Path) -> list[str]:
    decisions = ledger.decision_status(root)
    open_items = [
        f"{did} ({text})"
        for did, (st, text) in sorted(decisions.items(), key=lambda kv: int(kv[0][2:]))
        if st == "OPEN"
    ]
    return [f"- open decisions: {len(open_items)}", *(f"  - {item}" for item in open_items)]


def status_summary(root: Path) -> str:
    lines = ["Viveka status"]
    lines += _registry_lines(root)
    lines += _ledger_lines(root)
    lines += _run_lines(root)
    lines += _decision_lines(root)
    return "\n".join(lines)
