"""The side a community favours ("Which side a community is scored on")."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from viveka.measures.types import ResultItem, Side, Stance


def favouring_counts(results: Sequence[ResultItem], stance_of: Mapping[str, Stance]) -> dict[Side, int]:
    """Favouring citations per side: support of a result for the side, or discount-only of one against it."""
    counts = {Side.P: 0, Side.NOT_P: 0}
    for item in results:
        if not item.cited:
            continue
        stance = stance_of.get(item.result_id, Stance.NONE)
        if stance is Stance.SUPPORT:
            counts[item.supports] += 1
        elif stance is Stance.DISCOUNT:
            counts[item.supports.opposite()] += 1
    return counts


def favoured_side(results: Sequence[ResultItem], stance_of: Mapping[str, Stance]) -> Side:
    """P or NOT_P by majority of favouring citations; BOTH on an exact tie (including none at all)."""
    counts = favouring_counts(results, stance_of)
    if counts[Side.P] == counts[Side.NOT_P]:
        return Side.BOTH
    return Side.P if counts[Side.P] > counts[Side.NOT_P] else Side.NOT_P
