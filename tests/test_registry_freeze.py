"""Spec §15 registry tests: deterministic freeze, byte-level verify, refusal of
unfrozen dependencies, bump preserving the old version, and M0 hook integration."""

import tempfile
from pathlib import Path

import pytest
import yaml
from conftest import edit_event, git, shell_event, write_lf
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from viveka import gitinfo, ledger
from viveka.registry import components as comp
from viveka.registry import manifest as mf
from viveka.registry.errors import FreezeRefused, RegistryIntegrityError, RegistryNotFrozen
from viveka.registry.freeze import bump, freeze
from viveka.registry.verify import check, require_frozen, verify


def _add_prompt_stack(root: Path) -> None:
    write_lf(root / "registry" / "codebook" / "rules.md", "# Stance rules\n\nDiscounts need a reason.\n")
    write_lf(root / "registry" / "prompts" / "t1.md", "---\nschema: thresholds\n---\nCode the citation.\n")


def _complete_thresholds(root: Path) -> None:
    run_id = "2026-09-14T0000Z-sim-all-abcd"
    write_lf(root / "runs" / run_id / "manifest.json", "{}")
    path = root / "registry" / "thresholds.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for entry in data["parameters"].values():
        if entry["value"] is None:
            entry["value"] = 0.5
        if entry["status"] in ("fitted", "simulated"):
            entry["source_run"] = run_id
    write_lf(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


# ---------------------------------------------------------------- freeze


def test_freeze_writes_manifest_ledger_commit_and_tag(git_project):
    result = freeze(git_project, ["schemas"], "first freeze")

    manifest = mf.read(git_project)
    entry = manifest["components"]["schemas"]
    assert manifest["version"] == result.version == 1
    assert entry["files"] == comp.files_of(git_project, "schemas")
    assert entry["sha256"] == comp.component_hash(git_project, "schemas")

    record = ledger.records(git_project)[-1]
    assert record["type"] == "freeze" and record["components"] == {"schemas": entry["sha256"]}
    assert record["tag"] == "registry-v1" and record["manifest_sha256"] == mf.content_hash(manifest)

    assert gitinfo.tag_exists(git_project, "registry-v1")
    assert not gitinfo.is_dirty(git_project)
    assert ledger.verify(git_project) == []


def test_freeze_commits_only_its_own_paths(git_project):
    write_lf(git_project / "unrelated.txt", "staged work")
    git(git_project, "add", "unrelated.txt")
    freeze(git_project, ["schemas"], "keep unrelated work out")
    assert "unrelated.txt" not in git(git_project, "show", "--name-only", "--format=", "HEAD")
    assert "A  unrelated.txt" in git(git_project, "status", "--porcelain")


_names = st.from_regex(r"[a-z][a-z0-9_]{0,6}\.md", fullmatch=True)
_trees = st.dictionaries(_names, st.binary(max_size=64), min_size=1, max_size=5)


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(tree=_trees)
def test_freeze_is_deterministic(tree):
    hashes = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, data in tree.items():
                (root / "registry" / "codebook").mkdir(parents=True, exist_ok=True)
                (root / "registry" / "codebook" / name).write_bytes(data)
            freeze(root, ["codebook"], "determinism", use_git=False)
            entry = mf.read(root)["components"]["codebook"]
            hashes.append((entry["sha256"], entry["file_sha256"]))
            with pytest.raises(FreezeRefused, match="identical content"):
                freeze(root, ["codebook"], "again", use_git=False)
    assert hashes[0] == hashes[1]


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        (lambda r: None, "has no value"),
        (lambda r: _complete_thresholds(r), None),
    ],
)
def test_thresholds_need_values_and_provenance(registry_root, setup, message):
    setup(registry_root)
    # Thresholds are simulated (D-7), so the simulation settings and their schemas freeze with them.
    names = ["schemas", "simulation", "thresholds"]
    if message:
        with pytest.raises(FreezeRefused, match=message):
            freeze(registry_root, names, "calibrated", use_git=False)
    else:
        assert freeze(registry_root, names, "calibrated", use_git=False).version == 1


def test_thresholds_cannot_freeze_before_their_simulation_settings(registry_root):
    _complete_thresholds(registry_root)
    with pytest.raises(FreezeRefused, match="upstream component simulation is not frozen"):
        freeze(registry_root, ["thresholds"], "too early", use_git=False)


