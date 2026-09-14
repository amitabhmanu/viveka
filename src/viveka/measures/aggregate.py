"""Majority aggregation of coder-family labels.

Families may repeat (a bootstrap draw samples families with replacement); each
occurrence is one vote. Ties are broken by the generator among the tied values,
sorted first so the outcome never depends on iteration order.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Hashable, Iterable, Sequence

import numpy as np


def majority[T: Hashable](votes: Iterable[T], rng: np.random.Generator, key: Callable[[T], str] = str) -> T | None:
    counts = Counter(votes)
    if not counts:
        return None
    top = max(counts.values())
    tied = sorted((v for v, c in counts.items() if c == top), key=key)
    if len(tied) == 1:
        return tied[0]
    return tied[int(rng.integers(len(tied)))]


def votes_for[T](families: Sequence[str], by_family: dict[str, T]) -> list[T]:
    """One vote per family occurrence, skipping families with no label."""
    return [by_family[f] for f in families if f in by_family]
