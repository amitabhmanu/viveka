import pytest
from conftest import write_lf

from viveka.hashing import tree_hash
from viveka.registry import components as comp
from viveka.registry.errors import UnknownComponent


@pytest.mark.parametrize(
    ("path", "component"),
    [
        ("registry/thresholds.yaml", "thresholds"),
        ("registry/instrument.yaml", "instrument"),
        ("registry/corpus.yaml", "corpus"),
        ("registry/cases/fifth-force.yaml", "cases/fifth-force"),
        ("registry/schemas/thresholds.schema.json", "schemas"),
        ("registry/codebook/stance/rules.md", "codebook"),
        ("registry/prompts/t1.md", "prompts"),
        ("registry/events/cold-fusion.yaml", "events/cold-fusion"),
        ("registry/filters/cf_p1.yaml", "filters/cf_p1"),
        ("registry/predictions/pilot.yaml", "predictions/pilot"),
        ("registry/redaction/fifth-force.yaml", "redaction/fifth-force"),
        ("registry/FROZEN.json", None),
        ("registry/codebook/.gitkeep", None),
        ("registry/notes.txt", None),
        ("registry/events/sub/x.yaml", None),
        ("registry/events/Upper.yaml", None),
        ("registry/filters/x.json", None),
        ("docs/x.yaml", None),
    ],
)
def test_component_of(path, component):
    assert comp.component_of(path) == component


@pytest.mark.parametrize("name", ["thresholds", "codebook", "events/cold-fusion", "filters/cf_p1"])
def test_valid_names(name):
    comp.validate_name(name)


@pytest.mark.parametrize("name", ["", "registry", "events", "events/", "events/Upper", "misc/x", "codebook/x"])
def test_invalid_names(name):
    with pytest.raises(UnknownComponent):
        comp.validate_name(name)


def test_discover_and_orphans(registry_root):
    write_lf(registry_root / "registry" / "notes.txt", "x")
    found = set(comp.discover(registry_root))
    assert {"thresholds", "instrument", "schemas", "simulation", "corpus"} <= found
    singles = {"thresholds", "instrument", "schemas", "simulation", "corpus"}
    assert all(name.startswith(("events/", "cases/", "fields/")) for name in found - singles)
    assert comp.orphans(registry_root) == ["registry/notes.txt"]


def test_upstream_follows_a_filters_claim(registry_root):
    write_lf(registry_root / "registry" / "events" / "cold-fusion.yaml", "format: 0\n")
    write_lf(registry_root / "registry" / "filters" / "cf.yaml", "format: 0\nclaim: cold-fusion\n")
    assert comp.with_upstream(registry_root, ["filters/cf"]) == ["codebook", "events/cold-fusion", "filters/cf"]
    assert comp.with_upstream(registry_root, ["prompts"]) == ["codebook", "schemas", "prompts"]
    candidates = ["prompts", "filters/cf", "thresholds"]
    assert comp.downstream(registry_root, "codebook", candidates) == ["prompts", "filters/cf"]


def test_tree_hash_is_order_independent_and_sensitive():
    a = {"registry/a": "sha256:" + "1" * 64, "registry/b": "sha256:" + "2" * 64}
    assert tree_hash(a) == tree_hash(dict(reversed(list(a.items()))))
    assert tree_hash(a) != tree_hash({**a, "registry/b": "sha256:" + "3" * 64})
    assert tree_hash(a) != tree_hash({"registry/a2": a["registry/a"], "registry/b": a["registry/b"]})
    assert tree_hash(a) != tree_hash({"registry/a": a["registry/a"]})
