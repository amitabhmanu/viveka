"""Reversing a claim's registered orientation must change no measure value and no verdict."""

import numpy as np
from engine_builders import commitment, flip, params
from hypothesis import given, settings
from hypothesis import strategies as st

from viveka.measures.evaluate import measure_commitment
from viveka.measures.types import (
    Applicability,
    Applies,
    CommitmentInputs,
    Filter,
    LedgerCode,
    LedgerEntry,
    ResultItem,
    RoundInfo,
    RoundOutcome,
    Side,
    Stance,
    StanceLabel,
    TieEvent,
)
from viveka.verdict.gates import verdict
from viveka.verdict.reasons import Reason, Verdict


@st.composite
def raw_inputs(draw):
    families = draw(st.lists(st.sampled_from(["f1", "f2", "f3"]), min_size=1, max_size=3, unique=True))
    filter_specs = draw(st.lists(st.tuples(st.sampled_from(["a", "b", "c"]), st.booleans()), max_size=3,
                                 unique_by=lambda t: t[0]))
    filters = tuple(Filter(fid, checkable) for fid, checkable in filter_specs)
    results, stances, applicability = [], [], []
    for i in range(draw(st.integers(0, 12))):
        rid = f"r{i}"
        cited = draw(st.booleans())
        results.append(ResultItem(rid, draw(st.sampled_from([Side.P, Side.NOT_P])),
                                  float(draw(st.integers(0, 5))), cited))
        if cited:
            for fam in families:
                stance = draw(st.sampled_from(list(Stance)))
                reasons = [None, *[f.filter_id for f in filters]]
                fid = draw(st.sampled_from(reasons)) if stance is Stance.DISCOUNT else None
                stances.append(StanceLabel(rid, fam, stance, fid))
        for flt in filters:
            applicability += [Applicability(rid, flt.filter_id, fam, draw(st.sampled_from(list(Applies))))
                              for fam in families]
    ledger = []
    for e in range(draw(st.integers(0, 6))):
        codes = {fam: draw(st.sampled_from(list(LedgerCode))) for fam in families}
        rounds = {fam: RoundInfo("aux", draw(st.sampled_from(list(RoundOutcome))), 1990.0,
                                 draw(st.sampled_from([None, 1992.0])))
                  for fam in families if codes[fam] is LedgerCode.B}
        ledger.append(LedgerEntry(f"e{e}", float(draw(st.integers(1985, 2000))),
                                  draw(st.sampled_from([Side.P, Side.NOT_P])), codes, rounds, draw(st.booleans())))

    def ties(max_n):
        out = []
        for _ in range(draw(st.integers(0, max_n))):
            before = draw(st.integers(1, 6))
            out.append(TieEvent(before, draw(st.integers(0, before))))
        return tuple(out)

    return CommitmentInputs(
        results=tuple(results), stances=tuple(stances), filters=filters, applicability=tuple(applicability),
        ledger=tuple(ledger), members=draw(st.integers(0, 20)), coverage=draw(st.floats(0, 1)), window_end=2000.0,
        qualifying_breaks=ties(2), baseline_changes=ties(2),
        conditions_honoured=tuple(draw(st.lists(st.booleans(), max_size=4))),
        anchored_disagreement=draw(st.one_of(st.none(), st.floats(0, 0.5))),
    )


def _by_side(m, swap=False):
    return {(o.side.opposite() if swap else o.side): (o.delta, o.omega, o.insulating_share, o.loop_length)
            for o in m.oriented}


@settings(max_examples=60, deadline=None)
@given(inputs=raw_inputs(), seed=st.integers(0, 2**32 - 1), level=st.sampled_from([0.8, 0.95]))
def test_reversing_the_registration_changes_nothing(inputs, seed, level):
    p = params(bootstrap_draws=15, interval_level=level, n=0, m=0, v=0, r=0.0, k=1.0)
    original = measure_commitment(inputs, p, np.random.default_rng(seed))
    reversed_ = measure_commitment(flip(inputs), p, np.random.default_rng(seed))

    assert reversed_.favoured_side is original.favoured_side.opposite()
    assert _by_side(original) == _by_side(reversed_, swap=True)
    assert (original.tau, original.honoured, original.n_disconfirmations, original.citations_on_claim) == \
        (reversed_.tau, reversed_.honoured, reversed_.n_disconfirmations, reversed_.citations_on_claim)

    a, b = verdict(original, p), verdict(reversed_, p)
    assert (a.verdict, a.reason, a.corroboration) == (b.verdict, b.reason, b.corroboration)
    if a.favoured_side is not None:
        assert b.favoured_side is a.favoured_side.opposite()


def test_built_commitments_keep_their_verdicts_when_reversed():
    p = params()
    for kind, expected in (("healthy", Verdict.HEALTHY), ("insulated", Verdict.INSULATED)):
        original = verdict(measure_commitment(commitment(kind), p, np.random.default_rng(2)), p)
        reversed_ = verdict(measure_commitment(flip(commitment(kind)), p, np.random.default_rng(2)), p)
        assert original.verdict is expected and reversed_.verdict is expected
        assert reversed_.favoured_side is original.favoured_side.opposite()


def test_mirrored_discounting_flips_delta_and_is_not_insulation():
    """The insulated cluster's discounting pattern, applied to its own side instead, reads as harsher on
    its own side: Δ changes sign and the verdict is unclear, never insulated."""
    p = params()
    built = commitment("insulated")
    mirrored = CommitmentInputs(**{
        **built.__dict__,
        "results": tuple(ResultItem(r.result_id, r.supports, r.prominence, True) for r in built.results),
        "stances": tuple(
            StanceLabel(s.result_id, s.family, Stance.SUPPORT, None) if s.stance is Stance.DISCOUNT else s
            for s in built.stances
        ) + tuple(
            StanceLabel(r.result_id, fam, Stance.DISCOUNT, "blinding")
            for r in built.results if r.supports is Side.P and int(r.result_id[1:]) % 4 == 0
            for fam in ("human-1", "model-a", "model-b")
        ),
        "ledger": (),
    })
    # Keep one label per (result, family): drop the SUPPORT labels the extra DISCOUNT labels replace.
    discounted = {(s.result_id, s.family) for s in mirrored.stances if s.stance is Stance.DISCOUNT}
    mirrored = CommitmentInputs(**{**mirrored.__dict__, "stances": tuple(
        s for s in mirrored.stances if s.stance is Stance.DISCOUNT or (s.result_id, s.family) not in discounted)})

    m = measure_commitment(mirrored, p, np.random.default_rng(4))
    orientation = next(o for o in m.oriented if o.side is m.favoured_side) if len(m.oriented) == 1 else m.oriented[0]
    assert orientation.delta.point < 0
    result = verdict(m, p)
    assert result.verdict is not Verdict.INSULATED
    assert result.reason in (Reason.READING_UNCLEAR, Reason.INSUFFICIENT_DATA)
