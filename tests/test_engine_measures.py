import numpy as np
import pytest
from engine_builders import FAMILIES, commitment, params

from viveka.measures.conduct import chi, honoured_share, tau
from viveka.measures.delta import delta
from viveka.measures.evaluate import measure_commitment
from viveka.measures.omega import omega
from viveka.measures.side import favoured_side
from viveka.measures.types import (
    Applies,
    CommitmentInputs,
    Filter,
    LedgerCode,
    LedgerEntry,
    ResultItem,
    Side,
    Stance,
    TieEvent,
)


def _items(spec):
    """spec: list of (result_id, supports, cited)."""
    return [ResultItem(rid, side, float(i), cited) for i, (rid, side, cited) in enumerate(spec)]


def test_delta_is_zero_when_a_filter_is_applied_equally_in_both_lanes():
    results = _items([("f1", Side.P, True), ("f2", Side.P, True), ("u1", Side.NOT_P, True), ("u2", Side.NOT_P, True)])
    stance = {"f1": (Stance.DISCOUNT, "blind"), "f2": (Stance.SUPPORT, None),
              "u1": (Stance.DISCOUNT, "blind"), "u2": (Stance.SUPPORT, None)}
    applies = {(r, "blind"): Applies.YES for r in ("f1", "f2", "u1", "u2")}
    assert delta(results, stance, applies, [Filter("blind", True)], Side.P) == 0.0


def test_delta_counts_one_lane_discounting_and_orientation_sign():
    results = _items([("f1", Side.P, True), ("u1", Side.NOT_P, True)])
    stance = {"f1": (Stance.SUPPORT, None), "u1": (Stance.DISCOUNT, "blind")}
    applies = {("f1", "blind"): Applies.YES, ("u1", "blind"): Applies.YES}
    assert delta(results, stance, applies, [Filter("blind", True)], Side.P) == 1.0
    assert delta(results, stance, applies, [Filter("blind", True)], Side.NOT_P) == -1.0


def test_uncheckable_filter_uses_count_wholly_as_asymmetric():
    results = _items([("f1", Side.P, True), ("u1", Side.NOT_P, True), ("u2", Side.NOT_P, True)])
    stance = {"f1": (Stance.SUPPORT, None), "u1": (Stance.DISCOUNT, "decline"), "u2": (Stance.SUPPORT, None)}
    assert delta(results, stance, {}, [Filter("decline", False)], Side.P) == 0.5


def test_cannot_tell_is_excluded_from_the_lanes():
    results = _items([("f1", Side.P, True), ("u1", Side.NOT_P, True), ("u2", Side.NOT_P, True)])
    stance = {"f1": (Stance.SUPPORT, None), "u1": (Stance.DISCOUNT, "blind"), "u2": (Stance.SUPPORT, None)}
    applies = {("f1", "blind"): Applies.YES, ("u1", "blind"): Applies.CANNOT_TELL, ("u2", "blind"): Applies.YES}
    assert delta(results, stance, applies, [Filter("blind", True)], Side.P) == 0.0


def test_delta_without_filters_is_zero_and_incomparable_filters_give_none():
    results = _items([("f1", Side.P, True), ("u1", Side.NOT_P, True)])
    assert delta(results, {}, {}, [], Side.P) == 0.0
    assert delta(results, {}, {("f1", "blind"): Applies.YES}, [Filter("blind", True)], Side.P) is None


def test_omega_is_zero_when_citation_is_independent_of_direction_and_positive_when_not():
    independent = _items([("a", Side.P, True), ("b", Side.NOT_P, True), ("c", Side.P, False), ("d", Side.NOT_P, False)])
    assert omega(independent, Side.P, strata=1) == 0.0
    selective = _items([("a", Side.P, True), ("b", Side.NOT_P, False), ("c", Side.P, True), ("d", Side.NOT_P, False)])
    assert omega(selective, Side.P, strata=1) == 1.0
    assert omega(selective, Side.NOT_P, strata=1) == -1.0
    assert omega(_items([("a", Side.P, True)]), Side.P, strata=1) is None


