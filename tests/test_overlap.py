from viveka.corpus.overlap import Overlap, community_authors, name_key, overlaps


def test_names_compare_by_family_name_and_first_initial():
    assert name_key("Jerry R. Bergman") == name_key("J. Bergman") == "bergman:j"
    assert name_key("Ernst Lütz") == "lutz:e"
    assert name_key("Oard") == "oard:"
    assert name_key("  ") is None and name_key(None) is None


def test_only_community_frames_count():
    frames = [{"work_id": "W1", "kind": "community"}, {"work_id": "W2", "kind": "mainstream"}]
    authorships = [{"work_id": "W1", "author_id": "A1"}, {"work_id": "W2", "author_id": "A2"}]
    authors = [{"author_id": "A1", "display_name": "Ann Smith"}, {"author_id": "A2", "display_name": "Bob Jones"}]
    assert community_authors(frames, authorships, authors) == {"smith:a"}


def test_overlap_coefficient_uses_the_smaller_subject():
    authors = {"homeopathy": {f"a{i}:x" for i in range(100)}, "anthroposophy": {"a1:x", "a2:x", "b:y", "c:z"},
               "cold-fusion": {"q:q"}}
    pairs = overlaps(authors, fields={"homeopathy", "anthroposophy"})
    assert [(p.a, p.b, p.shared) for p in pairs] == [("anthroposophy", "cold-fusion", 0),
                                                     ("anthroposophy", "homeopathy", 2),
                                                     ("cold-fusion", "homeopathy", 0)]
    small_in_large = pairs[1]
    assert small_in_large.coefficient == 0.5 and small_in_large.smaller == "anthroposophy"  # Jaccard would be 2/102
    assert Overlap("a", "b", 0, 5, 0).coefficient is None
    assert overlaps({"case-1": {"x:x"}, "case-2": {"x:x"}}, fields=set()) == []  # two cases are not a selection issue
