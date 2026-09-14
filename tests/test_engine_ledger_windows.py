import pytest

from viveka.measures.ledger_stats import LedgerRules, UnresolvedRule, final_code, insulating_share, loop_length
from viveka.measures.types import FinalCode, LedgerCode, RoundInfo, RoundOutcome
from viveka.measures.window import subwindows, trajectory_closed, window_variants

NAMED = LedgerRules()


def _round(outcome, opened=1990.0, last=None, aux="high loading"):
    return RoundInfo(aux, outcome, opened, last)


@pytest.mark.parametrize(
    ("code", "round_info", "expected"),
    [
        (LedgerCode.A, None, FinalCode.A),
        (LedgerCode.C, None, FinalCode.C),
        (LedgerCode.D, None, FinalCode.D),
        (LedgerCode.B, _round(RoundOutcome.SUCCESS), FinalCode.B_RESOLVED),
        (LedgerCode.B, _round(RoundOutcome.FAIL_DEBIT), FinalCode.B_RESOLVED),
        (LedgerCode.B, _round(RoundOutcome.FAIL_NO_DEBIT), FinalCode.B_TO_C),
        (LedgerCode.B, _round(RoundOutcome.OPEN, opened=1995.0), FinalCode.B_OPEN),
        (LedgerCode.B, _round(RoundOutcome.OPEN, opened=1985.0), FinalCode.B_TO_C),
        (LedgerCode.B, _round(RoundOutcome.OPEN, opened=1980.0, last=1994.0), FinalCode.B_OPEN),
        (LedgerCode.B, _round(RoundOutcome.OPEN, opened=1980.0, last=1990.0), FinalCode.B_TO_C),
    ],
)
def test_each_closure_path_gives_its_final_code(code, round_info, expected):
    assert final_code(code, round_info, as_of=2000.0, j=10.0, rules=NAMED) is expected


def test_unnamed_round_needs_a_codebook_rule():
    unnamed = _round(RoundOutcome.OPEN, aux=None)
    with pytest.raises(UnresolvedRule, match="stated purpose"):
        final_code(LedgerCode.B, unnamed, 2000.0, 10.0, LedgerRules())
    assert final_code(LedgerCode.B, unnamed, 2000.0, 10.0, LedgerRules("exclude")) is None
    assert final_code(LedgerCode.B, unnamed, 2000.0, 10.0, LedgerRules("as_named")) is FinalCode.B_TO_C
    with pytest.raises(ValueError):
        LedgerRules("guess")
    with pytest.raises(ValueError, match="round information"):
        final_code(LedgerCode.B, None, 2000.0, 10.0, NAMED)


def test_share_and_loop_length():
    C, D, A, BC, BO = FinalCode.C, FinalCode.D, FinalCode.A, FinalCode.B_TO_C, FinalCode.B_OPEN
    codes = [C, D, None, BC, A, C, C, BO]
    assert insulating_share(codes) == 5 / 7
    assert loop_length(codes, [False] * 8) == 3
    # A risk statement at the D breaks the first run into C | B→C; the later C, C run is then longest.
    assert loop_length(codes, [False, True, False, False, False, False, False, False]) == 2
    assert insulating_share([None]) is None
    assert loop_length([], []) == 0


def test_windows_variants_and_closure():
    assert subwindows(1989, 1995, 5) == [(1989, 1993), (1990, 1994), (1991, 1995)]
    assert subwindows(1989, 1991, 5) == []
    variants = window_variants(1989, 2000, (4, 5), 1)
    assert [(length, shift) for length, shift, _ in variants] == [(4, 0), (4, 1), (5, 0), (5, 1)]
    assert variants[1][2][0] == (1990, 1993)

    counts = [9, 7, 1, 0, 2]
    assert trajectory_closed(counts, v=4, index=2)
    assert not trajectory_closed(counts, v=4, index=1)
    assert not trajectory_closed([1, 0, 0], v=4, index=1)  # never engaged
    assert not trajectory_closed([9, 1, 5], v=4, index=1)  # re-engaged later
    with pytest.raises(IndexError):
        trajectory_closed(counts, 4, 5)
