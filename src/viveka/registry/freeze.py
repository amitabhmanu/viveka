"""Freezing registry components, and returning frozen components to draft (bump).

A freeze writes FROZEN.json, appends a ``freeze`` record to the change ledger and,
in a git repository, commits exactly the newly frozen files, the manifest and the
ledger, then tags the commit ``registry-v<N>``. The tag is what keeps every old
version retrievable after a bump.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from viveka import gitinfo, ledger
from viveka.hashing import tree_hash
from viveka.paths import FROZEN, LEDGER
from viveka.registry import components as comp
from viveka.registry import manifest as mf
from viveka.registry import verify as vf
from viveka.registry.errors import FreezeRefused, RegistryError
from viveka.registry.validate import freeze_problems


@dataclass(frozen=True)
class FreezeResult:
    version: int
    components: dict[str, str]
    ledger_id: str
    tag: str | None
    git_commit: str | None


@dataclass(frozen=True)
class BumpResult:
    from_version: int
    components: dict[str, str]
    cascaded: list[str]
    ledger_id: str


def _unique(names: list[str]) -> list[str]:
    return list(dict.fromkeys(names))


def freeze(root: Path, names: list[str], reason: str, use_git: bool = True) -> FreezeResult:
    names = _unique(names)
    reason = " ".join((reason or "").split())
    manifest = mf.read(root)
    problems = [] if reason else ["a reason is required"]
    if not names:
        problems.append("name at least one component to freeze")
    problems += freeze_problems(root, names, manifest)
    problems += [f"{name}: frozen content has changed ({'; '.join(issues)})"
                 for name, issues in vf.check(root).items()]

    version = manifest["version"] + 1
    tag = f"registry-v{version}" if use_git else None
    if use_git:
        if not gitinfo.is_repo(root):
            problems.append("not a git repository (use --no-git only for development)")
        elif gitinfo.tag_exists(root, tag):
            problems.append(f"git tag {tag} already exists")
    if problems:
        raise FreezeRefused(problems)

    now = ledger.now_iso()
    ledger_id = ledger.new_id("frz")
    frozen_hashes: dict[str, str] = {}
    newly_frozen_files: list[str] = []
    for name in names:
        file_hashes = comp.file_hashes(root, name)
        sha = tree_hash(file_hashes)
        frozen_hashes[name] = sha
        newly_frozen_files += sorted(file_hashes)
        manifest["components"][name] = {
            "sha256": sha,
            "files": sorted(file_hashes),
            "file_sha256": file_hashes,
            "frozen_in": version,
            "frozen_at": now,
            "ledger_id": ledger_id,
        }
    manifest["version"] = version
    mf.write(root, manifest)

    ledger.append(root, {
        "id": ledger_id,
        "type": "freeze",
        "time": now,
        "version": version,
        "components": frozen_hashes,
        "manifest_sha256": mf.content_hash(manifest),
        "reason": reason,
        "git_commit": None,
        "tag": tag,
    })

    commit = None
    if use_git:
        message = f"registry v{version}: freeze {', '.join(names)}\n\n{reason}"
        try:
            commit = gitinfo.commit_paths(root, message, [*newly_frozen_files, FROZEN, LEDGER])
            gitinfo.create_tag(root, tag, f"Viveka registry version {version}: {reason}")
        except gitinfo.GitError as exc:
            raise RegistryError(
                f"registry version {version} is frozen in {FROZEN} and recorded in the ledger, "
                f"but committing or tagging failed: {exc}. Commit those files and create tag {tag} by hand."
            ) from exc
    return FreezeResult(version, frozen_hashes, ledger_id, tag, commit)


def bump(root: Path, names: list[str], reason: str, prompted_by: str) -> BumpResult:
    names = _unique(names)
    reason = " ".join((reason or "").split())
    prompted_by = " ".join((prompted_by or "").split())
    manifest = mf.read(root)
    frozen = manifest["components"]

    problems = []
    if not reason:
        problems.append("a reason is required")
    if not prompted_by:
        problems.append("--prompted-by is required: name the run or result that prompted the change")
    if not names:
        problems.append("name at least one component to bump")
    for name in names:
        comp.validate_name(name)
        if name not in frozen:
            problems.append(f"{name}: is not frozen")
    if problems:
        raise FreezeRefused(problems)

    mismatches = vf.check(root, names)
    if mismatches:
        raise FreezeRefused([
            f"{name}: frozen content has changed ({'; '.join(issues)}); restore it from tag "
            f"registry-v{frozen[name]['frozen_in']} before bumping"
            for name, issues in mismatches.items()
        ])

    others = [n for n in frozen if n not in names]
    cascaded = sorted({d for name in names for d in comp.downstream(root, name, others)})
    released = [*names, *cascaded]
    old_hashes = {name: frozen[name]["sha256"] for name in released}
    for name in released:
        del frozen[name]
    mf.write(root, manifest)

    ledger_id = ledger.new_id("bmp")
    ledger.append(root, {
        "id": ledger_id,
        "type": "bump",
        "time": ledger.now_iso(),
        "from_version": manifest["version"],
        "components": old_hashes,
        "cascaded": cascaded,
        "reason": reason,
        "prompted_by": prompted_by,
    })
    return BumpResult(manifest["version"], old_hashes, cascaded, ledger_id)
