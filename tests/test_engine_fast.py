"""The vectorised kernel must agree with the readable reference definitions."""

import math

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from test_engine_orientation import raw_inputs

from viveka.measures import fast
from viveka.measures.delta import delta
from viveka.measures.omega import omega
from viveka.measures.side import favoured_side
from viveka.measures.types import (
    Applicability,
    Applies,
    CommitmentInputs,
    Filter,
    ResultItem,
    Side,
    Stance,
    StanceLabel,
)


def _same(a, b):
    return (a is None and b is None) or (a is not None and b is not None and math.isclose(a, b, abs_tol=1e-12))


@settings(max_examples=80, deadline=None)
@given(inputs=raw_inputs(), seed=st.integers(0, 2**32 - 1), data=st.data())
def test_fast_delta_omega_and_side_match_the_reference(inputs, seed, data):
    families = tuple(sorted({s.family for s in inputs.stances} | {a.family for a in inputs.applicability}))
    enc = fast.encode(inputs, families)
    rng = np.random.default_rng(seed)
    weights = np.array([data.draw(st.integers(0, 3)) for _ in families], dtype=float)
    category, applies = fast.aggregate(enc, weights, rng, 0.0)
    stance_of, applies_of = fast.decode(enc, category, applies)

    results = sorted(inputs.results, key=lambda r: r.result_id)
    sample = rng.integers(0, len(results), len(results)) if results else np.empty(0, dtype=int)
    sampled = [results[i] for i in sample]
    strata = data.draw(st.integers(1, 4))

    assert fast.favoured_side_fast(enc, category) is favoured_side(results, {k: v[0] for k, v in stance_of.items()})
    for side in (Side.P, Side.NOT_P):
        assert _same(fast.delta_fast(enc, sample, category, applies, side),
                     delta(sampled, stance_of, applies_of, inputs.filters, side))
        assert _same(fast.omega_fast(enc, sample, side, strata), omega(sampled, side, strata))


def _single(result_id, labels):
    """Inputs with one cited result labelled by the given {family: (stance, filter)}."""
    return CommitmentInputs(
        results=(ResultItem(result_id, Side.P, 1.0, True), ResultItem("uncited", Side.NOT_P, 2.0, False)),
        stances=tuple(StanceLabel(result_id, fam, s, fid) for fam, (s, fid) in labels.items()),
        filters=(Filter("blind", True),),
        applicability=tuple(Applicability(result_id, "blind", fam, Applies.YES) for fam in labels),
        ledger=(), members=1, coverage=1.0, window_end=2000.0,
    )


def test_majority_follows_weights_and_ties_are_uniform():
    labels = {"f1": (Stance.SUPPORT, None), "f2": (Stance.DISCOUNT, "blind")}
    inputs = _single("r", labels)
    enc = fast.encode(inputs, ("f1", "f2"))
    rng = np.random.default_rng(0)

    category, _ = fast.aggregate(enc, np.array([2.0, 0.0]), rng, 0.0)
    assert enc.categories[category[0]] == (Stance.SUPPORT, None) and category[1] == -1
    category, _ = fast.aggregate(enc, np.array([0.0, 1.0]), rng, 0.0)
    assert enc.categories[category[0]] == (Stance.DISCOUNT, "blind")

    winners = [enc.categories[fast.aggregate(enc, np.array([1.0, 1.0]), rng, 0.0)[0][0]][0] for _ in range(2000)]
    share_support = winners.count(Stance.SUPPORT) / len(winners)
    assert 0.45 < share_support < 0.55


def test_noise_flips_labels_at_the_given_rate():
    inputs = _single("r", {"f1": (Stance.SUPPORT, None)})
    enc = fast.encode(inputs, ("f1",))
    rng = np.random.default_rng(1)
    flipped = sum(enc.categories[fast.aggregate(enc, np.ones(1), rng, 0.3)[0][0]][0] is not Stance.SUPPORT
                  for _ in range(4000))
    assert abs(flipped / 4000 - 0.3) < 0.03
