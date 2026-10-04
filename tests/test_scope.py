"""The coding scope of decision D-28: which lineage-windows, and which citations in them."""

import random

import pytest

from viveka.corpus import semanticscholar
from viveka.social.scope import coding_windows, eligible_windows, window_citations


def _row(lineage, start, *, resolution=1.0, m=True, v=True, r=True, closed=False):
    return {"resolution": resolution, "lineage_id": lineage, "window_start": start, "window_end": start + 4,
            "meets_m": m, "meets_v": v, "meets_r": r, "closed": closed}


def test_eligible_windows_need_every_check_at_the_resolution():
    rows = [_row("L1", 2000), _row("L1", 2001, r=None), _row("L2", 2000, v=False), _row("L3", 2000, closed=True),
            _row("L4", 2000, resolution=0.5), _row("L5", 2003, r=False), _row("L6", 1999)]
    assert eligible_windows(rows, 1.0) == [("L1", 2000, 2004), ("L6", 1999, 2003)]


def test_pseudoscience_codes_every_window_science_a_seeded_sample():
    eligible = [(f"L{i}", 2000 + i, 2004 + i) for i in range(10)]
    assert coding_windows(eligible, "pseudoscience", "x-c", per_science=3, seed=7) == eligible
    drawn = coding_windows(list(reversed(eligible)), "science", "x-c", per_science=3, seed=7)
    assert drawn == sorted(random.Random("7:x-c").sample(eligible, 3))
    assert drawn != coding_windows(eligible, "science", "y-c", per_science=3, seed=7) or len(eligible) < 4
    assert coding_windows(eligible[:2], "science", "x-c", per_science=3, seed=7) == eligible[:2]
    with pytest.raises(ValueError):
        coding_windows(eligible, "unknown", "x-c", per_science=3, seed=7)


def test_window_citations_are_members_papers_in_the_window_citing_bearing_results():
    lineages = [{"resolution": 1.0, "lineage_id": "L1", "window_start": 2000, "window_end": 2004, "cluster": 3},
                {"resolution": 1.0, "lineage_id": "L2", "window_start": 2000, "window_end": 2004, "cluster": 4}]
    members = {(1.0, 2000, 3): {"a", "b"}, (1.0, 2000, 4): {"z"}}
    years = {"w1": 2002, "w2": 2010, "w3": 2001, "w4": 2003}
    authors = {"w1": ("a",), "w2": ("b",), "w3": ("q",), "w4": ("b", "q")}
    citations = [("w1", "r1"), ("w1", "r2"), ("w1", "x"), ("w2", "r1"), ("w3", "r1"), ("w4", "w4"), ("w4", "r2")]
    rows = window_citations([("L1", 2000, 2004)], lineages, members, 1.0, years, authors, citations,
                            {"r1", "r2", "w4"})
    assert [(r["citing_work"], r["cited_work"]) for r in rows] == [("w1", "r1"), ("w1", "r2"), ("w4", "r2")]
    assert {r["lineage_id"] for r in rows} == {"L1"}


def test_abstract_text_rebuilds_word_order():
    from viveka.corpus.commands import abstract_text

    assert abstract_text({"effect": [1], "No": [0], "found": [2], "was": [3, 5], "it": [4]}) == \
        "No effect found was it was"
    assert abstract_text(None) is None
    assert abstract_text({}) is None


def test_reference_rows_carry_the_citing_paper_and_each_context():
    item = {"contexts": ["first [1]", "second [1]"], "intents": ["result", "background"], "isInfluential": True}
    rows = semanticscholar.reference_rows("10.1/x", None, "W9", item)
    assert [(r["cited_work"], r["citing_doi"], r["context_index"], r["text"]) for r in rows] == [
        ("W9", "10.1/x", 0, "first [1]"), ("W9", "10.1/x", 1, "second [1]")]
    assert rows[0]["intents"] == ["background", "result"]
    assert semanticscholar.reference_rows("10.1/x", None, "W9", {}) == []
