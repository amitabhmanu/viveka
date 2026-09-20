import pytest
from corpus_fakes import FIELD_YAML, write_field

from viveka.cases import CaseError, bearing_set, load_subject
from viveka.registry import components as comp
from viveka.registry.validate import validate

NO_FRAMES = FIELD_YAML.replace("frames:\n  - {id: venues, kind: community, sources: [S5]}\n", "frames: []\n")


def test_a_valid_field(registry_root):
    write_field(registry_root)
    assert validate(registry_root, ["fields/test-field"]) == []
    field, claim = load_subject(registry_root, "test-field", True)
    assert claim is None and field.seeds == () and field.is_field and field.component == "fields/test-field"
    assert (field.role, field.pair, field.start, field.end) == ("calibration", "pseudoscience", 1989, 2000)
    assert [(f.frame_id, f.kind, f.cites_seeds, f.sources) for f in field.frames] == [
        ("venues", "community", False, ("S5",))]
    assert field.absent_venues == ("An unindexed bulletin: Not an OpenAlex source.",)
    assert bearing_set(field, claim) == ()


def test_a_field_without_indexed_venues_is_valid(registry_root):
    write_field(registry_root, NO_FRAMES)
    assert validate(registry_root, ["fields/test-field"]) == []
    field, _ = load_subject(registry_root, "test-field", True)
    assert field.frames == () and len(field.absent_venues) == 1


def test_field_upstream_is_the_corpus_only(registry_root):
    write_field(registry_root)
    assert comp.component_of("registry/fields/test-field.yaml") == "fields/test-field"
    assert comp.with_upstream(registry_root, ["fields/test-field"]) == ["schemas", "corpus", "fields/test-field"]


def test_a_field_carries_its_commitments_and_their_claims(registry_root):
    from conftest import write_lf

    from viveka.cases import load_commitment

    events = ('format: 1\nclaim: p-holds\nwording: "p holds."\nevents:\n'
              '  - id: e1\n    date: "1991"\n    kind: disconfirmation\n'
              "    works: [{openalex: W9}]\n"
              '    note: "A result against p."\n    source: "Lookup."\n')
    write_lf(registry_root / "registry" / "events" / "p-holds.yaml", events)
    write_field(registry_root, FIELD_YAML.replace("format: 1", "format: 2").rstrip("\n")
                + "\ncommitments:\n  - id: c1\n    claim: p-holds\n    seeds: [{openalex: W1}]\n"
                  '    note: "The work the community cites as support."\n')
    assert validate(registry_root, ["fields/test-field"]) == []
    field, claim = load_subject(registry_root, "test-field", True)
    assert claim is None and [c.commitment_id for c in field.commitments] == ["c1"]
    case, claim = load_commitment(registry_root, "test-field", "c1")
    assert case.claim == "p-holds" and case.seeds[0].openalex == "W1" and len(claim.events) == 1
    assert case.frames == field.frames and case.component == "fields/test-field"
    assert "events/p-holds" in comp.with_upstream(registry_root, ["fields/test-field"])
    with pytest.raises(CaseError, match="no commitment"):
        load_commitment(registry_root, "test-field", "missing")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (FIELD_YAML.replace("field: test-field", "field: other"), "must match the file name"),
        (FIELD_YAML.replace("{start: 1989, end: 2000}", "{start: 2001, end: 2000}"), "starts after"),
        (FIELD_YAML.replace("sources: [S5]}", "cites: seeds}"), "frames"),
        (FIELD_YAML.replace("side: pseudoscience", "side: contested"), "side"),
        (FIELD_YAML.replace("role: calibration", "role: pilot"), "role"),
        (FIELD_YAML[: FIELD_YAML.index("absent_venues")], "absent_venues"),
        (FIELD_YAML.replace("frames:\n", "frames:\n  - {id: venues, kind: community, sources: [S6]}\n"),
         "duplicate frame ids"),
        (NO_FRAMES.replace(FIELD_YAML[FIELD_YAML.index("absent_venues"):], "absent_venues: []\n"),
         "must list its absent venues"),
        (FIELD_YAML.replace("sources: [S5]}", "ingest: [nowhere]}"), "ingested venue 'nowhere' is not registered"),
        (FIELD_YAML.replace("kind: community, sources: [S5]}", "kind: community}"), "frames"),
        (FIELD_YAML.replace("format: 1", "format: 2"), "commitments"),  # format 2 must carry them
        (FIELD_YAML.rstrip("\n") + "\ncommitments:\n  - id: c1\n    claim: missing\n"
         '    seeds: [{openalex: W1}]\n    note: "x"\n', "commitments"),  # format 1 must not
    ],
)
def test_invalid_fields_are_reported(registry_root, text, message):
    write_field(registry_root, text)
    problems = validate(registry_root, ["fields/test-field"])
    assert any(message in p for p in problems), problems
    with pytest.raises(CaseError):
        load_subject(registry_root, "test-field", True)
