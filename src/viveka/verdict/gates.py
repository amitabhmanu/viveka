"""Gates 1-3 of the decision procedure ("The procedure"). Gate 4 is ``stability.stable_verdict``.

Intervals are compared strictly, and the same interval level serves both readings:
S needs Δ and Ω wholly inside ±δ and the insulating share wholly below c; A needs
Δ or Ω wholly beyond +δ (toward the favoured side) and L wholly at or above k.
"""

from __future__ import annotations

from viveka.measures.evaluate import Measures, OrientedMeasures
from viveka.measures.types import Interval, Side
from viveka.verdict.params import GateParams
from viveka.verdict.reasons import Reading, Reason, Verdict, VerdictResult


def _inside(iv: Interval | None, band: float) -> bool:
    return iv is not None and iv.lower >= -band and iv.upper <= band


def _beyond_positive(iv: Interval | None, band: float) -> bool:
    return iv is not None and iv.lower > band


def _beyond_negative(iv: Interval | None, band: float) -> bool:
    return iv is not None and iv.upper < -band


def _wholly_below(iv: Interval | None, threshold: float) -> bool:
    return iv is not None and iv.upper < threshold


def _at_or_above(iv: Interval | None, threshold: float) -> bool:
    return iv is not None and iv.lower >= threshold


def reading_for(o: OrientedMeasures, p: GateParams) -> tuple[Reading, str | None]:
    if _inside(o.delta, p.delta) and _inside(o.omega, p.delta) and _wholly_below(o.insulating_share, p.c):
        return Reading.S, None
    asymmetric = _beyond_positive(o.delta, p.delta) or _beyond_positive(o.omega, p.delta)
    if asymmetric and _at_or_above(o.loop_length, p.k):
        return Reading.A, None
    missing = [name for name, iv in (("Δ", o.delta), ("Ω", o.omega), ("insulating share", o.insulating_share),
                                     ("L", o.loop_length)) if iv is None]
    if _beyond_negative(o.delta, p.delta) or _beyond_negative(o.omega, p.delta):
        return Reading.UNCLEAR, "asymmetry points away from the favoured side (harsher on its own side); not insulation"
    if missing:
        return Reading.UNCLEAR, "not computable: " + ", ".join(missing)
    if asymmetric:
        return Reading.UNCLEAR, "asymmetry beyond δ without a loop of at least k"
    if _at_or_above(o.loop_length, p.k):
        return Reading.UNCLEAR, "loop of at least k without asymmetry beyond δ"
    return Reading.UNCLEAR, "an interval straddles its threshold"


def primary_reading(m: Measures, p: GateParams) -> tuple[Reading, Side | None, str | None]:
    """The gate-2 reading, the side it applies to, and a note when unclear."""
    readings = [(o.side, *reading_for(o, p)) for o in m.oriented]
    if len(readings) == 1:
        side, reading, note = readings[0]
        return reading, side, note
    if all(r is Reading.S for _, r, _ in readings):
        return Reading.S, Side.BOTH, None
    asymmetric_sides = [s for s, r, _ in readings if r is Reading.A]
    if len(asymmetric_sides) == 1:
        return Reading.A, asymmetric_sides[0], None
    if len(asymmetric_sides) > 1:
        return Reading.UNCLEAR, None, "asymmetric toward both sides"
    return Reading.UNCLEAR, None, "; ".join(f"{s.value}: {n}" for s, r, n in readings if n)


def _direction(iv: Interval | None, threshold: float) -> Reading | None:
    if iv is None:
        return None
    if iv.upper < threshold:
        return Reading.A
    if iv.lower > threshold:
        return Reading.S
    return None


def verdict(m: Measures, p: GateParams) -> VerdictResult:
    if m.trajectory_closed:
        return VerdictResult(Verdict.CLOSED)
    if not m.cites_observation:
        return VerdictResult(Verdict.OUT_OF_SCOPE)

    # Gate 1: eligibility.
    shortfalls = [
        label for label, short in (
            (f"disconfirmations {m.n_disconfirmations} < n={p.n}", m.n_disconfirmations < p.n),
            (f"members {m.members} < m={p.m}", m.members < p.m),
            (f"citations {m.citations_on_claim} < v={p.v}", m.citations_on_claim < p.v),
            (f"coverage {m.coverage:.2f} < r={p.r}", m.coverage < p.r),
        ) if short
    ]
    if shortfalls:
        return VerdictResult(Verdict.INDETERMINATE, Reason.INSUFFICIENT_DATA, "; ".join(shortfalls),
                             favoured_side=m.favoured_side)

    # Gate 2: primary reading.
    reading, side, note = primary_reading(m, p)
    if reading is Reading.UNCLEAR:
        return VerdictResult(Verdict.INDETERMINATE, Reason.READING_UNCLEAR, note, favoured_side=m.favoured_side)

    # Gate 3: conduct check. A measure that cannot be taken counts neither way.
    corroboration = []
    for name, interval, measurable, threshold in (
        ("τ", m.tau, m.tau_measurable, p.t),
        ("H", m.honoured, m.honoured_measurable, p.h),
    ):
        if not measurable:
            continue
        direction = _direction(interval, threshold)
        if direction is None:
            continue
        if direction is not reading:
            return VerdictResult(Verdict.INDETERMINATE, Reason.CONDUCT_CONFLICT,
                                 f"{name} points to {direction.value} against reading {reading.value}",
                                 favoured_side=m.favoured_side)
        corroboration.append(name)

    return VerdictResult(
        Verdict.HEALTHY if reading is Reading.S else Verdict.INSULATED,
        corroboration=tuple(corroboration),
        favoured_side=side,
    )
