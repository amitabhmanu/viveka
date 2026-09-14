import numpy as np
from engine_builders import commitment, iv, measures, oriented, params
from hypothesis import given, settings
from hypothesis import strategies as st

from viveka.measures.evaluate import measure_commitment
from viveka.measures.types import Interval, Side
from viveka.verdict.gates import primary_reading, verdict
from viveka.verdict.reasons import Reading, Reason, Verdict, VerdictResult

# ---------------------------------------------------------------- every reason is reachable


def test_closed_and_out_of_scope_return_before_the_gates_even_with_nonsense_measures():
    nonsense = measures(members=-1, coverage=-5.0, oriented=())
    assert verdict(measures(trajectory_closed=True, members=-1, oriented=()), params()) == VerdictResult(Verdict.CLOSED)
    assert verdict(measures(cites_observation=False, members=-1, oriented=()), params()).verdict is Verdict.OUT_OF_SCOPE
    assert verdict(nonsense, params()).reason is Reason.INSUFFICIENT_DATA


def test_insufficient_data_names_every_shortfall():
    result = verdict(measures(n_disconfirmations=0, coverage=0.2), params())
    assert result.reason is Reason.INSUFFICIENT_DATA
    assert "disconfirmations" in result.note and "coverage" in result.note


def test_healthy_insulated_and_unclear_readings():
    p = params()
    assert verdict(measures(), p).verdict is Verdict.HEALTHY
    insulated = measures(oriented=(oriented(delta=iv(0.4, 0.9), loop=iv(3.0, 6.0)),))
    assert verdict(insulated, p).verdict is Verdict.INSULATED

    away = verdict(measures(oriented=(oriented(delta=iv(-0.9, -0.4)),)), p)
    assert away.reason is Reason.READING_UNCLEAR and "points away" in away.note
    short_loop = verdict(measures(oriented=(oriented(delta=iv(0.4, 0.9), loop=iv(1.0, 4.0)),)), p)
    assert "without a loop" in short_loop.note
    long_loop = verdict(measures(oriented=(oriented(share=iv(0.5, 0.9), loop=iv(3.0, 5.0)),)), p)
    assert "without asymmetry" in long_loop.note
    straddle = verdict(measures(oriented=(oriented(omega=iv(0.1, 0.3)),)), p)
    assert "straddles" in straddle.note


def test_missing_interval_is_not_computable():
    o = oriented()
    o = type(o)(o.side, None, o.omega, o.insulating_share, o.loop_length)
    result = verdict(measures(oriented=(o,)), params())
    assert result.reason is Reason.READING_UNCLEAR and "not computable: Δ" in result.note


def test_conduct_check_conflict_and_corroboration():
    p = params()
    conflict = verdict(measures(tau=iv(0.1, 0.4), tau_measurable=True), p)
    assert conflict.reason is Reason.CONDUCT_CONFLICT and "τ points to A" in conflict.note
    corroborated = verdict(measures(tau=iv(0.9, 1.1), tau_measurable=True,
                                    honoured=iv(0.6, 0.9), honoured_measurable=True), p)
    assert corroborated.verdict is Verdict.HEALTHY and corroborated.corroboration == ("τ", "H")
    unmeasurable = verdict(measures(tau=iv(0.1, 0.4), tau_measurable=False), p)
    assert unmeasurable.verdict is Verdict.HEALTHY
    straddling = verdict(measures(tau=iv(0.5, 1.1), tau_measurable=True), p)
    assert straddling.verdict is Verdict.HEALTHY and straddling.corroboration == ()


def test_both_sides_require_s_on_both_orientations():
    p = params()
    both_s = measures(favoured_side=Side.BOTH, oriented=(oriented(Side.P), oriented(Side.NOT_P)))
    assert verdict(both_s, p).verdict is Verdict.HEALTHY
    one_a = measures(favoured_side=Side.BOTH,
                     oriented=(oriented(Side.P), oriented(Side.NOT_P, delta=iv(0.4, 0.8), loop=iv(3, 5))))
    result = verdict(one_a, p)
    assert result.verdict is Verdict.INSULATED and result.favoured_side is Side.NOT_P
    one_unclear = measures(favoured_side=Side.BOTH,
                           oriented=(oriented(Side.P), oriented(Side.NOT_P, share=iv(0.2, 0.5))))
    assert verdict(one_unclear, p).reason is Reason.READING_UNCLEAR