def test_favoured_side_counts_support_and_discounts_and_ties_to_both():
    results = _items([("a", Side.P, True), ("b", Side.NOT_P, True), ("c", Side.NOT_P, True)])
    assert favoured_side(results, {"a": Stance.SUPPORT, "b": Stance.SUPPORT, "c": Stance.NONE}) is Side.BOTH
    assert favoured_side(results, {"a": Stance.SUPPORT, "b": Stance.DISCOUNT, "c": Stance.SUPPORT}) is Side.P
    assert favoured_side(results, {"a": Stance.SUPPORT, "b": Stance.DISCOUNT, "c": Stance.DISCOUNT}) is Side.P
    assert favoured_side(results, {}) is Side.BOTH


def test_conduct_measures():
    assert tau([TieEvent(10, 5)], [TieEvent(10, 10)]) == 0.5
    assert tau([], [TieEvent(10, 10)]) is None
    assert honoured_share([True, False, True, True]) == 0.75
    assert chi(3, 10, coverage=0.9, r=0.7) == 0.3
    assert chi(3, 10, coverage=0.5, r=0.7) is None


def test_healthy_and_insulated_commitments_measure_as_built():
    p = params()
    healthy = measure_commitment(commitment("healthy"), p, np.random.default_rng(1))
    insulated = measure_commitment(commitment("insulated"), p, np.random.default_rng(1))

    assert healthy.favoured_side is Side.P and insulated.favoured_side is Side.P
    (h,), (i,) = healthy.oriented, insulated.oriented
    assert h.delta.point == 0.0 and h.omega.point == 0.0 and h.insulating_share.point == 0.0
    assert i.delta.lower > p.delta and i.omega.lower > p.delta
    assert i.insulating_share.point == 1.0 and i.loop_length.lower >= p.k
    assert healthy.tau.lower > p.t and insulated.tau.upper < p.t
    assert healthy.n_disconfirmations == 6 and healthy.chi == 0.3


def test_disagreement_over_one_code_splits_the_loop_across_draws():
    families = ("f1", "f2")
    codes = [LedgerCode.C] * 5
    ledger = tuple(
        LedgerEntry(f"e{n}", 1990.0 + n, Side.P,
                    {"f1": code, "f2": (LedgerCode.A if n == 2 else code)})
        for n, code in enumerate(codes)
    )
    inputs = CommitmentInputs(results=(), stances=(), filters=(), applicability=(), ledger=ledger,
                              members=5, coverage=1.0, window_end=2000.0)
    m = measure_commitment(inputs, params(bootstrap_draws=400), np.random.default_rng(7))
    (o,) = [x for x in m.oriented if x.side is Side.P]
    assert set(m.diagnostics["families"]) == set(families)
    assert o.loop_length.lower == 2.0 and o.loop_length.upper == 5.0


def test_anchored_disagreement_widens_intervals_when_coders_agree_too_well():
    inputs = commitment("healthy", families=("model-a",))
    calm = measure_commitment(inputs, params(), np.random.default_rng(3))
    anchored = measure_commitment(
        CommitmentInputs(**{**inputs.__dict__, "anchored_disagreement": 0.3}), params(), np.random.default_rng(3)
    )
    (c,), (a,) = calm.oriented, anchored.oriented
    assert anchored.diagnostics["noise_rate"] == 0.3 and calm.diagnostics["noise_rate"] == 0.0
    assert (a.delta.upper - a.delta.lower) > (c.delta.upper - c.delta.lower)


def test_measurability_of_tau_and_h():
    p = params(h0=3)
    base = commitment("healthy")
    m = measure_commitment(CommitmentInputs(**{**base.__dict__, "qualifying_breaks": (),
                                               "conditions_honoured": (True, False)}), p, np.random.default_rng(0))
    assert not m.tau_measurable and not m.honoured_measurable
    m = measure_commitment(CommitmentInputs(**{**base.__dict__, "conditions_honoured": (True, True, False)}),
                           p, np.random.default_rng(0))
    assert m.tau_measurable and m.honoured_measurable


@pytest.mark.parametrize("fam", [FAMILIES, ("solo",)])
def test_families_are_reported(fam):
    m = measure_commitment(commitment("healthy", families=fam), params(bootstrap_draws=20), np.random.default_rng(0))
    assert m.diagnostics["families"] == tuple(sorted(fam))
