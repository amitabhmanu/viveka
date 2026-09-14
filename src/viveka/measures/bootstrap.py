"""Percentile bootstrap helpers: resampling, intervals, and the anchored-noise mode.

Coder families are the unit of independence (the framework's coder rules), so a
draw resamples families with replacement alongside evidence items. When the
disagreement measured on the human-anchored set exceeds what the case itself
shows, a draw instead keeps every family and flips aggregated labels at the
anchored rate, so coders that agree with one another cannot narrow an interval.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from itertools import combinations

import numpy as np

from viveka.measures.types import Interval


def percentile_interval(point: float | None, draws: Sequence[float | None], level: float) -> Interval | None:
    if point is None:
        return None
    values = np.array([d for d in draws if d is not None], dtype=float)
    if values.size == 0:
        return None
    alpha = (1.0 - level) / 2.0
    lower, upper = np.quantile(values, [alpha, 1.0 - alpha])
    return Interval(float(point), float(lower), float(upper), int(values.size))


def resample_indices(rng: np.random.Generator, n: int) -> np.ndarray:
    return rng.integers(0, n, n) if n > 0 else np.empty(0, dtype=int)


def resample_families(rng: np.random.Generator, families: Sequence[str]) -> list[str]:
    if not families:
        return []
    return [families[i] for i in rng.integers(0, len(families), len(families))]


def observed_disagreement(labels_by_item: Mapping[str, Mapping[str, Hashable]]) -> float:
    """Mean share of disagreeing family pairs, over items labelled by at least two families."""
    rates = []
    for by_family in labels_by_item.values():
        values = [by_family[f] for f in sorted(by_family)]
        if len(values) < 2:
            continue
        pairs = list(combinations(values, 2))
        rates.append(sum(a != b for a, b in pairs) / len(pairs))
    return float(np.mean(rates)) if rates else 0.0


def perturb[T: Hashable](value: T, options: Sequence[T], rate: float, rng: np.random.Generator) -> T:
    """With probability ``rate`` replace ``value`` by a different option chosen uniformly."""
    if rate <= 0 or rng.random() >= rate:
        return value
    others = sorted((o for o in options if o != value), key=str)
    return others[int(rng.integers(len(others)))] if others else value