def test_healthy_and_insulated_built_commitments_end_to_end():
    p = params()
    h = verdict(measure_commitment(commitment("healthy"), p, np.random.default_rng(11)), p)
    i = verdict(measure_commitment(commitment("insulated"), p, np.random.default_rng(11)), p)
    assert h.verdict is Verdict.HEALTHY and h.corroboration == ("τ",)
    assert i.verdict is Verdict.INSULATED and i.corroboration == ("τ",)


def test_same_interval_level_serves_both_readings():
    # One level, one set of intervals: widening the level can only move a verdict toward indeterminate,
    # for healthy and insulated alike.
    narrow, wide = params(interval_level=0.5), params(interval_level=0.999)
    for kind, expected in (("healthy", Verdict.HEALTHY), ("insulated", Verdict.INSULATED)):
        for p in (narrow, wide):
            result = verdict(measure_commitment(commitment(kind), p, np.random.default_rng(5)), p)
            assert result.verdict in (expected, Verdict.INDETERMINATE)


# ---------------------------------------------------------------- property: exactly one consistent outcome

_bound = st.floats(-2.0, 2.0, allow_nan=False)


@st.composite
def _intervals(draw):
    if draw(st.booleans()) and draw(st.booleans()):
        return None
    lower = draw(_bound)
    upper = lower + draw(st.floats(0.0, 2.0, allow_nan=False))
    return Interval(lower, lower, upper, 10)


@st.composite
def _measures_and_params(draw):
    side = draw(st.sampled_from(list(Side)))
    sides = [Side.P, Side.NOT_P] if side is Side.BOTH else [side]
    oriented_measures = tuple(oriented(s, draw(_intervals()), draw(_intervals()), draw(_intervals()),
                                       draw(_intervals())) for s in sides)
    # oriented() replaces None with defaults; restore genuine Nones half the time
    if draw(st.booleans()):
        o = oriented_measures[0]
        oriented_measures = (type(o)(o.side, None, o.omega, o.insulating_share, o.loop_length), *oriented_measures[1:])
    m = measures(
        trajectory_closed=draw(st.booleans()) and draw(st.booleans()),
        cites_observation=not (draw(st.booleans()) and draw(st.booleans())),
        n_disconfirmations=draw(st.integers(0, 10)), members=draw(st.integers(0, 20)),
        citations_on_claim=draw(st.integers(0, 30)), coverage=draw(st.floats(0, 1)),
        favoured_side=side, oriented=oriented_measures,
        tau=draw(_intervals()), tau_measurable=draw(st.booleans()),
        honoured=draw(_intervals()), honoured_measurable=draw(st.booleans()),
    )
    p = params(n=draw(st.integers(0, 5)), m=draw(st.integers(0, 10)), v=draw(st.integers(0, 10)),
               r=draw(st.floats(0, 1)), delta=draw(st.floats(0, 1)), c=draw(st.floats(0, 1)),
               k=draw(st.floats(0, 5)), t=draw(st.floats(0, 1.5)), h=draw(st.floats(0, 1)))
    return m, p


@settings(max_examples=300, deadline=None)
@given(_measures_and_params())
def test_every_combination_yields_exactly_one_consistent_outcome(case):
    m, p = case
    result = verdict(m, p)
    assert isinstance(result, VerdictResult)
    if m.trajectory_closed:
        assert result.verdict is Verdict.CLOSED
        return
    if not m.cites_observation:
        assert result.verdict is Verdict.OUT_OF_SCOPE
        return
    shortfall = m.n_disconfirmations < p.n or m.members < p.m or m.citations_on_claim < p.v or m.coverage < p.r
    if shortfall:
        assert result.reason is Reason.INSUFFICIENT_DATA
        return
    reading, _, _ = primary_reading(m, p)
    if reading is Reading.UNCLEAR:
        assert result.reason is Reason.READING_UNCLEAR
    elif result.verdict is Verdict.INDETERMINATE:
        assert result.reason is Reason.CONDUCT_CONFLICT
    else:
        assert (result.verdict, reading) in ((Verdict.HEALTHY, Reading.S), (Verdict.INSULATED, Reading.A))
    if reading is Reading.S and len(m.oriented) == 1:
        o = m.oriented[0]
        assert o.delta.lower >= -p.delta and o.delta.upper <= p.delta
        assert o.omega.lower >= -p.delta and o.omega.upper <= p.delta and o.insulating_share.upper < p.c
    if reading is Reading.A and len(m.oriented) == 1:
        o = m.oriented[0]
        assert (o.delta is not None and o.delta.lower > p.delta) or (o.omega is not None and o.omega.lower > p.delta)
        assert o.loop_length.lower >= p.k
