"""Input and output types for the measures. All immutable."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class Side(StrEnum):
    P = "p"
    NOT_P = "not_p"
    BOTH = "both"

    def opposite(self) -> Side:
        if self is Side.P:
            return Side.NOT_P
        if self is Side.NOT_P:
            return Side.P
        return Side.BOTH


class Stance(StrEnum):
    """How a cluster cites a result, relative to the result itself (so labels never depend on orientation).

    SUPPORT  - cites the result as counting in the direction it points. This is the framework's
               "+" for a result favouring p and "−" for a result against p: the evidence is accepted.
    DISCOUNT - cites the result only to discount it (the framework's "×"); ``filter_id`` names the reason.
    AGAINST  - cites the result as counting opposite to its own direction; recorded, not used by the measures.
    NONE     - no usable citation label.
    """

    SUPPORT = "+"
    AGAINST = "-"
    DISCOUNT = "x"
    NONE = "none"


class Applies(StrEnum):
    YES = "yes"
    NO = "no"
    CANNOT_TELL = "cannot_tell"


class LedgerCode(StrEnum):
    A = "A"  # abandon, or restrict with results inside the domain still able to count against
    B = "B"  # adopt the anomaly as a problem: opens a round
    C = "C"  # insulate
    D = "D"  # ignore: no response within the lag while citing favourable results


class RoundOutcome(StrEnum):
    OPEN = "open"
    SUCCESS = "success"
    FAIL_DEBIT = "fail_debit"
    FAIL_NO_DEBIT = "fail_no_debit"


class FinalCode(StrEnum):
    A = "A"
    B_RESOLVED = "B_resolved"
    B_OPEN = "B_open"
    C = "C"
    D = "D"
    B_TO_C = "B_to_C"


INSULATING = frozenset({FinalCode.C, FinalCode.D, FinalCode.B_TO_C})


@dataclass(frozen=True)
class ResultItem:
    """A result bearing on the claim. ``supports`` is the side the result favours (P or NOT_P)."""

    result_id: str
    supports: Side
    prominence: float
    cited: bool


@dataclass(frozen=True)
class StanceLabel:
    """One coder family's label for how the cluster cites a result. ``filter_id`` is the reason for a discount."""

    result_id: str
    family: str
    stance: Stance
    filter_id: str | None = None


@dataclass(frozen=True)
class Filter:
    filter_id: str
    checkable: bool


@dataclass(frozen=True)
class Applicability:
    result_id: str
    filter_id: str
    family: str
    value: Applies


@dataclass(frozen=True)
class RoundInfo:
    """What a B response committed to, as coded by one family. Times are decimal years."""

    tests_auxiliary: str | None
    outcome: RoundOutcome
    opened: float
    last_interim: float | None = None


@dataclass(frozen=True)
class LedgerEntry:
    """A dated disconfirmation of one side, with each coder family's response code."""

    event_id: str
    when: float
    against: Side
    codes: Mapping[str, LedgerCode]
    rounds: Mapping[str, RoundInfo] = field(default_factory=dict)
    p_placed_at_risk: bool = False


@dataclass(frozen=True)
class TieEvent:
    """Ties a member had before a change of position, and how many they kept afterwards."""

    ties_before: int
    ties_kept: int


@dataclass(frozen=True)
class Interval:
    point: float
    lower: float
    upper: float
    n: int


@dataclass(frozen=True)
class CommitmentInputs:
    """Everything the measures need for one commitment (lineage x claim x sub-window)."""

    results: tuple[ResultItem, ...]
    stances: tuple[StanceLabel, ...]
    filters: tuple[Filter, ...]
    applicability: tuple[Applicability, ...]
    ledger: tuple[LedgerEntry, ...]
    members: int
    coverage: float
    window_end: float
    cites_observation: bool = True
    trajectory_closed: bool = False
    qualifying_breaks: tuple[TieEvent, ...] = ()
    baseline_changes: tuple[TieEvent, ...] = ()
    conditions_honoured: tuple[bool, ...] = ()
    citations_out: int = 0
    citations_total: int = 0
    anchored_disagreement: float | None = None
