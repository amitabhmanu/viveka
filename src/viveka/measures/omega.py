"""Ω: omission asymmetry.

Results bearing on the claim are ranked by field-wide prominence (ties by result
id, so the ranking never depends on orientation) and cut into equal-count
quantile strata. In each stratum holding both favourable and unfavourable
results:

    (share of favourable results the cluster cites) - (share of unfavourable results it cites)

Ω is the mean over those strata; None if no stratum holds both kinds.
Positive Ω means the cluster leaves the other side's results uncited.
"""

from __future__ import annotations

from collections.abc import Sequence

from viveka.measures.types import ResultItem, Side


def omega(results: Sequence[ResultItem], side: Side, strata: int) -> float | None:
    if side is Side.BOTH:
        raise ValueError("Ω is computed for one side at a time")
    if strata < 1:
        raise ValueError("strata must be at least 1")
    if not results:
        return None
    ranked = sorted(results, key=lambda r: (r.prominence, r.result_id))
    buckets: list[list[ResultItem]] = [[] for _ in range(strata)]
    for rank, item in enumerate(ranked):
        buckets[min(rank * strata // len(ranked), strata - 1)].append(item)

    differences = []
    for bucket in buckets:
        favourable = [r for r in bucket if r.supports is side]
        unfavourable = [r for r in bucket if r.supports is not side]
        if favourable and unfavourable:
            cited_fav = sum(r.cited for r in favourable) / len(favourable)
            cited_unfav = sum(r.cited for r in unfavourable) / len(unfavourable)
            differences.append(cited_fav - cited_unfav)
    return sum(differences) / len(differences) if differences else None
