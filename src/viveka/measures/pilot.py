"""The descriptive pilot of decision D-29: how a community's stance differs between results for and against its claim.

Not a framework measure and never a verdict: Δ needs filters and applicability, Ω needs the directions of results
the community did not cite. For each coder, its own direction labels are paired with its own stance labels:

* shares of the stance labels (+, x, -, none) on contexts citing results the coder calls ``for`` the claim, and on
  those it calls ``against``;
* D0 = discounted share on ``against`` minus discounted share on ``for``;
* A0 = accepted share on ``for`` minus accepted share on ``against``.

Both are positive when evidence in the claim's favour is treated more kindly. Point estimates average the coders;
percentile intervals resample cited results (each with all its contexts) and coders, as intervals do (D-21).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from viveka.measures.bootstrap import percentile_interval, resample_families
from viveka.measures.types import Interval

STANCES = ("+", "x", "-", "none")
DIRECTIONS = ("for", "against")


@dataclass(frozen=True)
class StanceRow:
    item_id: str
    result_id: str
    coder: str
    stance: str


@dataclass(frozen=True)
class PilotResult:
    coders: tuple[str, ...]
    shares: dict[str, dict[str, dict[str, float | None]]]  # coder -> direction -> stance -> share
    items: dict[str, dict[str, int]]  # coder -> direction -> stance items on results of that direction
    d0: Interval | None
    a0: Interval | None


def _counts(rows: Sequence[StanceRow], direction: Mapping[tuple[str, str], str], coder: str,
            weights: Mapping[str, int] | None = None) -> dict[str, dict[str, float]]:
    counts = {d: dict.fromkeys(STANCES, 0.0) for d in DIRECTIONS}
    for row in rows:
        if row.coder != coder:
            continue
        d = direction.get((coder, row.result_id))
        if d in counts and row.stance in counts[d]:
            counts[d][row.stance] += 1.0 if weights is None else weights.get(row.result_id, 0)
    return counts


def _share(counts: Mapping[str, float], stance: str) -> float | None:
    total = sum(counts.values())
    return counts[stance] / total if total else None


def _d0_a0(counts: Mapping[str, Mapping[str, float]]) -> tuple[float | None, float | None]:
    x_against, x_for = _share(counts["against"], "x"), _share(counts["for"], "x")
    p_for, p_against = _share(counts["for"], "+"), _share(counts["against"], "+")
    d0 = None if x_against is None or x_for is None else x_against - x_for
    a0 = None if p_for is None or p_against is None else p_for - p_against
    return d0, a0


def _mean(values: Sequence[float | None]) -> float | None:
    kept = [v for v in values if v is not None]
    return float(np.mean(kept)) if kept else None


def pilot(rows: Sequence[StanceRow], direction: Mapping[tuple[str, str], str], *, draws: int, seed: int,
          level: float = 0.95) -> PilotResult:
    """``direction`` maps (coder, result id) to that coder's T7 label; ``rows`` are T1 labels with their results."""
    coders = tuple(sorted({r.coder for r in rows}))
    per_coder = {c: _counts(rows, direction, c) for c in coders}
    shares = {c: {d: {s: _share(per_coder[c][d], s) for s in STANCES} for d in DIRECTIONS} for c in coders}
    items = {c: {d: int(sum(per_coder[c][d].values())) for d in DIRECTIONS} for c in coders}
    points = [_d0_a0(per_coder[c]) for c in coders]
    d0, a0 = _mean([p[0] for p in points]), _mean([p[1] for p in points])

    results = sorted({r.result_id for r in rows})
    rng = np.random.default_rng(seed)
    d0_draws, a0_draws = [], []
    for _ in range(draws):
        picked = rng.integers(0, len(results), len(results)) if results else []
        weights: dict[str, int] = {}
        for i in picked:
            weights[results[i]] = weights.get(results[i], 0) + 1
        drawn = [_d0_a0(_counts(rows, direction, c, weights)) for c in resample_families(rng, list(coders))]
        d0_draws.append(_mean([p[0] for p in drawn]))
        a0_draws.append(_mean([p[1] for p in drawn]))
    return PilotResult(coders, shares, items, percentile_interval(d0, d0_draws, level),
                       percentile_interval(a0, a0_draws, level))
