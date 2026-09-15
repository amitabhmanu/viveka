"""Generate one commitment's engine inputs from a planted behaviour profile.

The simulated community holds P. Results bearing on the claim support P with the
registered ``support_share`` (evidence tilted toward the claim the community holds),
and each result's filter property and prominence are drawn independently of its
direction. The profile decides what the community cites, what
it discounts (and why), how it responds to disconfirmations, whether members who
break with it keep their ties, and whether stated revision conditions are honoured.
Coder families then label the citations and ledger responses with the error model.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from viveka.measures.types import (
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
    TieEvent,
)
from viveka.sim import coders
from viveka.sim.config import Profile, SimulationConfig

FILTERS = (Filter("blinding", checkable=True), Filter("decline", checkable=False))
_FILTER_IDS = tuple(f.filter_id for f in FILTERS)
_LEDGER_CODES = (LedgerCode.A, LedgerCode.B, LedgerCode.C, LedgerCode.D)
_ROUND_OUTCOMES = (RoundOutcome.SUCCESS, RoundOutcome.FAIL_DEBIT, RoundOutcome.FAIL_NO_DEBIT, RoundOutcome.OPEN)


@dataclass(frozen=True)
class PlantedTruth:
    profile: str
    members: int
    results: int
    cited: int
    true_insulating_share: float | None


def _categorical(probabilities: dict[str, float], keys: tuple[str, ...], rng: np.random.Generator) -> int:
    weights = np.array([probabilities[k] for k in keys], dtype=float)
    return int(rng.choice(len(keys), p=weights / weights.sum()))


def _tie_events(count: int, ties_per_member: float, retention: float, rng: np.random.Generator) -> tuple[TieEvent, ...]:
    events = []
    for _ in range(count):
        before = 1 + int(rng.poisson(max(ties_per_member - 1.0, 0.0)))
        events.append(TieEvent(before, int(rng.binomial(before, retention))))
    return tuple(events)


def simulate_commitment(profile: Profile, members: int, config: SimulationConfig, lag: float,
                        rng: np.random.Generator) -> tuple[CommitmentInputs, PlantedTruth]:
    if config.window_length_years <= lag:
        raise ValueError("the simulated window must be longer than the response lag")
    families = config.families

    results, stances, applicability = [], [], []
    n_results = max(1, round(members * config.results_per_member))
    for i in range(n_results):
        rid = f"r{i:05d}"
        supports = Side.P if rng.random() < config.support_share else Side.NOT_P
        favourable = supports is Side.P
        has_property = rng.random() < config.filter_property_probability
        prominence = float(rng.lognormal(0.0, 1.0))
        cited = rng.random() < (profile.cite_favourable if favourable else profile.cite_unfavourable)
        results.append(ResultItem(rid, supports, prominence, cited))

        applicability += coders.label_applicability(rid, "blinding", Applies.YES if has_property else Applies.NO,
                                                    families, rng)
        if cited:
            discount_rate = profile.discount_favourable if favourable else profile.discount_unfavourable
            if has_property and rng.random() < discount_rate:
                true = (Stance.DISCOUNT, "blinding")
            elif not favourable and rng.random() < profile.uncheckable_unfavourable:
                true = (Stance.DISCOUNT, "decline")
            else:
                true = (Stance.SUPPORT, None)
            stances += coders.label_stance(rid, true, families, _FILTER_IDS, rng)

    ledger, true_codes = [], []
    start = config.window_end - config.window_length_years
    latest = config.window_end - lag
    for e in range(int(rng.poisson(members * config.disconfirmations_per_member))):
        when = float(start + rng.random() * (latest - start))
        code = _LEDGER_CODES[_categorical(dict(profile.ledger), ("A", "B", "C", "D"), rng)]
        round_info = None
        if code is LedgerCode.B:
            outcome = _ROUND_OUTCOMES[_categorical(dict(profile.rounds),
                                                   ("success", "fail_debit", "fail_no_debit", "open"), rng)]
            round_info = RoundInfo("auxiliary under test", outcome, opened=when)
        codes, rounds = coders.label_ledger(code, round_info, families, when, rng)
        ledger.append(LedgerEntry(f"e{e:03d}", when, Side.P, codes, rounds))
        true_codes.append((code, round_info))

    breaks = _tie_events(int(rng.poisson(members * config.qualifying_breaks_per_member)),
                         config.ties_per_member, profile.retention_after_break, rng)
    baseline = _tie_events(int(rng.poisson(members * config.baseline_changes_per_member)),
                           config.ties_per_member, profile.retention_after_baseline, rng)
    conditions = tuple(bool(rng.random() < profile.honoured)
                       for _ in range(int(rng.poisson(members * config.met_conditions_per_member))))

    cited_count = sum(r.cited for r in results)
    insulating = [c for c, r in true_codes if c in (LedgerCode.C, LedgerCode.D)
                  or (c is LedgerCode.B and r is not None and r.outcome is RoundOutcome.FAIL_NO_DEBIT)]
    inputs = CommitmentInputs(
        results=tuple(results), stances=tuple(stances), filters=FILTERS, applicability=tuple(applicability),
        ledger=tuple(ledger), members=members, coverage=1.0, window_end=float(config.window_end),
        qualifying_breaks=breaks, baseline_changes=baseline, conditions_honoured=conditions,
        citations_out=0, citations_total=cited_count,
    )
    truth = PlantedTruth(profile.name, members, n_results, cited_count,
                         len(insulating) / len(true_codes) if true_codes else None)
    return inputs, truth
