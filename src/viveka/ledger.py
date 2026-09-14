"""The append-only change ledger (ledger/changes.jsonl) and the decision log.

Record types:

* ``change`` - an edit under registry/, written by the log_change hook;
* ``reason`` - why one or more changes were made, written by /log-decision;
* ``freeze`` - a registry freeze, written by ``viveka registry freeze``;
* ``bump``   - components returned to draft, written by ``viveka registry bump``.

The hooks in .claude/hooks keep a standard-library copy of the reading logic on
purpose (they must run without this environment); tests check both agree.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import uuid
from pathlib import Path

import jsonschema

from viveka import gitinfo, schemas
from viveka.paths import DECISIONS, LEDGER

_DECISION_LINE = re.compile(r"^- (\S+) · (D-\d+) · ([A-Z]+) · (.*)$")


class LedgerError(RuntimeError):
    pass


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(schemas.load("ledger_record"))


def records(root: Path) -> list[dict]:
    path = root / LEDGER
    if not path.exists():
        return []
    out = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise LedgerError(f"{LEDGER} line {number} is not valid JSON: {exc}") from exc
    return out


def append(root: Path, record: dict) -> dict:
    """Validate and append one record. Never rewrites existing bytes."""
    errors = sorted(_validator().iter_errors(record), key=str)
    if errors:
        raise LedgerError(f"invalid {record.get('type')} record: {errors[0].message}")
    path = root / LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = path.exists() and path.stat().st_size > 0 and not path.read_bytes().endswith(b"\n")
    with open(path, "ab") as fh:
        if needs_newline:
            fh.write(b"\n")
        fh.write((json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
        fh.flush()
        os.fsync(fh.fileno())
    return record


def unreasoned(recs: list[dict], session_id: str | None = None) -> list[str]:
    """Ids of change records no reason record covers (optionally for one session)."""
    covered = {cid for r in recs if r.get("type") == "reason" for cid in r.get("for", [])}
    return [
        r["id"]
        for r in recs
        if r.get("type") == "change"
        and r.get("id") not in covered
        and (session_id is None or r.get("session_id") == session_id)
    ]


def verify(root: Path) -> list[str]:
    """Problems with the ledger; an empty list means it is intact."""
    problems: list[str] = []
    try:
        recs = records(root)
    except LedgerError as exc:
        return [str(exc)]

    validator = _validator()
    seen: set[str] = set()
    change_ids = {r.get("id") for r in recs if r.get("type") == "change"}
    for index, rec in enumerate(recs, start=1):
        for error in validator.iter_errors(rec):
            problems.append(f"record {index} ({rec.get('id')}): {error.message}")
        rid = rec.get("id")
        if rid in seen:
            problems.append(f"record {index}: duplicate id {rid}")
        seen.add(rid)
        if rec.get("type") == "reason":
            for cid in rec.get("for", []):
                if cid not in change_ids:
                    problems.append(f"record {index} ({rid}): reason for unknown change {cid}")

    if gitinfo.is_repo(root) and gitinfo.head_commit(root):
        committed = gitinfo.show_file(root, "HEAD", LEDGER)
        current = (root / LEDGER).read_bytes() if (root / LEDGER).exists() else b""
        if committed is not None and not current.startswith(committed):
            problems.append(f"committed lines of {LEDGER} were rewritten or deleted (HEAD is not a prefix)")
    return problems


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