def test_fitted_value_without_source_run_is_refused(registry_root):
    _complete_thresholds(registry_root)
    path = registry_root / "registry" / "thresholds.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["parameters"]["delta"]["source_run"] = None
    write_lf(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    with pytest.raises(FreezeRefused, match="delta is simulated but has no source_run"):
        freeze(registry_root, ["schemas", "simulation", "thresholds"], "calibrated", use_git=False)


def test_other_refusals(registry_root, git_project):
    with pytest.raises(FreezeRefused, match="no files to freeze"):
        freeze(registry_root, ["codebook"], "empty", use_git=False)
    with pytest.raises(FreezeRefused, match="reason is required"):
        freeze(registry_root, ["schemas"], "   ", use_git=False)
    with pytest.raises(FreezeRefused, match="not a git repository"):
        freeze(registry_root, ["schemas"], "no git")

    _add_prompt_stack(registry_root)
    with pytest.raises(FreezeRefused, match="upstream component codebook is not frozen"):
        freeze(registry_root, ["prompts"], "too early", use_git=False)
    assert freeze(registry_root, ["codebook", "schemas", "prompts"], "together", use_git=False).version == 1

    git(git_project, "tag", "-a", "registry-v1", "-m", "squatter")
    with pytest.raises(FreezeRefused, match="registry-v1 already exists"):
        freeze(git_project, ["schemas"], "tag clash")


# ---------------------------------------------------------------- verify


def test_verify_detects_changed_added_and_missing_files(registry_root):
    freeze(registry_root, ["schemas"], "base", use_git=False)
    target = registry_root / "registry" / "schemas" / "instrument.schema.json"
    original = target.read_bytes()

    target.write_bytes(original[:-2] + bytes([original[-2] ^ 1]) + original[-1:])
    assert check(registry_root) == {"schemas": ["changed registry/schemas/instrument.schema.json"]}
    with pytest.raises(RegistryIntegrityError):
        verify(registry_root)

    target.write_bytes(original)
    write_lf(registry_root / "registry" / "schemas" / "extra.schema.json", "{}")
    assert check(registry_root) == {"schemas": ["added registry/schemas/extra.schema.json"]}

    (registry_root / "registry" / "schemas" / "extra.schema.json").unlink()
    target.unlink()
    assert check(registry_root) == {"schemas": ["missing registry/schemas/instrument.schema.json"]}

    target.write_bytes(original)
    verify(registry_root)


def test_require_frozen_refuses_drafts_outside_dev_and_checks_upstream(registry_root):
    with pytest.raises(RegistryNotFrozen):
        require_frozen(registry_root, ["schemas"], "pilot")
    assert require_frozen(registry_root, ["schemas"], "dev")["schemas"].startswith("draft:sha256:")

    _add_prompt_stack(registry_root)
    freeze(registry_root, ["codebook", "schemas", "prompts"], "stack", use_git=False)
    used = require_frozen(registry_root, ["prompts"], "pilot")
    assert set(used) == {"codebook", "schemas", "prompts"}

    write_lf(registry_root / "registry" / "codebook" / "rules.md", "# changed after freezing\n")
    for fold in ("pilot", "dev"):
        with pytest.raises(RegistryIntegrityError, match="codebook"):
            require_frozen(registry_root, ["prompts"], fold)


# ---------------------------------------------------------------- bump


def test_bump_cascades_and_preserves_the_old_version(git_project):
    _add_prompt_stack(git_project)
    freeze(git_project, ["codebook", "schemas", "prompts"], "version one")
    rules = git_project / "registry" / "codebook" / "rules.md"
    old_bytes = rules.read_bytes()
    old_hash = mf.read(git_project)["components"]["codebook"]["sha256"]

    result = bump(git_project, ["codebook"], "tighten discount rule", "2026-09-14T0000Z-s7-anchor-abcd")
    assert result.cascaded == ["prompts"]
    assert sorted(mf.read(git_project)["components"]) == ["schemas"]
    record = ledger.records(git_project)[-1]
    assert record["type"] == "bump" and record["components"]["codebook"] == old_hash
    assert record["prompted_by"] == "2026-09-14T0000Z-s7-anchor-abcd"

    with pytest.raises(RegistryNotFrozen):
        require_frozen(git_project, ["prompts"], "pilot")

    write_lf(rules, "# Stance rules\n\nDiscounts need a checkable reason.\n")
    assert freeze(git_project, ["codebook", "prompts"], "version two").version == 2
    assert gitinfo.show_file(git_project, "registry-v1", "registry/codebook/rules.md") == old_bytes
    assert gitinfo.show_file(git_project, "registry-v2", "registry/codebook/rules.md") == rules.read_bytes()
    assert ledger.verify(git_project) == []


def test_bump_refusals(registry_root):
    freeze(registry_root, ["schemas"], "base", use_git=False)
    with pytest.raises(FreezeRefused, match="prompted-by is required"):
        bump(registry_root, ["schemas"], "why", "")
    with pytest.raises(FreezeRefused, match="is not frozen"):
        bump(registry_root, ["codebook"], "why", "run")
    write_lf(registry_root / "registry" / "schemas" / "instrument.schema.json", "{}")
    with pytest.raises(FreezeRefused, match="restore it from tag registry-v1"):
        bump(registry_root, ["schemas"], "why", "run")


# ---------------------------------------------------------------- M0 hooks


def test_hooks_protect_what_a_real_freeze_froze(git_project, hook):
    freeze(git_project, ["schemas"], "protect")
    target = git_project / "registry" / "schemas" / "thresholds.schema.json"
    assert hook("guard_frozen.py", git_project, edit_event(str(target))).returncode == 2
    manifest = git_project / "registry" / "FROZEN.json"
    assert hook("guard_frozen.py", git_project, edit_event(str(manifest))).returncode == 2
    assert hook("guard_shell.py", git_project,
                shell_event("Remove-Item registry/schemas/thresholds.schema.json")).returncode == 2
    assert hook("guard_frozen.py", git_project,
                edit_event(str(git_project / "registry" / "instrument.yaml"))).returncode == 0
