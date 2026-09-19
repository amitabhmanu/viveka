"""Leiden clustering of an author graph at one resolution (Traag, Waltman and van Eck 2019).

The quality function is modularity with a resolution parameter (leidenalg's RBConfigurationVertexPartition),
run to convergence from a registered seed. Vertices enter igraph in sorted order, so a run is deterministic.
Clusters are numbered by size, largest first, ties broken by their smallest member; isolated authors form
clusters of one and are kept, so every author in the sub-window has exactly one cluster.
"""

from __future__ import annotations

from dataclasses import dataclass

import igraph as ig
import leidenalg

from viveka.social.graph import AuthorGraph

METHOD = "leiden"


@dataclass(frozen=True)
class Partition:
    method: str
    resolution: float
    clusters: tuple[frozenset[str], ...]  # largest first

    def cluster_of(self) -> dict[str, int]:
        return {author: i for i, members in enumerate(self.clusters) for author in members}


def leiden(graph: AuthorGraph, resolution: float, seed: int) -> Partition:
    if not graph.nodes:
        return Partition(METHOD, resolution, ())
    index = {author: i for i, author in enumerate(graph.nodes)}
    g = ig.Graph(n=len(graph.nodes), edges=[(index[a], index[b]) for a, b in graph.edges], directed=False)
    g.es["weight"] = list(graph.edges.values())
    found = leidenalg.find_partition(g, leidenalg.RBConfigurationVertexPartition, weights="weight",
                                     resolution_parameter=resolution, n_iterations=-1, seed=seed)
    groups: dict[int, set[str]] = {}
    for vertex, community in enumerate(found.membership):
        groups.setdefault(community, set()).add(graph.nodes[vertex])
    ordered = sorted((frozenset(members) for members in groups.values()), key=lambda m: (-len(m), min(m)))
    return Partition(METHOD, resolution, tuple(ordered))
