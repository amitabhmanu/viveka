"""Clusters linked over sub-windows into lineages (framework: "Communities followed as lineages").

Between consecutive sub-windows, a cluster is linked to a successor when the Jaccard overlap of their members
is at least o. Each successor keeps only its best-linked predecessor (largest overlap, then lowest cluster
index), so a lineage never has two parents:

* a cluster whose only successor it is continues its lineage;
* a cluster with two or more successors branches: its lineage ends there and each successor starts a new
  lineage whose parent it is, so both branches share its history;
* a successor with no linked predecessor starts a new lineage without a parent;
* a predecessor that is linked only to successors which chose another predecessor ends (it merged).

Clusters smaller than `min_members` are not followed. Lineage ids are numbered in order of first appearance,
so a run is deterministic.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from viveka.social.graph import Window
from viveka.social.leiden import Partition
from viveka.verdict.stability import jaccard


@dataclass(frozen=True)
class LineageStep:
    lineage_id: str
    window: Window
    cluster: int  # index in that window's partition
    members: frozenset[str]
    parent: str | None  # on a lineage's first step only
    overlap: float | None  # Jaccard with the predecessor cluster; None on a lineage's first step


def link(partitions: Sequence[tuple[Window, Partition]], o: float, min_members: int) -> list[LineageStep]:
    steps: list[LineageStep] = []
    counter = 0

    def new_id() -> str:
        nonlocal counter
        counter += 1
        return f"L{counter}"

    previous: dict[int, str] = {}  # cluster index in the previous window -> lineage id
    prev_clusters: tuple[frozenset[str], ...] = ()
    for window, partition in partitions:
        followed = [i for i, members in enumerate(partition.clusters) if len(members) >= min_members]
        owner: dict[str, int] = {a: i for i, members in enumerate(prev_clusters) if i in previous for a in members}
        best: dict[int, tuple[int, float]] = {}
        for j in followed:
            candidates = {owner[a] for a in partition.clusters[j] if a in owner}
            scored = sorted(((jaccard(prev_clusters[i], partition.clusters[j]), i) for i in candidates),
                            key=lambda t: (-t[0], t[1]))
            if scored and scored[0][0] >= o:
                best[j] = (scored[0][1], scored[0][0])
        successors: dict[int, list[int]] = defaultdict(list)
        for j, (i, _) in best.items():
            successors[i].append(j)
        current: dict[int, str] = {}
        for j in followed:
            if j not in best:
                current[j] = new_id()
                steps.append(LineageStep(current[j], window, j, partition.clusters[j], None, None))
                continue
            i, overlap = best[j]
            if len(successors[i]) == 1:
                current[j] = previous[i]
                steps.append(LineageStep(current[j], window, j, partition.clusters[j], None, overlap))
            else:
                current[j] = new_id()
                steps.append(LineageStep(current[j], window, j, partition.clusters[j], previous[i], overlap))
        previous, prev_clusters = current, partition.clusters
    return steps


def ancestry(steps: Sequence[LineageStep]) -> dict[str, str | None]:
    """Each lineage's parent (None for a root)."""
    parents: dict[str, str | None] = {}
    for step in steps:
        if step.lineage_id not in parents:
            parents[step.lineage_id] = step.parent
    return parents
