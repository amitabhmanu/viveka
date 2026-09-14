"""Read-only project status.

M0 stand-in for the registry tooling that arrives in M1. The same summary is
produced by `.claude/hooks/_common.py` for session context; the hooks keep
their own copy because they must not depend on the project environment.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

LEDGER = "ledger/changes.jsonl"
DECISIONS = "ledger/decisions.md"
FROZEN = "registry/FROZEN.json"

_DECISION_LINE = re.compile(r"^- (\S+) · (D-\d+) · ([A-Z]+) · (.*)$")


def find_root(start: Path) -> Path:
    """Nearest directory at or above ``start`` that contains a Viveka registry."""
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / "registry").is_dir() and (candidate / "pyproject.toml").is_file():
            return candidate
    raise FileNotFoundError(f"no Viveka project found at or above {start}")


def ledger_records(root: Path) -> list[dict]:
    path = root / LEDGER
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def unreasoned_changes(records: list[dict]) -> list[str]:
    covered = {cid for r in records if r.get("type") == "reason" for cid in r.get("for", [])}
    return [r["id"] for r in records if r.get("type") == "change" and r.get("id") not in covered]


def decision_status(root: Path) -> dict[str, tuple[str, str]]:
    path = root / DECISIONS
    status: dict[str, tuple[str, str]] = {}
    if not path.exists():
        return status
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _DECISION_LINE.match(line.strip())
        if m:
            _, did, st, text = m.groups()
            status[did] = (st, text)
    return status


def status_summary(root: Path) -> str:
    lines = ["Viveka status"]
    manifest_path = root / FROZEN
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        comps = ", ".join(sorted(manifest.get("components", {}))) or "none"
        lines.append(f"- registry: frozen version {manifest.get('version')} (components: {comps})")
    else:
        lines.append("- registry: no frozen registry (drafts only)")
    records = ledger_records(root)
    lines.append(
        f"- change ledger: {len(records)} records, {len(unreasoned_changes(records))} changes without a reason"
    )
    runs_dir = root / "runs"
    run_count = sum(1 for p in runs_dir.iterdir() if p.is_dir()) if runs_dir.exists() else 0
    lines.append(f"- runs: {run_count}")
    decisions = decision_status(root)
    open_items = [
        f"{did} ({text})"
        for did, (st, text) in sorted(decisions.items(), key=lambda kv: int(kv[0][2:]))
        if st == "OPEN"
    ]
    lines.append(f"- open decisions: {len(open_items)}")
    lines.extend(f"  - {item}" for item in open_items)
    return "\n".join(lines)
