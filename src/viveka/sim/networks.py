"""Edge-level corpora with planted communities, for testing community detection and lineage tracking.

A community is a pool of author ids active over a span of years. Each year it publishes papers written by 2-4
of its members, with a registered chance of one outside co-author, and each paper cites earlier papers,
mostly from its own community. The output has the shape of the S1 tables (works with years, authorships,
citations), so the social layer runs on it exactly as on a real case.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class PlantedCommunity:
    name: str
    members: tuple[str, ...]
    start: int
    end: int  # inclusive
    papers_per_year: int = 12


@dataclass
class PlantedCorpus:
    years: dict[str, int] = field(default_factory=dict)
    authorships: list[tuple[str, str]] = field(default_factory=list)
    citations: list[tuple[str, str]] = field(default_factory=list)
    community_of: dict[str, str] = field(default_factory=dict)  # work -> community


def plant(communities: Sequence[PlantedCommunity], seed: int, outsider_share: float = 0.05,
          cite_inside: float = 0.9, cites_per_paper: int = 4) -> PlantedCorpus:
    rng = np.random.default_rng(seed)
    corpus = PlantedCorpus()
    everyone = sorted({m for c in communities for m in c.members})
    by_community: dict[str, list[str]] = {c.name: [] for c in communities}
    first = min(c.start for c in communities)
    last = max(c.end for c in communities)
    counter = 0
    for year in range(first, last + 1):
        for community in communities:
            if not community.start <= year <= community.end:
                continue
            for _ in range(community.papers_per_year):
                counter += 1
                work = f"W{counter}"
                size = int(rng.integers(2, 5))
                team = list(rng.choice(community.members, size=min(size, len(community.members)), replace=False))
                if rng.random() < outsider_share:
                    team.append(str(rng.choice(everyone)))
                corpus.years[work] = year
                corpus.community_of[work] = community.name
                corpus.authorships += [(work, str(a)) for a in dict.fromkeys(team)]
                earlier_inside = [w for w in by_community[community.name] if corpus.years[w] < year]
                earlier_all = [w for w, y in corpus.years.items() if y < year]
                for _ in range(cites_per_paper):
                    pool = earlier_inside if earlier_inside and rng.random() < cite_inside else earlier_all
                    if pool:
                        corpus.citations.append((work, str(rng.choice(pool))))
                by_community[community.name].append(work)
    return corpus
