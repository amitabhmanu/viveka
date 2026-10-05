"""citations_v2 (decision D-30): numbered markers in parentheses, and reference-list numbers."""

import pytest

from viveka.coders.items import (
    CITATION_RULE,
    CITATION_RULE_V2,
    CitedNumbers,
    CitedWork,
    build_items,
    marker_numbers,
    mask_citations,
    mask_citations_v2,
)


def test_marker_numbers_expand_ranges_and_lists():
    assert marker_numbers("[3-5, 9]") == {3, 4, 5, 9}
    assert marker_numbers("(12)") == {12}
    assert marker_numbers("[29–31]") == {29, 30, 31}
    assert marker_numbers("[5-900]") == set()


def test_a_single_parenthesised_number_is_the_cited_marker():
    text = "The earlier trial (37) was judged to be of high quality despite its dropout rate."
    assert mask_citations(text, None) == (text, False)
    assert mask_citations_v2(text) == (text.replace("(37)", "[CITED]"), True)


def test_years_and_long_numbers_in_parentheses_are_not_markers():
    text = "In the cohort (2009) of patients (n = 12) the effect (1234) was absent in the trial of interest."
    assert mask_citations_v2(text) == (text, False)


def test_reference_numbers_pick_the_cited_marker_among_several():
    text = "Dissonance in our work [11, 12] could reflect diversity in the profession [15] as shown before (3)."
    assert mask_citations_v2(text) == (text.replace("[11, 12]", "[REF]").replace("[15]", "[REF]")
                                       .replace("(3)", "[REF]"), False)
    masked, placed = mask_citations_v2(text, CitedNumbers(frozenset({12}), 40))
    assert placed and masked == ("Dissonance in our work [CITED] could reflect diversity in the profession [REF] "
                                 "as shown before [REF].")


def test_numbers_are_ignored_when_a_marker_exceeds_the_list():
    text = "Shown before [4] and again [55] in later work on the same question by others."
    assert mask_citations_v2(text, CitedNumbers(frozenset({4}), 30))[1] is False
    assert mask_citations_v2(text, CitedNumbers(frozenset({4}), 60))[1] is True


def test_v2_adds_items_and_leaves_v1_items_as_they_were():
    cited = {"W1": CitedWork("W1", "Smith", 1999), "W2": CitedWork("W2", "Jones", 2001)}
    rows = [
        {"cited_work": "W1", "citing_work": "C1", "citing_doi": "10.1/a",
         "text": "As Smith et al. (1999) showed, the effect is absent in the larger trials of this kind."},
        {"cited_work": "W2", "citing_work": "C1", "citing_doi": "10.1/a",
         "text": "The second trial (7) found the same absence of effect in a larger group of patients."},
        {"cited_work": "W2", "citing_work": "C2", "citing_doi": "10.1/b",
         "text": "Two reviews [3] and one trial [9] found no effect in the larger group of patients."},
    ]
    v1, dropped1 = build_items(rows, cited, lambda t: t)
    v2, dropped2 = build_items(rows, cited, lambda t: t, rule=CITATION_RULE_V2,
                               numbers={("C2", "W2"): CitedNumbers(frozenset({9}), 20)})
    assert len(v1) == 1 and dropped1["unresolved"] == 2
    assert len(v2) == 3 and dropped2["unresolved"] == 0
    assert {i.item_id for i in v1} == {i.item_id for i in v2 if i.rule == CITATION_RULE}
    assert sum(i.rule == CITATION_RULE_V2 for i in v2) == 2
    assert any("one trial [CITED]" in i.text and "[REF]" in i.text for i in v2)
    with pytest.raises(ValueError):
        build_items(rows, cited, lambda t: t, rule="citations_v9")
