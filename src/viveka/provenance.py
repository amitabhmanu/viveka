"""Run manifests and content-addressed artefacts (spec §12).

Every stage runs inside a ``RunContext``. On entry it verifies the registry
components the stage depends on and refuses a dirty git tree for strict folds; on
exit it writes ``runs/<run_id>/manifest.json`` exactly once, whether the run
succeeded or failed. Derived artefacts go to ``data/derived/`` under their own
content hash and are never overwritten.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import secrets
from pathlib import Path

import jsonschema

from viveka import __version__, gitinfo, schemas
from viveka.hashing import sha256_bytes, sha256_file
from viveka.paths import DERIVED, RUNS, rel_posix
from viveka.registry import manifest as mf
from viveka.registry.verify import require_frozen

FOLDS = ("dev", "calibration", "heldout", "pilot", "contested")
STRICT_FOLDS = ("pilot", "heldout", "contested")
_SLUG = re.compile(r"[^a-z0-9]+")


class ProvenanceError(RuntimeError):
    pass


def _slug(value: str) -> str:
    slug = _SLUG.sub("-", value.lower()).strip("-")
    if not slug:
        raise ProvenanceError(f"cannot build a run id from {value!r}")
    return slug


def mint_run_id(stage: str, case: str, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.UTC)
    return f"{now:%Y-%m-%dT%H%MZ}-{_slug(stage)}-{_slug(case)}-{secrets.token_hex(2)}"


def store_artifact(root: Path, data: bytes, ext: str) -> Path:
    """Write bytes under their content hash. Existing files are checked, never overwritten."""
    sha = sha256_bytes(data)
    digest = sha.removeprefix("sha256:")
    path = root / DERIVED / digest[:2] / f"{digest}.{ext.lstrip('.')}"
    if path.exists():
        if sha256_file(path) != sha:
            raise ProvenanceError(f"{rel_posix(path, root)} exists but does not match its content hash")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as fh:
        fh.write(data)
    return path


class RunContext:
    def __init__(self, root: Path, stage: str, case: str, fold: str, components: list[str],
                 seed: int | None = None, params: dict | None = None):
        if fold not in FOLDS:
            raise ProvenanceError(f"unknown fold {fold!r}; expected one of {', '.join(FOLDS)}")
        self.root = root
        self.stage = stage
        self.case = case
        self.fold = fold
        self.components = list(components)
        self.seed = seed
        self.params = dict(params or {})
        self.usage: dict = {}  # external API use, per source (spec §13)
        self.inputs: list[dict] = []
        self.outputs: list[dict] = []
        self.run_id: str | None = None
        self.run_dir: Path | None = None

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> RunContext:
        in_repo = gitinfo.is_repo(self.root)
        self.git_commit = gitinfo.head_commit(self.root) if in_repo else None
        self.git_dirty = gitinfo.is_dirty(self.root) if in_repo else None
        if self.fold in STRICT_FOLDS and self.git_dirty is not False:
            state = "not a git repository" if self.git_dirty is None else "the git tree has uncommitted changes"
            raise ProvenanceError(f"fold {self.fold!r} requires a clean git tree, but {state}")

        self.registry_components = require_frozen(self.root, self.components, self.fold)
        self.registry_version = mf.read(self.root)["version"]
        self.run_id = mint_run_id(self.stage, self.case)
        self.run_dir = self.root / RUNS / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self.started = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        manifest = {
            "run_id": self.run_id,
            "stage": self.stage,
            "case": self.case,
            "fold": self.fold,
            "status": "failed" if exc_type else "ok",
            "error": f"{exc_type.__name__}: {exc}" if exc_type else None,
            "git_commit": self.git_commit,
            "git_dirty": self.git_dirty,
            "registry": {"version": self.registry_version, "components": self.registry_components},
            "inputs": self.inputs,
            "outputs": self.outputs,
            "coders": [],
            "usage": self.usage,
            "seed": self.seed,
            "params": self.params,
            "started": self.started,
            "ended": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "viveka_version": __version__,
        }
        jsonschema.Draft202012Validator(schemas.load("run_manifest")).validate(manifest)
        with open(self.run_dir / "manifest.json", "x", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        return False  # never swallow the run's exception

    # -- recording ---------------------------------------------------------

    def record_input(self, path: Path) -> None:
        self.inputs.append({"path": rel_posix(path, self.root), "sha256": sha256_file(path)})

    def record_output(self, path: Path, rows: int | None = None) -> None:
        self.outputs.append({"path": rel_posix(path, self.root), "sha256": sha256_file(path), "rows": rows})

    def store(self, data: bytes, ext: str, rows: int | None = None) -> Path:
        path = store_artifact(self.root, data, ext)
        self.record_output(path, rows)
        return path


def load_manifest(root: Path, run_id: str) -> dict:
    path = root / RUNS / run_id / "manifest.json"
    if not path.is_file():
        raise ProvenanceError(f"no manifest for run {run_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def verify_run(root: Path, run_id: str) -> list[str]:
    """Problems with a run's recorded artefacts; empty means everything still matches."""
    try:
        manifest = load_manifest(root, run_id)
    except (ProvenanceError, json.JSONDecodeError) as exc:
        return [str(exc)]
    problems = [f"manifest: {e.message}" for e in
                jsonschema.Draft202012Validator(schemas.load("run_manifest")).iter_errors(manifest)]
    for kind in ("inputs", "outputs"):
        for item in manifest.get(kind, []):
            path = root / item["path"]
            if not path.is_file():
                problems.append(f"{kind[:-1]} {item['path']} is missing")
            elif sha256_file(path) != item["sha256"]:
                problems.append(f"{kind[:-1]} {item['path']} no longer matches its recorded hash")
    return problems


def recent_runs(root: Path, limit: int = 5) -> list[dict]:
    runs_dir = root / RUNS
    if not runs_dir.is_dir():
        return []
    manifests = sorted(runs_dir.glob("*/manifest.json"), reverse=True)[:limit]
    return [json.loads(p.read_text(encoding="utf-8")) for p in manifests]
