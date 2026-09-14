"""Builders for verdict-engine tests: small hand-made commitments with known structure."""

from __future__ import annotations

import dataclasses

from viveka.measures.evaluate import Measures, OrientedMeasures
from viveka.measures.types import (
    Applicability,
    Applies,
    CommitmentInputs,
    Filter,
    Interval,
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
from viveka.verdict.params import GateParams

FAMILIES = ("human-1", "model-a", "model-b")


def params(**overrides) -> GateParams:
    base = dict(n=2, m=3, v=4, r=0.7, lag=2.0, delta=0.15, c=0.3, k=3.0, j=10.0, t=0.8, h=0.5, h0=3,
                interval_level=0.95, bootstrap_draws=200, omega_strata=2)
    base.update(overrides)
    return GateParams(**base)


def flip(inputs: CommitmentInputs) -> CommitmentInputs:
    """The same commitment with the claim registered the other way round."""
    return dataclasses.replace(
        inputs,
        results=tuple(dataclasses.replace(r, supports=r.supports.opposite()) for r in inputs.results),
        ledger=tuple(dataclasses.replace(e, against=e.against.opposite()) for e in inputs.ledger),
    )


def _labels(result_id: str, stance: Stance, filter_id: str | None, families) -> list[StanceLabel]:
    return [StanceLabel(result_id, f, stance, filter_id) for f in families]


def commitment(kind: str, families=FAMILIES) -> CommitmentInputs:
    """``healthy``: the blinding filter is applied to both lanes alike, every result is cited, anomalies
    are abandoned or adopted and resolved, and breaks keep their ties.
    ``insulated``: only unfavourable results are discounted (including by the uncheckable decline
    filter), most unfavourable results go uncited, anomalies are insulated or ignored, and breaks lose ties."""
    if kind not in ("healthy", "insulated"):
        raise ValueError(kind)
    results, stances, applicability = [], [], []
    filters = (Filter("blinding", checkable=True), Filter("decline", checkable=False))
    for i in range(40):
        supports = Side.P if i < 25 else Side.NOT_P
        rid = f"r{i:02d}"
        applies = i % 4 == 0
        if kind == "healthy":
            cited = True
            stance, fid = (Stance.DISCOUNT, "blinding") if applies else (Stance.SUPPORT, None)
        else:
            cited = supports is Side.P or i % 3 == 0
            if supports is Side.P:
                stance, fid = Stance.SUPPORT, None
            else:
                stance, fid = (Stance.DISCOUNT, "blinding") if applies else (Stance.DISCOUNT, "decline")
        results.append(ResultItem(rid, supports, prominence=float(i), cited=cited))
        if cited:
            stances += _labels(rid, stance, fid, families)
        applicability += [Applicability(rid, "blinding", f, Applies.YES if applies else Applies.NO) for f in families]

    ledger = []
    for n, year in enumerate(range(1990, 1996)):
        if kind == "healthy":
            code = LedgerCode.A if n < 3 else LedgerCode.B
            rounds = {f: RoundInfo("detector sensitivity", RoundOutcome.SUCCESS, opened=year) for f in families} \
                if code is LedgerCode.B else {}
        else:
            code = LedgerCode.D if n in (1, 4) else LedgerCode.C
            rounds = {}
        ledger.append(LedgerEntry(f"e{n}", float(year), Side.P, dict.fromkeys(families, code), rounds))

    if kind == "healthy":
        breaks = (TieEvent(10, 9), TieEvent(8, 7))
    else:
        breaks = (TieEvent(10, 2), TieEvent(8, 1))
    return CommitmentInputs(
        results=tuple(results), stances=tuple(stances), filters=filters, applicability=tuple(applicability),
        ledger=tuple(ledger), members=10, coverage=0.9, window_end=2000.0,
        qualifying_breaks=breaks, baseline_changes=(TieEvent(10, 9), TieEvent(10, 9)),
        citations_out=12, citations_total=40,
    )


def iv(lower: float, upper: float, point: float | None = None) -> Interval:
    return Interval((lower + upper) / 2 if point is None else point, lower, upper, 100)


def oriented(side: Side = Side.P, delta=None, omega=None, share=None, loop=None) -> OrientedMeasures:
    return OrientedMeasures(
        side=side,
        delta=iv(-0.05, 0.05) if delta is None else delta,
        omega=iv(-0.05, 0.05) if omega is None else omega,
        insulating_share=iv(0.0, 0.1) if share is None else share,
        loop_length=iv(0.0, 1.0) if loop is None else loop,
    )


def measures(**overrides) -> Measures:
    base = dict(trajectory_closed=False, cites_observation=True, n_disconfirmations=5, members=10,
                citations_on_claim=20, coverage=0.9, favoured_side=Side.P, oriented=(oriented(),),
                tau=None, tau_measurable=False, honoured=None, honoured_measurable=False, chi=None)
    base.update(overrides)
    return Measures(**base)
