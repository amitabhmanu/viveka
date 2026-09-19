"""The social layer: author graphs, Leiden clusters and lineages, on hand-built and planted corpora."""

from __future__ import annotations

import pytest

from viveka.sim.networks import PlantedCommunity, plant
from viveka.social.graph import Window, authors_by_work, build_graph, windows
from viveka.social.leiden import Partition, leiden
from viveka.social.lineage import ancestry, link


def test_sub_windows_step_yearly_and_a_short_span_is_one_window():
    assert windows(1989, 1995, 5) == [Window(1989, 1993), Window(1990, 1994), Window(1991, 1995)]
    assert windows(1989, 1991, 5) == [Window(1989, 1991)]
    with pytest.raises(ValueError):
        windows(1989, 1995, 0)


def test_coauthorship_is_fractional_and_citations_link_only_active_authors():
    years = {"A": 1990, "B": 1991, "C": 1980}
    authors = authors_by_work([("A", "x"), ("A", "y"), ("A", "z"), ("B", "x"), ("B", "w"), ("C", "old")])
    citations = [("B", "A"), ("B", "C"), ("A", "A")]
    g = build_graph(Window(1989, 1993), years, authors, citations)
    assert g.nodes == ("w", "x", "y", "z")
    assert g.weight("y", "z") == pytest.approx(0.5)  # three authors: 1/(3-1) per pair
    assert g.weight("w", "x") == pytest.approx(1.0 + 1 / 6)  # co-authors of B, and w cites x's paper A
    assert g.weight("w", "y") == pytest.approx(1 / 6) and g.weight("x", "x") == 0.0  # no self-ties
    assert all("old" not in pair for pair in g.edges)  # C lies outside the window, so its author is not a node


def _planted():
    a = PlantedCommunity("A", tuple(f"a{i}" for i in range(30)), 1990, 1999)
    b = PlantedCommunity("B", tuple(f"b{i}" for i in range(30)), 1990, 1999)
    return plant([a, b], seed=7, outsider_share=0.02)


def test_leiden_recovers_planted_communities_deterministically():
    corpus = _planted()
    g = build_graph(Window(1990, 1994), corpus.years, authors_by_work(corpus.authorships), corpus.citations)
    first, again = leiden(g, 1.0, seed=1), leiden(g, 1.0, seed=1)
    assert first == again
    big = [c for c in first.clusters if len(c) >= 10]
    assert len(big) == 2
    for cluster in big:
        prefixes = {author[0] for author in cluster}
        purity = max(sum(a.startswith(p) for a in cluster) for p in prefixes) / len(cluster)
        assert purity >= 0.9


def _p(*clusters: set[str]) -> Partition:
    return Partition("leiden", 1.0, tuple(frozenset(c) for c in clusters))


def test_lineages_continue_branch_start_and_end():
    w1, w2, w3 = Window(1990, 1994), Window(1991, 1995), Window(1992, 1996)
    core = {f"m{i}" for i in range(10)}
    left, right = {f"m{i}" for i in range(5)} | {"l1"}, {f"m{i}" for i in range(5, 10)} | {"r1"}
    steps = link([(w1, _p(core, {"s1", "s2", "s3"})),
                  (w2, _p(core | {"n1"}, {"t1", "t2"})),
                  (w3, _p(left, right, {"z"}))], o=0.3, min_members=2)
    by_window = {(s.window, s.cluster): s for s in steps}
    assert by_window[(w1, 0)].lineage_id == by_window[(w2, 0)].lineage_id == "L1"  # continued
    assert by_window[(w2, 0)].overlap == pytest.approx(10 / 11)
    assert by_window[(w2, 1)].lineage_id == "L3" and by_window[(w2, 1)].parent is None  # new, no link to s*
    branches = [by_window[(w3, 0)], by_window[(w3, 1)]]
    assert {b.parent for b in branches} == {"L1"} and len({b.lineage_id for b in branches}) == 2
    assert (w3, 2) not in by_window  # a cluster of one is not followed
    assert ancestry(steps)[branches[0].lineage_id] == "L1" and ancestry(steps)["L1"] is None


def test_a_merge_keeps_the_best_linked_predecessor_and_ends_the_other():
    w1, w2 = Window(1990, 1994), Window(1991, 1995)
    big, small = {f"b{i}" for i in range(8)}, {"s1", "s2", "s3", "s4"}
    steps = link([(w1, _p(big, small)), (w2, _p(big | small))], o=0.3, min_members=2)
    assert [(s.window, s.lineage_id) for s in steps] == [(w1, "L1"), (w1, "L2"), (w2, "L1")]


def test_planted_communities_are_followed_as_two_lineages_across_sliding_windows():
    corpus = _planted()
    authors = authors_by_work(corpus.authorships)
    partitions = []
    for window in windows(1990, 1999, 5):
        g = build_graph(window, corpus.years, authors, corpus.citations)
        partitions.append((window, leiden(g, 1.0, seed=1)))
    steps = link(partitions, o=0.3, min_members=10)
    lineages = {s.lineage_id for s in steps}
    assert len(lineages) == 2 and all(s.parent is None for s in steps)
    assert len(steps) == 2 * len(partitions)
