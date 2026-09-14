"""Checking frozen components against FROZEN.json, and the guard every stage calls."""

from __future__ import annotations

from pathlib import Path

from viveka.hashing import tree_hash
from viveka.registry import components as comp
from viveka.registry import manifest as mf
from viveka.registry.errors import RegistryIntegrityError, RegistryNotFrozen

DEV_FOLD = "dev"


def check(root: Path, names: list[str] | None = None) -> dict[str, list[str]]:
    """Mismatches per frozen component (all frozen components if ``names`` is None)."""
    manifest = mf.read(root)
    frozen = manifest["components"]
    targets = [n for n in (names if names is not None else sorted(frozen)) if n in frozen]
    mismatches: dict[str, list[str]] = {}
    for name in targets:
        recorded: dict[str, str] = frozen[name].get("file_sha256", {})
        current = comp.file_hashes(root, name)
        issues = [f"missing {p}" for p in sorted(set(recorded) - set(current))]
        issues += [f"added {p}" for p in sorted(set(current) - set(recorded))]
        issues += [f"changed {p}" for p in sorted(set(recorded) & set(current)) if recorded[p] != current[p]]
        if not issues and tree_hash(current) != frozen[name]["sha256"]:
            issues.append("tree hash differs from the manifest")
        if issues:
            mismatches[name] = issues
    return mismatches


def verify(root: Path, names: list[str] | None = None) -> None:
    mismatches = check(root, names)
    if mismatches:
        raise RegistryIntegrityError(mismatches)


def require_frozen(root: Path, names: list[str], fold: str) -> dict[str, str]:
    """Verify ``names`` and everything upstream of them before a stage runs.

    Returns the hash of every component used, for the run manifest. Outside the
    development fold every component must be frozen and intact. In the
    development fold drafts are allowed and recorded as ``draft:<hash>``; a frozen
    component that no longer matches is refused in every fold.
    """
    needed = comp.with_upstream(root, names)
    frozen = mf.read(root)["components"]
    unfrozen = [n for n in needed if n not in frozen]
    if unfrozen and fold != DEV_FOLD:
        raise RegistryNotFrozen(unfrozen)
    verify(root, [n for n in needed if n in frozen])
    used = {}
    for name in needed:
        if name in frozen:
            used[name] = frozen[name]["sha256"]
        else:
            used[name] = "draft:" + (comp.component_hash(root, name) or "empty")
    return used
