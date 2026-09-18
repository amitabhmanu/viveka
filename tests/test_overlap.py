from viveka.corpus.overlap import Overlap, SubjectAuthors, community_authors, name_key, overlaps


def test_names_compare_by_family_name_and_every_initial():
    assert name_key("Jerry R. Bergman") == name_key("J. R. Bergman") == name_key("J.R. Bergman") == "bergman:jr"
    assert name_key("Jerry Bergman") == "bergman:j"  # a different key: v2 prefers missed matches to namesakes
    assert name_key("Ernst Lütz") == "lutz:e"
    assert name_key("Oard") == "oard:"
    assert name_key("  ") is None and name_key(None) is None


def frames(*works, kind="community"):
    return [{"work_id": w, "kind": kind} for w in works]


def test_core_authors_have_at_least_the_registered_number_of_community_works():
    rows = frames("W1", "W2", "W3") + frames("W9", kind="mainstream")
    authorships = [{"work_id": w, "author_id": a} for w, a in
                   [("W1", "A1"), ("W2", "A1"), ("W3", "A2"), ("W9", "A2"), ("W9", "A3"), ("W1", "A1")]]
    authors = [{"author_id": "A1", "display_name": "Ann B. Smith"}, {"author_id": "A2", "display_name": "Bob Jones"},
               {"author_id": "A3", "display_name": "Cy Lee"}]
    subject = community_authors(rows, authorships, authors, core_min_works=2)
    assert subject == SubjectAuthors(ids=frozenset({"A1"}), names=frozenset({"smith:ab"}), all_openalex=True)
    ingested = community_authors(frames("X:crsq:1", "X:crsq:2"),
                                 [{"work_id": "X:crsq:1", "author_id": "name:smith:a"},
                                  {"work_id": "X:crsq:2", "author_id": "name:smith:a"}],
                                 [{"author_id": "name:smith:a", "display_name": "Ann B. Smith"}], core_min_works=2)
    assert ingested == SubjectAuthors(ids=frozenset(), names=frozenset({"smith:ab"}), all_openalex=False)


def test_openalex_subjects_compare_by_id_and_others_by_name():
    immunology = SubjectAuthors(frozenset({"A1", "A2", "A3", "A4"}), frozenset({"smith:ab", "lee:c", "x:y", "q:r"}),
                                True)
    homeopathy = SubjectAuthors(frozenset({"A9", "A8"}), frozenset({"smith:ab", "lee:c"}), True)  # namesakes only
    creation = SubjectAuthors(frozenset(), frozenset({"smith:ab", "oard:mj"}), False)
    pairs = overlaps({"immunology": immunology, "homeopathy": homeopathy, "creation-science": creation},
                     fields={"immunology", "homeopathy", "creation-science"})
    by_pair = {(p.a, p.b): p for p in pairs}
    assert by_pair[("homeopathy", "immunology")] == Overlap("homeopathy", "immunology", "openalex_id", 2, 4, 0)
    named = by_pair[("creation-science", "immunology")]
    assert (named.basis, named.shared, named.coefficient, named.smaller) == ("name", 1, 0.5, "creation-science")
    assert Overlap("a", "b", "name", 0, 5, 0).coefficient is None
    assert overlaps({"case-1": homeopathy, "case-2": homeopathy}, fields=set()) == []
