"""The coder-error model: each family flips each true label with its flip rate.

A flipped label becomes one of the other values uniformly. A stance flipped into a
discount gets a reason drawn uniformly from the registered filters, which is how
noise can invent uncheckable discounts and bias Δ even in a symmetric community.
Until stage S7 measures real confusion matrices, this uniform model is the
registered placeholder.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from viveka.measures.types import (
    Applicability,
    Applies,
    LedgerCode,
    RoundInfo,
    RoundOutcome,
    Stance,
    StanceLabel,
)
from viveka.sim.config import CoderFamily


def _flip[T](value: T, options: Sequence[T], rate: float, rng: np.random.Generator) -> T:
    if rng.random() >= rate:
        return value
    others = [o for o in options if o != value]
    return others[int(rng.integers(len(others)))]


def label_stance(result_id: str, true: tuple[Stance, str | None], families: Sequence[CoderFamily],
                 filter_ids: Sequence[str], rng: np.random.Generator) -> list[StanceLabel]:
    labels = []
    for fam in families:
        stance = _flip(true[0], list(Stance), fam.flip_rate, rng)
        if stance is Stance.DISCOUNT:
            reason = true[1] if true[0] is Stance.DISCOUNT else filter_ids[int(rng.integers(len(filter_ids)))]
        else:
            reason = None
        labels.append(StanceLabel(result_id, fam.name, stance, reason))
    return labels


def label_applicability(result_id: str, filter_id: str, true: Applies, families: Sequence[CoderFamily],
                        rng: np.random.Generator) -> list[Applicability]:
    return [Applicability(result_id, filter_id, fam.name, _flip(true, list(Applies), fam.flip_rate, rng))
            for fam in families]


def label_ledger(true_code: LedgerCode, true_round: RoundInfo | None, families: Sequence[CoderFamily],
                 when: float, rng: np.random.Generator) -> tuple[dict[str, LedgerCode], dict[str, RoundInfo]]:
    codes: dict[str, LedgerCode] = {}
    rounds: dict[str, RoundInfo] = {}
    for fam in families:
        code = _flip(true_code, list(LedgerCode), fam.flip_rate, rng)
        codes[fam.name] = code
        if code is LedgerCode.B:
            if true_round is not None:
                rounds[fam.name] = true_round
            else:
                outcome = list(RoundOutcome)[int(rng.integers(len(RoundOutcome)))]
                rounds[fam.name] = RoundInfo("auxiliary", outcome, opened=when)
    return codes, rounds
