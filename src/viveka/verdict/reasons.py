"""Verdicts, indeterminacy reasons, readings, and the verdict result record."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from viveka.measures.types import Side


class Verdict(StrEnum):
    HEALTHY = "healthy"
    INSULATED = "insulated"
    INDETERMINATE = "indeterminate"
    CLOSED = "closed"
    OUT_OF_SCOPE = "out_of_scope"


DETERMINATE = frozenset({Verdict.HEALTHY, Verdict.INSULATED})
NOT_SCORED = frozenset({Verdict.CLOSED, Verdict.OUT_OF_SCOPE})


class Reason(StrEnum):
    INSUFFICIENT_DATA = "insufficient_data"
    READING_UNCLEAR = "reading_unclear"
    CONDUCT_CONFLICT = "conduct_conflict"
    UNSTABLE = "unstable"


class Reading(StrEnum):
    S = "S"
    A = "A"
    UNCLEAR = "unclear"


@dataclass(frozen=True)
class VerdictResult:
    verdict: Verdict
    reason: Reason | None = None
    note: str | None = None
    corroboration: tuple[str, ...] = ()
    favoured_side: Side | None = None

    def __post_init__(self) -> None:
        indeterminate = self.verdict is Verdict.INDETERMINATE
        if indeterminate != (self.reason is not None):
            raise ValueError("an indeterminate verdict needs exactly one reason; other verdicts take none")
