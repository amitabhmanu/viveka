"""The descriptive pilot of decision D-29."""

import pytest

from viveka.measures.pilot import StanceRow, pilot


def _rows(coder, spec):
    """spec: result id -> list of stance labels on contexts citing it."""
    return [StanceRow(f"{coder}-{r}-{i}", r, coder, s) for r, labels in spec.items() for i, s in enumerate(labels)]


def test_harsher_on_evidence_against_gives_positive_d0_and_a0():
    rows = _rows("a", {"f1": ["+", "+"], "f2": ["+", "none"], "g1": ["x", "+"], "g2": ["x", "none"]})
    direction = {("a", "f1"): "for", ("a", "f2"): "for", ("a", "g1"): "against", ("a", "g2"): "against"}
    out = pilot(rows, direction, draws=200, seed=1)
    assert out.shares["a"]["for"]["+"] == pytest.approx(0.75)
    assert out.shares["a"]["against"]["x"] == pytest.approx(0.5)
    assert out.d0.point == pytest.approx(0.5)
    assert out.a0.point == pytest.approx(0.5)
    assert out.items["a"] == {"for": 4, "against": 4}
    assert out.d0.lower <= out.d0.point <= out.d0.upper


def test_reversing_every_direction_reverses_the_signs():
    rows = _rows("a", {"f1": ["+", "+"], "g1": ["x", "none"]})
    direction = {("a", "f1"): "for", ("a", "g1"): "against"}
    flipped = {k: {"for": "against", "against": "for"}[v] for k, v in direction.items()}
    one, two = pilot(rows, direction, draws=50, seed=2), pilot(rows, flipped, draws=50, seed=2)
    assert one.d0.point == pytest.approx(-two.d0.point)
    assert one.a0.point == pytest.approx(-two.a0.point)


def test_each_coder_uses_its_own_directions_and_results_without_one_are_ignored():
    rows = _rows("a", {"r": ["x"], "s": ["+"], "n": ["x"]}) + _rows("b", {"r": ["x"], "s": ["+"]})
    direction = {("a", "r"): "against", ("a", "s"): "for", ("a", "n"): "not_bearing",
                 ("b", "r"): "for", ("b", "s"): "against"}
    out = pilot(rows, direction, draws=50, seed=3)
    assert out.coders == ("a", "b")
    assert out.items["a"] == {"for": 1, "against": 1}
    assert out.d0.point == pytest.approx((1.0 + -1.0) / 2)


def test_no_directed_results_gives_no_estimate():
    rows = _rows("a", {"r": ["+"]})
    out = pilot(rows, {("a", "r"): "cannot_tell"}, draws=10, seed=4)
    assert out.d0 is None and out.a0 is None
