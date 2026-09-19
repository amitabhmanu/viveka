"""Author graphs per sub-window, built from a case's S1 tables.

Nodes are the authors of the works published in the sub-window (OpenAlex author ids; ingested venues' authors
by name key). Edges are undirected and weighted:

* co-authorship: each work with k >= 2 authors adds 1/(k-1) to every pair of its authors, so a paper gives
  each author a total weight of 1 however many co-authors it has;
* citation: each citation from a work in the sub-window to another corpus work adds 1/(a*b) to every pair of
  a citing author and a cited author (a and b authors), counted only when both are active in the sub-window.

Self-ties (an author citing their own work, or listed twice) are dropped. The graph is a plain mapping, so it
is pure and testable without a graph library.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Window:
    start: int
    end: int  # inclusive

    def __contains__(self, year: object) -> bool:
        return isinstance(year, int) and self.start <= year <= self.end

    @property
    def label(self) -> str:
        return f"{self.start}-{self.end}"


@dataclass(frozen=True)
class AuthorGraph:
    window: Window
    nodes: tuple[str, ...]  # sorted
    edges: dict[tuple[str, str], float]  # (a, b) with a < b

    def weight(self, a: str, b: str) -> float:
        return self.edges.get((a, b) if a < b else (b, a), 0.0)


def windows(start: int, end: int, length: int) -> list[Window]:
    """Sub-windows of `length` years stepped yearly across [start, end]; one window if the span is shorter."""
    if length < 1:
        raise ValueError("a sub-window is at least one year long")
    if end - start + 1 <= length:
        return [Window(start, end)]
    return [Window(s, s + length - 1) for s in range(start, end - length + 2)]


def authors_by_work(authorships: Iterable[tuple[str, str]]) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for work_id, author_id in authorships:
        if author_id and author_id not in grouped[work_id]:
            grouped[work_id].append(author_id)
    return {work: tuple(sorted(authors)) for work, authors in grouped.items()}


def build_graph(window: Window, years: Mapping[str, int | None], authors: Mapping[str, tuple[str, ...]],
                citations: Iterable[tuple[str, str]]) -> AuthorGraph:
    """The author graph of one sub-window."""
    in_window = [work for work, year in years.items() if year in window]
    active = sorted({a for work in in_window for a in authors.get(work, ())})
    edges: dict[tuple[str, str], float] = defaultdict(float)

    def add(a: str, b: str, weight: float) -> None:
        if a != b:
            edges[(a, b) if a < b else (b, a)] += weight

    for work in in_window:
        team = authors.get(work, ())
        if len(team) >= 2:
            for i, a in enumerate(team):
                for b in team[i + 1:]:
                    add(a, b, 1.0 / (len(team) - 1))
    active_set = set(active)
    window_works = set(in_window)
    for citing, cited in citations:
        if citing not in window_works or citing == cited:
            continue
        citing_team = [a for a in authors.get(citing, ()) if a in active_set]
        cited_team = [a for a in authors.get(cited, ()) if a in active_set]
        if not citing_team or not cited_team:
            continue
        share = 1.0 / (len(authors[citing]) * len(authors[cited]))
        for a in citing_team:
            for b in cited_team:
                add(a, b, share)
    return AuthorGraph(window, tuple(active), dict(sorted(edges.items())))
