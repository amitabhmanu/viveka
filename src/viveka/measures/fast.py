"""Vectorised label aggregation, Δ and Ω for the bootstrap.

The definitions are exactly those of ``delta.py``, ``omega.py`` and ``aggregate.py``;
those modules stay as the readable specification, and tests check that the
functions here agree with them. Labels are encoded once as one-hot arrays over
coder families, so a bootstrap draw becomes a weighted count (families drawn with
replacement give integer weights), with ties broken uniformly by adding a jitter
below one half before taking the argmax. Items are always processed in result-id
order, so no random draw ever depends on which side a result supports.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from viveka.measures.types import Applies, CommitmentInputs, Side, Stance

STANCES = (Stance.SUPPORT, Stance.AGAINST, Stance.DISCOUNT, Stance.NONE)
APPLIES = (Applies.YES, Applies.NO, Applies.CANNOT_TELL)
_DISCOUNT = STANCES.index(Stance.DISCOUNT)
_SUPPORT = STANCES.index(Stance.SUPPORT)


@dataclass(frozen=True)
class Encoded:
    families: tuple[str, ...]
    result_ids: tuple[str, ...]
    supports_p: np.ndarray  # bool [R]
    cited: np.ndarray  # bool [R]
    rank: np.ndarray  # int [R], order by (prominence, result id)
    categories: tuple[tuple[Stance, str | None], ...]  # stance label categories
    category_stance: np.ndarray  # int [K] -> index into STANCES
    plain_category: np.ndarray  # int [len(STANCES)] -> category (stance, None)
    stance_onehot: np.ndarray  # float [R, F, K]
    filter_ids: tuple[str, ...]  # sorted
    checkable: np.ndarray  # bool [G]
    discount_category: np.ndarray  # int [G] -> category (DISCOUNT, filter) or -1
    applies_onehot: np.ndarray  # float [R, G, F, 3]


def encode(inputs: CommitmentInputs, families: tuple[str, ...]) -> Encoded:
    results = sorted(inputs.results, key=lambda r: r.result_id)
    index = {r.result_id: i for i, r in enumerate(results)}
    fam_index = {f: i for i, f in enumerate(families)}
    filters = sorted(inputs.filters, key=lambda f: f.filter_id)
    filter_index = {f.filter_id: g for g, f in enumerate(filters)}

    categories: list[tuple[Stance, str | None]] = [(s, None) for s in STANCES]
    for label in inputs.stances:
        key = (label.stance, label.filter_id)
        if key not in categories:
            categories.append(key)
    for f in filters:
        if (Stance.DISCOUNT, f.filter_id) not in categories:
            categories.append((Stance.DISCOUNT, f.filter_id))
    cat_index = {c: k for k, c in enumerate(categories)}

    n_r, n_f, n_k, n_g = len(results), len(families), len(categories), len(filters)
    stance_onehot = np.zeros((n_r, n_f, n_k))
    for label in inputs.stances:
        if label.result_id in index and label.family in fam_index:
            stance_onehot[index[label.result_id], fam_index[label.family], cat_index[(label.stance,
                                                                                     label.filter_id)]] = 1.0
    applies_onehot = np.zeros((n_r, n_g, n_f, len(APPLIES)))
    for a in inputs.applicability:
        if a.result_id in index and a.filter_id in filter_index and a.family in fam_index:
            applies_onehot[index[a.result_id], filter_index[a.filter_id], fam_index[a.family],
                           APPLIES.index(a.value)] = 1.0

    order = sorted(range(n_r), key=lambda i: (results[i].prominence, results[i].result_id))
    rank = np.empty(n_r, dtype=int)
    rank[order] = np.arange(n_r)
    return Encoded(
        families=families,
        result_ids=tuple(r.result_id for r in results),
        supports_p=np.array([r.supports is Side.P for r in results], dtype=bool),
        cited=np.array([r.cited for r in results], dtype=bool),
        rank=rank,
        categories=tuple(categories),
        category_stance=np.array([STANCES.index(s) for s, _ in categories], dtype=int),
        plain_category=np.array([cat_index[(s, None)] for s in STANCES], dtype=int),
        stance_onehot=stance_onehot,
        filter_ids=tuple(f.filter_id for f in filters),
        checkable=np.array([f.checkable for f in filters], dtype=bool),
        discount_category=np.array([cat_index[(Stance.DISCOUNT, f.filter_id)] for f in filters], dtype=int),
        applies_onehot=applies_onehot,
    )


def _argmax_with_ties(counts: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Per row, the index of the largest count, ties broken uniformly; -1 where every count is zero."""
    jittered = np.where(counts > 0, counts + rng.random(counts.shape) * 0.5, -1.0)
    winner = np.argmax(jittered, axis=-1)
    return np.where(counts.sum(axis=-1) > 0, winner, -1)


