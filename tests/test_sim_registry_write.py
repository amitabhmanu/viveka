import pytest
import yaml
from conftest import write_lf

from viveka import ledger
from viveka.cli import main
from viveka.registry.thresholds import load_thresholds
from viveka.registry.validate import validate
from viveka.sim.registry_write import DraftWriteRefused, write_draft

RUN = "2026-09-14T1600Z-sim-thresholds-abcd"
VALUES = {"delta": 0.1234567, "c": 0.8, "k": 4, "t": 0.71, "h": 0.4, "m": 40, "v": 120}


def _fake_run(root):
    write_lf(root / "runs" / RUN / "manifest.json", "{}")


def test_write_draft_sets_values_provenance_and_ledger(registry_root):
    _fake_run(registry_root)
    path = registry_root / "registry" / "thresholds.yaml"
    before = path.read_text(encoding="utf-8").splitlines()

    written = write_draft(registry_root, VALUES, RUN, "D-7 test run")

    th = load_thresholds(registry_root)
    assert th["delta"] == 0.123457 and th["k_min_loop"] == 4 and th["m_min_members"] == 40
    assert th.parameter("v_min_citations").source_run == RUN
    assert written["c_max_insulating_share"] == 0.8
    assert validate(registry_root, ["thresholds"]) == []

    after = path.read_text(encoding="utf-8").splitlines()
    changed = [(a, b) for a, b in zip(before, after, strict=True) if a != b]
    assert len(changed) == 14  # value and source_run lines of the seven written parameters only
    assert all(b.strip().startswith(("value:", "source_run:")) for _, b in changed)
    assert any(line.startswith("# Viveka parameter registry") for line in after)

    change, reason = ledger.records(registry_root)[-2:]
    assert change["type"] == "change" and change["tool"] == "viveka sim thresholds" and change["session_id"] is None
    assert reason["for"] == [change["id"]] and reason["decision"] == "D-7"
    assert ledger.verify(registry_root) == []


def test_write_draft_refusals(registry_root):
    with pytest.raises(DraftWriteRefused, match="no manifest"):
        write_draft(registry_root, VALUES, RUN, "x")
    _fake_run(registry_root)
    path = registry_root / "registry" / "thresholds.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["parameters"]["delta"]["status"] = "fitted"
    write_lf(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    with pytest.raises(DraftWriteRefused, match="only simulated"):
        write_draft(registry_root, VALUES, RUN, "x")


def test_cli_refuses_overridden_settings_with_write_draft(registry_root, capsys):
    code = main(["sim", "thresholds", "--write-draft", "--replicates", "2", "--root", str(registry_root)])
    assert code == 1 and "registered replicates" in capsys.readouterr().out
