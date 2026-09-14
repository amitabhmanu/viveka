"""Shared helpers for Viveka's Claude Code hooks.

Standard library only: hooks must keep working even when the project
environment is broken. Guards must fail closed, so callers wrap their
entry point in ``run_guard``.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

LEDGER = "ledger/changes.jsonl"
DECISIONS = "ledger/decisions.md"
FROZEN = "registry/FROZEN.json"
THRESHOLDS = "registry/thresholds.yaml"
STATE_DIR = ".claude/state"

STATIC_PROTECTED_PREFIXES = ("data/raw/", "runs/")
STATIC_PROTECTED_FILES = (LEDGER,)

_DECISION_LINE = re.compile(r"^- (\S+) · (D-\d+) · ([A-Z]+) · (.*)$")


# ---------------------------------------------------------------- input / output


def read_event() -> dict:
    event = json.loads(sys.stdin.read())
    if not isinstance(event, dict):
        raise ValueError("hook input is not a JSON object")
    return event


def block(message: str) -> None:
    """Block the tool call or stop: exit code 2 with the reason on stderr."""
    print(message, file=sys.stderr)
    sys.exit(2)


def run_guard(main) -> None:
    """Run a guard so that any unexpected error blocks instead of allowing."""
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - failing closed is the point
        block(f"Viveka guard failed closed ({type(exc).__name__}: {exc}). "
              "Fix the hook or its input before retrying.")


# ---------------------------------------------------------------- paths


def project_root(event: dict | None = None) -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    if event and event.get("cwd"):
        return Path(event["cwd"]).resolve()
    return Path.cwd().resolve()


def rel_key(path_str: str, root: Path) -> str | None:
    """Repo-relative, POSIX, case-folded key for a path, or None if outside the project."""
    if not path_str:
        return None
    p = Path(path_str)
    if not p.is_absolute():
        p = root / p
    try:
        rel = os.path.relpath(os.path.normpath(str(p)), str(root))
    except ValueError:  # another drive on Windows
        return None
    rel = rel.replace("\\", "/")
    if rel == ".." or rel.startswith("../"):
        return None
    return rel.casefold()


def frozen_files(root: Path) -> dict[str, str]:
    """Map of case-folded frozen file keys to a description. Raises if FROZEN.json is malformed."""
    manifest_path = root / FROZEN
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = manifest.get("version")
    files: dict[str, str] = {FROZEN.casefold(): f"the frozen manifest of registry version {version}"}
    for name, component in manifest.get("components", {}).items():
        for f in component.get("files", []):
            key = f.replace("\\", "/").casefold()
            files[key] = f"component '{name}' of frozen registry version {version}"
    return files


def protection_reason(key: str | None, root: Path) -> str | None:
    """Why a path may not be written, or None if it may."""
    if key is None:
        return None
    frozen = frozen_files(root)
    if key in frozen:
        return f"it is {frozen[key]}"
    if key in STATIC_PROTECTED_FILES:
        return "the change ledger is append-only and written only by hooks"
    for prefix in STATIC_PROTECTED_PREFIXES:
        if key.startswith(prefix):
            return f"everything under {prefix} is immutable once written"
    return None


def protected_keys(root: Path) -> list[str]:
    """Every protected file key and prefix, for matching inside shell commands."""
    return sorted(set(frozen_files(root)) | set(STATIC_PROTECTED_FILES) | set(STATIC_PROTECTED_PREFIXES))


def is_registry_path(key: str | None) -> bool:
    return key is not None and key.startswith("registry/")


# ---------------------------------------------------------------- files


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def safe_name(value: str | None) -> str:
    """A filesystem-safe name derived from a tool_use_id or session id."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value or "unknown")[:120]


def rel_display(path_str: str, root: Path) -> str:
    """Repo-relative POSIX path with its original case, for ledger records."""
    p = Path(path_str)
    if not p.is_absolute():
        p = root / p
    return os.path.relpath(os.path.normpath(str(p)), str(root)).replace("\\", "/")


def state_path(root: Path, *parts: str) -> Path:
    p = root / STATE_DIR
    for part in parts:
        p = p / part
    return p


# ---------------------------------------------------------------- ledger and decisions


def ledger_records(root: Path) -> list[dict]:
    path = root / LEDGER
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def unreasoned_changes(records: list[dict], session_id: str | None = None) -> list[str]:
    """Ids of change records not covered by any reason record (optionally for one session)."""
    covered = {cid for r in records if r.get("type") == "reason" for cid in r.get("for", [])}
    return [
        r["id"]
        for r in records
        if r.get("type") == "change"
        and r.get("id") not in covered
        and (session_id is None or r.get("session_id") == session_id)
    ]


def decision_status(root: Path) -> dict[str, tuple[str, str]]:
    """Latest status and text per decision id, from the append-only decision log."""
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
    """Plain-text project status for session context and `viveka status`."""
    lines = ["Viveka status"]
    manifest_path = root / FROZEN
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        comps = ", ".join(sorted(manifest.get("components", {}))) or "none"
        lines.append(f"- registry: frozen version {manifest.get('version')} (components: {comps})")
    else:
        lines.append("- registry: no frozen registry (drafts only)")
    records = ledger_records(root)
    pending = unreasoned_changes(records)
    lines.append(f"- change ledger: {len(records)} records, {len(pending)} changes without a reason")
    runs_dir = root / "runs"
    run_count = sum(1 for p in runs_dir.iterdir() if p.is_dir()) if runs_dir.exists() else 0
    lines.append(f"- runs: {run_count}")
    decisions = decision_status(root)
    open_ids = [
        f"{did} ({text})"
        for did, (st, text) in sorted(decisions.items(), key=lambda kv: int(kv[0][2:]))
        if st == "OPEN"
    ]
    lines.append(f"- open decisions: {len(open_ids)}")
    lines.extend(f"  - {item}" for item in open_ids)
    return "\n".join(lines)
