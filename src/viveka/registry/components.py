"""The component map: which registry files freeze together, and what depends on what.

Components are derived from a fixed map, never configured by hand:

* ``thresholds`` and ``instrument`` are single files;
* ``schemas``, ``codebook`` and ``prompts`` are whole directories;
* ``events/<claim>``, ``filters/<commitment>``, ``predictions/<case>`` and
  ``redaction/<case>`` are one YAML file each.

``.gitkeep`` files and ``FROZEN.json`` belong to no component. Any other file under
``registry/`` that matches no component is an orphan, which validation rejects.
"""

from __future__ import annotations

import re
from pathlib import Path

from viveka.hashing import sha256_file, tree_hash
from viveka.paths import FROZEN, REGISTRY
from viveka.registry.errors import UnknownComponent

SINGLE_FILES = {
    "thresholds": "registry/thresholds.yaml",
    "instrument": "registry/instrument.yaml",
    "simulation": "registry/simulation.yaml",
}
DIRECTORIES = ("schemas", "codebook", "prompts")
PER_FILE_DIRS = ("events", "filters", "predictions", "redaction")
IGNORED_NAMES = frozenset({".gitkeep"})

_PER_FILE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# Direct upstream dependencies that do not depend on file content.
STATIC_UPSTREAM: dict[str, tuple[str, ...]] = {
    "prompts": ("codebook", "schemas"),
    "instrument": ("schemas",),
    "simulation": ("schemas",),
    "thresholds": ("simulation",),  # decision D-7: simulated thresholds come from the simulation settings
}


def validate_name(name: str) -> None:
    if name in SINGLE_FILES or name in DIRECTORIES:
        return
    kind, _, stem = name.partition("/")
    if kind in PER_FILE_DIRS and _PER_FILE_NAME.match(stem):
        return
    raise UnknownComponent(
        f"unknown registry component {name!r}; expected one of {sorted(SINGLE_FILES)}, "
        f"{list(DIRECTORIES)}, or <{'|'.join(PER_FILE_DIRS)}>/<name>"
    )


def component_of(relpath: str) -> str | None:
    """The component a repo-relative POSIX path belongs to, or None."""
    parts = relpath.split("/")
    if len(parts) < 2 or parts[0] != REGISTRY or relpath == FROZEN or parts[-1] in IGNORED_NAMES:
        return None
    for name, path in SINGLE_FILES.items():
        if relpath == path:
            return name
    if parts[1] in DIRECTORIES and len(parts) >= 3:
        return parts[1]
    if parts[1] in PER_FILE_DIRS and len(parts) == 3 and parts[2].endswith(".yaml"):
        stem = parts[2][: -len(".yaml")]
        if _PER_FILE_NAME.match(stem):
            return f"{parts[1]}/{stem}"
    return None


def registry_files(root: Path) -> list[str]:
    """Every file under registry/ except FROZEN.json and ignored placeholders, sorted."""
    base = root / REGISTRY
    if not base.is_dir():
        return []
    files = []
    for path in base.rglob("*"):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            if rel != FROZEN and path.name not in IGNORED_NAMES:
                files.append(rel)
    return sorted(files)


def discover(root: Path) -> dict[str, list[str]]:
    """Map of every component that currently has files to its sorted file list."""
    found: dict[str, list[str]] = {}
    for rel in registry_files(root):
        name = component_of(rel)
        if name is not None:
            found.setdefault(name, []).append(rel)
    return found


def orphans(root: Path) -> list[str]:
    return [rel for rel in registry_files(root) if component_of(rel) is None]


def files_of(root: Path, name: str) -> list[str]:
    validate_name(name)
    return discover(root).get(name, [])


def file_hashes(root: Path, name: str) -> dict[str, str]:
    return {rel: sha256_file(root / rel) for rel in files_of(root, name)}


def component_hash(root: Path, name: str) -> str | None:
    """Tree hash of a component's current files, or None if it has no files."""
    hashes = file_hashes(root, name)
    return tree_hash(hashes) if hashes else None


def direct_upstream(root: Path, name: str) -> list[str]:
    validate_name(name)
    upstream = list(STATIC_UPSTREAM.get(name, ()))
    if name.startswith("filters/"):
        upstream.append("codebook")
        claim = _filter_claim(root, name)
        if claim:
            upstream.append(f"events/{claim}")
    return upstream


def with_upstream(root: Path, names: list[str]) -> list[str]:
    """The given components plus everything they depend on, upstream first, no duplicates."""
    ordered: list[str] = []

    def visit(name: str, trail: tuple[str, ...]) -> None:
        if name in trail:
            raise UnknownComponent(f"dependency cycle: {' -> '.join((*trail, name))}")
        for dep in direct_upstream(root, name):
            visit(dep, (*trail, name))
        if name not in ordered:
            ordered.append(name)

    for name in names:
        visit(name, ())
    return ordered


def downstream(root: Path, name: str, candidates: list[str]) -> list[str]:
    """Candidates that depend on ``name``, directly or transitively."""
    return [c for c in candidates if c != name and name in with_upstream(root, [c])]


def _filter_claim(root: Path, name: str) -> str | None:
    import yaml

    path = root / REGISTRY / f"{name}.yaml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    claim = data.get("claim") if isinstance(data, dict) else None
    return claim if isinstance(claim, str) and _PER_FILE_NAME.match(claim) else None
