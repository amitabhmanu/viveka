"""Δ: symmetry read reason by reason ("Symmetry reason by reason").

For each checkable filter f, among the cluster's cited results that f applies to
(by results-blind applicability coding):

    Δ_f = (share of unfavourable ones discounted citing f) - (share of favourable ones discounted citing f)

Δ is the mean of Δ_f weighted by applicable results in both lanes; a filter whose
property never appears in one of the lanes cannot be compared and is skipped.
An uncheckable filter can only ever excuse a failure, so every use counts as
asymmetric: its contribution is its share of unfavourable cited results, with
nothing subtracted, weighted by the number of unfavourable cited results.

Positive Δ is asymmetry in favour of ``side``; negative means harsher on it.
A cluster with no registered filters has discounted nothing: Δ = 0. When filters
exist but none can be evaluated, Δ is None (not computable).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from viveka.measures.types import Applies, Filter, ResultItem, Side, Stance


def delta(
    results: Sequence[ResultItem],
    stance_of: Mapping[str, tuple[Stance, str | None]],
    applies_of: Mapping[tuple[str, str], Applies],
    filters: Sequence[Filter],
    side: Side,
) -> float | None:
    if side is Side.BOTH:
        raise ValueError("Δ is computed for one side at a time")
    if not filters:
        return 0.0

    cited = [r for r in results if r.cited]
    favourable = [r for r in cited if r.supports is side]
    unfavourable = [r for r in cited if r.supports is not side]

    def discounted_with(item: ResultItem, filter_id: str) -> bool:
        return stance_of.get(item.result_id, (Stance.NONE, None)) == (Stance.DISCOUNT, filter_id)

    weighted_sum = 0.0
    total_weight = 0
    for flt in sorted(filters, key=lambda f: f.filter_id):
        if flt.checkable:
            unfav_lane = [r for r in unfavourable if applies_of.get((r.result_id, flt.filter_id)) is Applies.YES]
            fav_lane = [r for r in favourable if applies_of.get((r.result_id, flt.filter_id)) is Applies.YES]
            if not unfav_lane or not fav_lane:
                continue
            rate_unfav = sum(discounted_with(r, flt.filter_id) for r in unfav_lane) / len(unfav_lane)
            rate_fav = sum(discounted_with(r, flt.filter_id) for r in fav_lane) / len(fav_lane)
            weight = len(unfav_lane) + len(fav_lane)
            weighted_sum += (rate_unfav - rate_fav) * weight
        else:
            if not unfavourable:
                continue
            weight = len(unfavourable)
            weighted_sum += sum(discounted_with(r, flt.filter_id) for r in unfavourable)
        total_weight += weight
    return weighted_sum / total_weight if total_weight else None


def uncheckable_uses_on_favourable(
    results: Sequence[ResultItem],
    stance_of: Mapping[str, tuple[Stance, str | None]],
    filters: Sequence[Filter],
    side: Side,
) -> int:
    """Diagnostic: uses of uncheckable filters against the cluster's own favourable results."""
    uncheckable = {f.filter_id for f in filters if not f.checkable}
    return sum(
        1
        for r in results
        if r.cited and r.supports is side
        and stance_of.get(r.result_id, (Stance.NONE, None))[0] is Stance.DISCOUNT
        and stance_of[r.result_id][1] in uncheckable
    )