def aggregate(enc: Encoded, weights: np.ndarray, rng: np.random.Generator, noise: float
              ) -> tuple[np.ndarray, np.ndarray]:
    """Majority stance category per result [R] and applicability per (result, filter) [R, G]; -1 = no label."""
    category = _argmax_with_ties(np.einsum("rfk,f->rk", enc.stance_onehot, weights), rng)
    if enc.applies_onehot.size:
        applies = _argmax_with_ties(np.einsum("rgfk,f->rgk", enc.applies_onehot, weights), rng)
    else:  # no labels at all (no results, families or filters): every (result, filter) is unlabelled
        applies = np.full((len(enc.result_ids), len(enc.filter_ids)), -1, dtype=int)

    if noise > 0:
        flip = (rng.random(category.shape) < noise) & (category >= 0)
        if flip.any():
            old = enc.category_stance[category[flip]]
            new = (old + rng.integers(1, len(STANCES), size=old.shape)) % len(STANCES)
            category = category.copy()
            category[flip] = enc.plain_category[new]
        flip_a = (rng.random(applies.shape) < noise) & (applies >= 0)
        if flip_a.any():
            applies = applies.copy()
            applies[flip_a] = (applies[flip_a] + rng.integers(1, len(APPLIES), size=int(flip_a.sum()))) % len(APPLIES)
    return category, applies


def favoured_side_fast(enc: Encoded, category: np.ndarray) -> Side:
    stance = np.where(category >= 0, enc.category_stance[np.maximum(category, 0)], -1)
    support = enc.cited & (stance == _SUPPORT)
    discount = enc.cited & (stance == _DISCOUNT)
    p = int((support & enc.supports_p).sum() + (discount & ~enc.supports_p).sum())
    not_p = int((support & ~enc.supports_p).sum() + (discount & enc.supports_p).sum())
    if p == not_p:
        return Side.BOTH
    return Side.P if p > not_p else Side.NOT_P


def delta_fast(enc: Encoded, idx: np.ndarray, category: np.ndarray, applies: np.ndarray, side: Side) -> float | None:
    if side is Side.BOTH:
        raise ValueError("Δ is computed for one side at a time")
    if not enc.filter_ids:
        return 0.0
    for_side = enc.supports_p[idx] if side is Side.P else ~enc.supports_p[idx]
    cited = enc.cited[idx]
    favourable, unfavourable = cited & for_side, cited & ~for_side
    sampled_category = category[idx]
    weighted_sum, total_weight = 0.0, 0
    for g in range(len(enc.filter_ids)):
        discounted = sampled_category == enc.discount_category[g]
        if enc.checkable[g]:
            yes = applies[idx, g] == 0
            unfav_lane, fav_lane = unfavourable & yes, favourable & yes
            n_unfav, n_fav = int(unfav_lane.sum()), int(fav_lane.sum())
            if n_unfav == 0 or n_fav == 0:
                continue
            rate_unfav = (discounted & unfav_lane).sum() / n_unfav
            rate_fav = (discounted & fav_lane).sum() / n_fav
            weight = n_unfav + n_fav
            weighted_sum += (rate_unfav - rate_fav) * weight
        else:
            weight = int(unfavourable.sum())
            if weight == 0:
                continue
            weighted_sum += float((discounted & unfavourable).sum())
        total_weight += weight
    return weighted_sum / total_weight if total_weight else None


def omega_fast(enc: Encoded, idx: np.ndarray, side: Side, strata: int) -> float | None:
    if side is Side.BOTH:
        raise ValueError("Ω is computed for one side at a time")
    n = len(idx)
    if n == 0:
        return None
    order = np.argsort(enc.rank[idx], kind="stable")
    position = np.empty(n, dtype=int)
    position[order] = np.arange(n)
    bucket = np.minimum(position * strata // n, strata - 1)
    for_side = enc.supports_p[idx] if side is Side.P else ~enc.supports_p[idx]
    cited = enc.cited[idx]
    n_fav = np.bincount(bucket[for_side], minlength=strata)
    n_unfav = np.bincount(bucket[~for_side], minlength=strata)
    cited_fav = np.bincount(bucket[for_side & cited], minlength=strata)
    cited_unfav = np.bincount(bucket[~for_side & cited], minlength=strata)
    valid = (n_fav > 0) & (n_unfav > 0)
    if not valid.any():
        return None
    return float(np.mean(cited_fav[valid] / n_fav[valid] - cited_unfav[valid] / n_unfav[valid]))


def decode(enc: Encoded, category: np.ndarray, applies: np.ndarray
           ) -> tuple[dict[str, tuple[Stance, str | None]], dict[tuple[str, str], Applies]]:
    """The aggregated labels as the dictionaries the reference functions take."""
    stance_of = {rid: enc.categories[c] for rid, c in zip(enc.result_ids, category, strict=True) if c >= 0}
    applies_of = {
        (rid, fid): APPLIES[applies[i, g]]
        for i, rid in enumerate(enc.result_ids)
        for g, fid in enumerate(enc.filter_ids)
        if applies[i, g] >= 0
    }
    return stance_of, applies_of
