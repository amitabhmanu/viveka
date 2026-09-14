import json

import jsonschema
import pytest
from conftest import write_lf

from viveka import provenance, schemas
from viveka.registry import manifest as mf
from viveka.registry.errors import RegistryNotFrozen
from viveka.registry.freeze import freeze


def _manifest(root, ctx) -> dict:
    return json.loads((root / "runs" / ctx.run_id / "manifest.json").read_text(encoding="utf-8"))


def test_dev_run_writes_a_valid_manifest_with_draft_components(registry_root):
    with provenance.RunContext(registry_root, "S0", "demo", "dev", ["schemas"], seed=7) as ctx:
        ctx.record_input(registry_root / "registry" / "thresholds.yaml")
        ctx.store(b"derived bytes", "txt", rows=1)
    manifest = _manifest(registry_root, ctx)
    jsonschema.Draft202012Validator(schemas.load("run_manifest")).validate(manifest)
    assert manifest["status"] == "ok" and manifest["seed"] == 7
    assert manifest["registry"]["components"]["schemas"].startswith("draft:")
    assert manifest["outputs"][0]["path"].startswith("data/derived/")
    assert provenance.verify_run(registry_root, ctx.run_id) == []


def test_failed_run_still_writes_its_manifest(registry_root):
    with pytest.raises(ValueError), provenance.RunContext(registry_root, "S1", "demo", "dev", []) as ctx:
        raise ValueError("boom")
    manifest = _manifest(registry_root, ctx)
    assert manifest["status"] == "failed" and "boom" in manifest["error"]


def test_manifests_are_never_overwritten(registry_root, monkeypatch):
    monkeypatch.setattr(provenance, "mint_run_id", lambda stage, case: "2026-09-14T0000Z-s0-demo-abcd")
    with provenance.RunContext(registry_root, "S0", "demo", "dev", []):
        pass
    with pytest.raises(FileExistsError), provenance.RunContext(registry_root, "S0", "demo", "dev", []):
        pass


def test_strict_folds_need_a_clean_tree_and_frozen_components(registry_root, git_project):
    with pytest.raises(provenance.ProvenanceError, match="not a git repository"):
        provenance.RunContext(registry_root, "S8", "pilot", "pilot", []).__enter__()

    with pytest.raises(RegistryNotFrozen):
        provenance.RunContext(git_project, "S8", "pilot", "pilot", ["schemas"]).__enter__()

    freeze(git_project, ["schemas"], "pilot prerequisites")
    with provenance.RunContext(git_project, "S8", "pilot", "pilot", ["schemas"]) as first:
        first.store(b"labels", "jsonl")
    assert _manifest(git_project, first)["registry"]["components"]["schemas"] == \
        mf.read(git_project)["components"]["schemas"]["sha256"]

    # Pipeline output under runs/ and data/ does not make the tree dirty for the next run.
    with provenance.RunContext(git_project, "S9", "pilot", "pilot", ["schemas"]):
        pass

    write_lf(git_project / "notes.md", "uncommitted")
    with pytest.raises(provenance.ProvenanceError, match="uncommitted changes"):
        provenance.RunContext(git_project, "S10", "pilot", "pilot", ["schemas"]).__enter__()


def test_artifacts_are_content_addressed_and_tampering_is_detected(registry_root):
    first = provenance.store_artifact(registry_root, b"same", "bin")
    assert provenance.store_artifact(registry_root, b"same", "bin") == first

    with provenance.RunContext(registry_root, "S9", "demo", "dev", []) as ctx:
        out = ctx.store(b"measures", "json")
    out.write_bytes(b"tampered")
    assert any("no longer matches" in p for p in provenance.verify_run(registry_root, ctx.run_id))
    with pytest.raises(provenance.ProvenanceError):
        provenance.store_artifact(registry_root, b"measures", "json")


def test_unknown_fold_is_rejected(registry_root):
    with pytest.raises(provenance.ProvenanceError, match="unknown fold"):
        provenance.RunContext(registry_root, "S0", "demo", "training", [])
