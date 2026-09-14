"""The framework's own revision triggers, as pure functions over already-computed results.

Each returns a ``TriggerResult``: ``fired`` is True or False, or None when the
trigger cannot be evaluated from what was supplied. The harness reports triggers;
it never acts on one by itself. Recording results in the change ledger belongs to
stage S12.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from viveka.verdict.field_summary import Summary
from viveka.verdict.reasons import NOT_SCORED, Reason, Verdict, VerdictResult


class Truth(StrEnum):
    SCIENCE = "science"
    PSEUDOSCIENCE = "pseudoscience"


@dataclass(frozen=True)
class TriggerResult:
    trigger: int
    fired: bool | None
    numbers: Mapping[str, object] = field(default_factory=dict)
    used: tuple[str, ...] = ()
    note: str | None = None


@dataclass(frozen=True)
class CalibrationVerdict:
    commitment_id: str
    field_id: str
    truth: Truth
    result: VerdictResult
    field_replaced: bool = False


@dataclass(frozen=True)
class PairOutcome:
    pair_id: str
    predicted: Mapping[str, Summary]
    actual: Mapping[str, Summary]


@dataclass(frozen=True)
class IndependentCheck:
    commitment_id: str
    depth_ratio: float | None
    deletion_rate: float | None


def trigger_1(held_out: Sequence[CalibrationVerdict], e: float, i: float) -> TriggerResult:
    """Calibration fails on held-out fields: misclassification share > e, or indeterminate share > i.
    Closed trajectories and fields replaced at the census are not counted."""
    scored = [v for v in held_out if not v.field_replaced and v.result.verdict not in NOT_SCORED]
    if not scored:
        return TriggerResult(1, None, note="no scored held-out commitments")
    errors = [v for v in scored if (v.truth is Truth.SCIENCE and v.result.verdict is Verdict.INSULATED)
              or (v.truth is Truth.PSEUDOSCIENCE and v.result.verdict is Verdict.HEALTHY)]
    indeterminate = [v for v in scored if v.result.verdict is Verdict.INDETERMINATE]
    error_share = len(errors) / len(scored)
    indeterminate_share = len(indeterminate) / len(scored)
    return TriggerResult(
        1, error_share > e or indeterminate_share > i,
        {"scored": len(scored), "error_share": error_share, "indeterminate_share": indeterminate_share,
         "e": e, "i": i},
        tuple(v.commitment_id for v in scored),
    )


def trigger_2(kappa_discounts: float | None, qualified_pool: bool | None, kappa_min: float) -> TriggerResult:
    """Coding is unreliable: κ on discounts below the minimum, or no qualified pool of q coders."""
    if kappa_discounts is None and qualified_pool is None:
        return TriggerResult(2, None, note="no coder audit results supplied")
    low_kappa = kappa_discounts is not None and kappa_discounts < kappa_min
    no_pool = qualified_pool is False
    return TriggerResult(2, low_kappa or no_pool,
                         {"kappa_discounts": kappa_discounts, "kappa_min": kappa_min, "qualified_pool": qualified_pool})


def trigger_3() -> TriggerResult:
    """Verdicts track confounds after controls. The framework does not yet specify the confound model."""
    return TriggerResult(3, None, note="confound model not yet specified by the framework; evaluated from M8")


def trigger_4(pairs: Sequence[PairOutcome]) -> TriggerResult:
    """Matched pairs not separated: any case whose field summary differs from its prediction, or is undetermined."""
    if not pairs:
        return TriggerResult(4, None, note="no matched pairs supplied")
    not_separated = [
        p.pair_id for p in pairs
        if any(p.actual.get(case) != predicted or p.actual.get(case) is Summary.UNDETERMINED
               for case, predicted in p.predicted.items())
    ]
    return TriggerResult(4, bool(not_separated), {"pairs": len(pairs), "not_separated": not_separated},
                         tuple(p.pair_id for p in pairs))


def trigger_5(results: Sequence[VerdictResult]) -> TriggerResult:
    """Robustness decides the answer: more than half of all verdicts are indeterminate · unstable."""
    scored = [r for r in results if r.verdict not in NOT_SCORED]
    if not scored:
        return TriggerResult(5, None, note="no scored verdicts")
    unstable = sum(r.reason is Reason.UNSTABLE for r in scored)
    share = unstable / len(scored)
    return TriggerResult(5, share > 0.5, {"scored": len(scored), "unstable": unstable, "share": share})


def trigger_6(checks_passed_calibration: bool, insulated: Sequence[IndependentCheck],
              consensus_depth_range: tuple[float, float] | None,
              consensus_deletion_range: tuple[float, float] | None) -> TriggerResult:
    """Independent checks disagree: more than half of measurable insulated verdicts fall within the
    consensus sciences' range on depth ratio or deletion rate."""
    if not checks_passed_calibration:
        return TriggerResult(6, None, note="independent checks failed calibration and were dropped")

    def within(value: float | None, bounds: tuple[float, float] | None) -> bool:
        return value is not None and bounds is not None and bounds[0] <= value <= bounds[1]

    measurable = [c for c in insulated if c.depth_ratio is not None or c.deletion_rate is not None]
    if not measurable:
        return TriggerResult(6, None, note="no insulated verdict has a measurable independent check")
    in_range = [c for c in measurable
                if within(c.depth_ratio, consensus_depth_range) or within(c.deletion_rate, consensus_deletion_range)]
    share = len(in_range) / len(measurable)
    return TriggerResult(6, share > 0.5, {"measurable": len(measurable), "within_consensus_range": len(in_range),
                                          "share": share}, tuple(c.commitment_id for c in measurable))
