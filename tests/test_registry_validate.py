import json

import pytest
import yaml
from conftest import write_lf

from viveka.registry.errors import MissingParameter, UnsetParameter
from viveka.registry.thresholds import PARAMETERS, load_thresholds
from viveka.registry.validate import validate


def test_real_registry_is_valid(registry_root):
    assert validate(registry_root) == []


def test_orphan_file(registry_root):
    write_lf(registry_root / "registry" / "notes.txt", "x")
    assert any("belongs to no registry component" in p for p in validate(registry_root))


def test_thresholds_schema_violation(registry_root):
    path = registry_root / "registry" / "thresholds.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["parameters"]["r_min_coverage"]["value"] = 2
    write_lf(path, yaml.safe_dump(data, allow_unicode=True))
    assert any("r_min_coverage" in p for p in validate(registry_root, ["thresholds"]))


def test_dangling_source_run(registry_root):
    path = registry_root / "registry" / "thresholds.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["parameters"]["m_min_members"]["source_run"] = "2026-09-14T0000Z-sim-m-abcd"
    write_lf(path, yaml.safe_dump(data, allow_unicode=True))
    assert any("has no manifest" in p for p in validate(registry_root, ["thresholds"]))
    (registry_root / "runs" / "2026-09-14T0000Z-sim-m-abcd").mkdir()
    write_lf(registry_root / "runs" / "2026-09-14T0000Z-sim-m-abcd" / "manifest.json", "{}")
    assert validate(registry_root, ["thresholds"]) == []


def test_schema_and_code_parameter_lists_must_agree(registry_root):
    path = registry_root / "registry" / "schemas" / "thresholds.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema["properties"]["parameters"]["required"].remove("delta")
    write_lf(path, json.dumps(schema))
    assert any("differ from the code" in p for p in validate(registry_root, ["thresholds"]))


def test_schema_files_must_be_valid_and_well_named(registry_root):
    write_lf(registry_root / "registry" / "schemas" / "notes.json", "{}")
    write_lf(registry_root / "registry" / "schemas" / "bad.schema.json", '{"type": 12}')
    problems = validate(registry_root, ["schemas"])
    assert any("must be named" in p for p in problems)
    assert any("not a valid JSON Schema" in p for p in problems)


def test_prompts_must_name_an_existing_schema(registry_root):
    prompt = registry_root / "registry" / "prompts" / "t1.md"
    write_lf(prompt, "no front matter")
    assert any("front matter" in p for p in validate(registry_root, ["prompts"]))
    write_lf(prompt, "---\nschema: stance\n---\nCode the citation.\n")
    assert any("does not exist" in p for p in validate(registry_root, ["prompts"]))
    write_lf(prompt, "---\nschema: thresholds\n---\nCode the citation.\n")
    assert validate(registry_root, ["prompts"]) == []


def test_filters_must_name_an_existing_claim(registry_root):
    flt = registry_root / "registry" / "filters" / "cf.yaml"
    write_lf(flt, "format: 0\n")
    assert any("must name its 'claim'" in p for p in validate(registry_root, ["filters/cf"]))
    write_lf(flt, "format: 0\nclaim: cold-fusion\n")
    assert any("has no registry/events" in p for p in validate(registry_root, ["filters/cf"]))
    write_lf(registry_root / "registry" / "events" / "cold-fusion.yaml", "format: 0\n")
    assert validate(registry_root, ["filters/cf", "events/cold-fusion"]) == []


def test_per_file_components_need_a_format_key(registry_root):
    write_lf(registry_root / "registry" / "predictions" / "pilot.yaml", "claims: []\n")
    assert any("'format' key" in p for p in validate(registry_root, ["predictions/pilot"]))


def test_unknown_component_name_is_reported(registry_root):
    assert any("unknown registry component" in p for p in validate(registry_root, ["misc"]))


def test_loader_matches_schema_and_rejects_missing_parameters(registry_root):
    schema = json.loads((registry_root / "registry" / "schemas" / "thresholds.schema.json").read_text(encoding="utf-8"))
    assert tuple(schema["properties"]["parameters"]["required"]) == PARAMETERS

    path = registry_root / "registry" / "thresholds.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    del data["parameters"]["kappa_min"]
    write_lf(path, yaml.safe_dump(data, allow_unicode=True))
    with pytest.raises(MissingParameter, match="kappa_min"):
        load_thresholds(registry_root)


def test_loader_raises_on_unset_values_and_returns_set_ones(registry_root):
    thresholds = load_thresholds(registry_root)
    assert thresholds["kappa_min"] == 0.6
    assert thresholds.parameter("w_window_years").extra["variants"]["length_years"] == [4, 7]
    with pytest.raises(UnsetParameter, match="n_min_disconfirmations"):
        thresholds.value("n_min_disconfirmations")  # fitted at calibration, so unset until M8
    with pytest.raises(KeyError):
        thresholds.parameter("not_a_parameter")
    assert "n_min_disconfirmations" in thresholds.unset()
