import pytest
from conftest import write_lf
from corpus_fakes import CASE_YAML, EVENTS_YAML, write_case

from viveka.cases import CaseError, WorkRef, bearing_set, load_case
from viveka.registry import components as comp
from viveka.registry.validate import validate


def test_a_valid_case_and_claim(registry_root):
    write_case(registry_root)
    assert validate(registry_root, ["corpus", "events/cold-fusion", "cases/cold-fusion"]) == []
    case, claim = load_case(registry_root, "cold-fusion")
    assert case.start == 1989 and case.seeds == (WorkRef(None, "10.1/seed", "founding claim"),)
    assert [(f.frame_id, f.kind, f.cites_seeds, f.sources) for f in case.frames] == [
        ("citing", "mainstream", True, ()), ("venue", "community", False, ("S5",))]
    assert [r.key for r in bearing_set(case, claim)] == ["10.1/seed", "W2"]


def test_case_upstream_is_corpus_and_its_claim(registry_root):
    write_case(registry_root)
    assert comp.component_of("registry/cases/cold-fusion.yaml") == "cases/cold-fusion"
    assert comp.component_of("registry/corpus.yaml") == "corpus"
    assert comp.with_upstream(registry_root, ["cases/cold-fusion"]) == [
        "schemas", "corpus", "events/cold-fusion", "cases/cold-fusion"]
    assert comp.downstream(registry_root, "corpus", ["cases/cold-fusion", "thresholds"]) == ["cases/cold-fusion"]


@pytest.mark.parametrize(
    ("events", "case", "message"),
    [
        (EVENTS_YAML.replace("claim: cold-fusion", "claim: fusion"), CASE_YAML, "must match the file name"),
        (EVENTS_YAML + EVENTS_YAML[EVENTS_YAML.index("  - id"):], CASE_YAML, "duplicate event ids"),
        (EVENTS_YAML.replace("kind: disconfirmation", "kind: rumour"), CASE_YAML, "kind"),
        (EVENTS_YAML, CASE_YAML.replace("{start: 1989, end: 2000}", "{start: 2001, end: 2000}"), "starts after"),
        (EVENTS_YAML, CASE_YAML.replace("cites: seeds}", "cites: seeds, sources: [S1]}"), "frames"),
        (EVENTS_YAML, CASE_YAML.replace("{doi: 10.1/seed, note: founding claim}", "{note: no id}"), "seeds"),
        (EVENTS_YAML, CASE_YAML.replace("role: pilot", "role: star"), "role"),
    ],
)
def test_invalid_definitions_are_reported(registry_root, events, case, message):
    write_case(registry_root, events, case)
    problems = validate(registry_root, ["events/cold-fusion", "cases/cold-fusion"])
    assert any(message in p for p in problems), problems
    with pytest.raises(CaseError):
        load_case(registry_root, "cold-fusion")


def test_case_needs_its_claim(registry_root):
    write_lf(registry_root / "registry" / "cases" / "cold-fusion.yaml", CASE_YAML)
    assert any("has no registry/events/cold-fusion.yaml" in p for p in validate(registry_root, ["cases/cold-fusion"]))
    with pytest.raises(CaseError, match="no registry/cases/fifth-force.yaml"):
        load_case(registry_root, "fifth-force")


def test_instrument_no_longer_holds_the_corpus(registry_root):
    path = registry_root / "registry" / "instrument.yaml"
    write_lf(path, path.read_text(encoding="utf-8") + "corpus: {sources: []}\n")
    assert any("corpus" in p for p in validate(registry_root, ["instrument"]))
