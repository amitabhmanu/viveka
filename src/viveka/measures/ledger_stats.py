"""The Anomaly Response Ledger: closing rounds, the insulating share, and loop length L.

Final codes (from the framework's "Rounds"):

* A, C, D keep their code;
* B with a round that succeeded, or failed with debit to the tested auxiliary -> B resolved;
* B with a round that failed without debit -> B→C;
* B with a round still open -> B→C once no interim result able to go against p has
  appeared for ``j`` years at the window's end, otherwise B open.

C, D and B→C are insulating. A round that names no tested auxiliary is governed by
a codebook rule the framework has not fixed yet; until a rule is supplied the
engine raises rather than guessing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from viveka.measures.types import INSULATING, FinalCode, LedgerCode, RoundInfo, RoundOutcome

UNNAMED_ROUND_POLICIES = ("as_named", "exclude")


class UnresolvedRule(RuntimeError):
    """The input needs a codebook rule the registry has not fixed yet."""


@dataclass(frozen=True)
class LedgerRules:
    unnamed_round: str | None = None  # None (not yet decided) | "as_named" | "exclude"

    def __post_init__(self) -> None:
        if self.unnamed_round is not None and self.unnamed_round not in UNNAMED_ROUND_POLICIES:
            raise ValueError(f"unnamed_round must be one of {UNNAMED_ROUND_POLICIES} or None")


def final_code(code: LedgerCode, round_info: RoundInfo | None, as_of: float, j: float,
               rules: LedgerRules) -> FinalCode | None:
    """The entry's final code, or None if a rule excludes it."""
    if code is LedgerCode.A:
        return FinalCode.A
    if code is LedgerCode.C:
        return FinalCode.C
    if code is LedgerCode.D:
        return FinalCode.D
    if round_info is None:
        raise ValueError("a B response needs round information")
    if round_info.tests_auxiliary is None:
        if rules.unnamed_round is None:
            raise UnresolvedRule(
                "a B response names no tested auxiliary, and the codebook rule for such rounds is not fixed "
                "(framework open item: 'Rounds need a stated purpose')"
            )
        if rules.unnamed_round == "exclude":
            return None
    if round_info.outcome in (RoundOutcome.SUCCESS, RoundOutcome.FAIL_DEBIT):
        return FinalCode.B_RESOLVED
    if round_info.outcome is RoundOutcome.FAIL_NO_DEBIT:
        return FinalCode.B_TO_C
    last = round_info.last_interim if round_info.last_interim is not None else round_info.opened
    return FinalCode.B_TO_C if as_of - last >= j else FinalCode.B_OPEN


def insulating_share(codes: Sequence[FinalCode | None]) -> float | None:
    counted = [c for c in codes if c is not None]
    if not counted:
        return None
    return sum(c in INSULATING for c in counted) / len(counted)


def loop_length(codes: Sequence[FinalCode | None], at_risk: Sequence[bool]) -> int:
    """Longest run of consecutive insulating entries (date order), broken by a non-insulating
    entry or by an entry at which the community publicly placed p at risk. Excluded entries are skipped."""
    if len(codes) != len(at_risk):
        raise ValueError("codes and at_risk must have the same length")
    longest = current = 0
    for code, risk in zip(codes, at_risk, strict=True):
        if code is None:
            continue
        if risk or code not in INSULATING:
            current = 0
            continue
        current += 1
        longest = max(longest, current)
    return longest
