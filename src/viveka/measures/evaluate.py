"""Compute every measure for one commitment, with bootstrap intervals, oriented to the favoured side.

Orientation invariance is a design constraint: items are processed in an order
that never depends on which side a result supports, and every random draw is
taken the same way whatever the registration, so reversing every ``Side`` in the
inputs yields identical measure values.

Stance and applicability aggregation, Δ and Ω run vectorised (``fast.py``), with the
readable definitions in ``delta.py``, ``omega.py`` and ``aggregate.py`` as their
specification. The ledger is short and stays in plain Python.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from viveka.measures import bootstrap as bs
from viveka.measures import fast
from viveka.measures.aggregate import majority, votes_for
from viveka.measures.conduct import chi, honoured_share, tau
from viveka.measures.delta import uncheckable_uses_on_favourable
from viveka.measures.ledger_stats import LedgerRules, final_code, insulating_share, loop_length
from viveka.measures.types import (
    CommitmentInputs,
    FinalCode,
    Interval,
    LedgerCode,
    LedgerEntry,
    RoundInfo,
    RoundOutcome,
    Side,
)
from viveka.verdict.params import GateParams


@dataclass(frozen=True)
class OrientedMeasures:
    side: Side
    delta: Interval | None
    omega: Interval | None
    insulating_share: Interval | None
    loop_length: Interval | None


@dataclass(frozen=True)
class Measures:
    trajectory_closed: bool
    cites_observation: bool
    n_disconfirmations: int
    members: int
    citations_on_claim: int
    coverage: float
    favoured_side: Side
    oriented: tuple[OrientedMeasures, ...]
    tau: Interval | None
    tau_measurable: bool
    honoured: Interval | None
    honoured_measurable: bool
    chi: float | None
    diagnostics: Mapping[str, object] = field(default_factory=dict)


LedgerLabels = list[tuple[LedgerCode, RoundInfo | None] | None]


def _aggregate_ledger(families: Sequence[str], ledger: Sequence[LedgerEntry], rng: np.random.Generator,
                      noise: float) -> LedgerLabels:
    coded: LedgerLabels = []
    for entry in ledger:
        code = majority(votes_for(families, dict(entry.codes)), rng)
        if code is None:
            coded.append(None)
            continue
        if noise:
            code = bs.perturb(code, list(LedgerCode), noise, rng)
        round_info = None
        if code is LedgerCode.B:
            voters = [entry.rounds[f] for f in families if f in entry.rounds and entry.codes.get(f) is LedgerCode.B]
            round_info = majority(voters or [entry.rounds[f] for f in sorted(entry.rounds)], rng)
            if round_info is None:  # only reachable when noise turned a code into B
                round_info = RoundInfo(tests_auxiliary="unrecorded", outcome=RoundOutcome.OPEN, opened=entry.when)
        coded.append((code, round_info))
    return coded


def _finals(indices: Sequence[int], labels: LedgerLabels, as_of: float, j: float,
            rules: LedgerRules) -> list[FinalCode | None]:
    out = []
    for i in indices:
        coded = labels[i]
        out.append(None if coded is None else final_code(coded[0], coded[1], as_of, j, rules))
    return out


def measure_commitment(inputs: CommitmentInputs, params: GateParams, rng: np.random.Generator,
                       rules: LedgerRules | None = None) -> Measures:
    rules = rules or LedgerRules()
    results = tuple(sorted(inputs.results, key=lambda r: r.result_id))
    ledger = tuple(sorted(inputs.ledger, key=lambda e: (e.when, e.event_id)))
    old_enough = [i for i, e in enumerate(ledger) if e.when + params.lag <= inputs.window_end]
    families = tuple(sorted(
        {s.family for s in inputs.stances} | {a.family for a in inputs.applicability}
        | {f for e in ledger for f in e.codes}
    ))
    enc = fast.encode(inputs, families)

    labelled_items: dict[str, dict[str, object]] = {}
    for label in inputs.stances:
        labelled_items.setdefault(f"s:{label.result_id}", {})[label.family] = (label.stance, label.filter_id)
    for a in inputs.applicability:
        labelled_items.setdefault(f"a:{a.result_id}:{a.filter_id}", {})[a.family] = a.value
    labelled_items.update({f"l:{e.event_id}": dict(e.codes) for e in ledger})
    observed = bs.observed_disagreement(labelled_items)
    anchored = inputs.anchored_disagreement
    noise = float(anchored) if anchored is not None and anchored > observed else 0.0

    # Point estimates: every family once, no noise; ties broken by a generator derived from the caller's.
    point_rng = np.random.default_rng(int(rng.integers(2**63)))
    all_families = np.ones(len(families))
    point_category, point_applies = fast.aggregate(enc, all_families, point_rng, 0.0)
    point_ledger = _aggregate_ledger(families, ledger, point_rng, 0.0)
    side = fast.favoured_side_fast(enc, point_category)
    orientations = [Side.P, Side.NOT_P] if side is Side.BOTH else [side]

    def entries_for(orientation: Side, indices: Sequence[int]) -> list[int]:
        return [i for i in indices if ledger[i].against is orientation]

    every_result = np.arange(len(results))
    point_values = {}
    for o in orientations:
        ordered = entries_for(o, old_enough)
        finals = _finals(ordered, point_ledger, inputs.window_end, params.j, rules)
        point_values[o] = (
            fast.delta_fast(enc, every_result, point_category, point_applies, o),
            fast.omega_fast(enc, every_result, o, params.omega_strata),
            insulating_share(finals),
            float(loop_length(finals, [ledger[i].p_placed_at_risk for i in ordered])) if finals else None,
        )

    draws: dict[Side, list[list[float | None]]] = {o: [[], [], [], []] for o in orientations}
    tau_draws: list[float | None] = []
    honoured_draws: list[float | None] = []
    breaks, baseline, conditions = inputs.qualifying_breaks, inputs.baseline_changes, inputs.conditions_honoured

    for _ in range(params.bootstrap_draws):
        if noise or not families:
            weights, drawn_families = all_families, list(families)
        else:
            picks = rng.integers(0, len(families), len(families))
            weights = np.bincount(picks, minlength=len(families)).astype(float)
            drawn_families = [families[i] for i in picks]
        category, applies = fast.aggregate(enc, weights, rng, noise)
        ledger_labels = _aggregate_ledger(drawn_families, ledger, rng, noise)
        sample = bs.resample_indices(rng, len(results))
        sampled_entries = [old_enough[i] for i in bs.resample_indices(rng, len(old_enough))]
        for o in orientations:
            draws[o][0].append(fast.delta_fast(enc, sample, category, applies, o))
            draws[o][1].append(fast.omega_fast(enc, sample, o, params.omega_strata))
            draws[o][2].append(insulating_share(_finals(entries_for(o, sampled_entries), ledger_labels,
                                                        inputs.window_end, params.j, rules)))
            ordered = entries_for(o, old_enough)
            finals = _finals(ordered, ledger_labels, inputs.window_end, params.j, rules)
            draws[o][3].append(float(loop_length(finals, [ledger[i].p_placed_at_risk for i in ordered]))
                               if finals else None)
        tau_draws.append(tau([breaks[i] for i in bs.resample_indices(rng, len(breaks))],
                             [baseline[i] for i in bs.resample_indices(rng, len(baseline))]))
        honoured_draws.append(honoured_share([conditions[i] for i in bs.resample_indices(rng, len(conditions))]))

    level = params.interval_level
    oriented = tuple(
        OrientedMeasures(
            side=o,
            delta=bs.percentile_interval(point_values[o][0], draws[o][0], level),
            omega=bs.percentile_interval(point_values[o][1], draws[o][1], level),
            insulating_share=bs.percentile_interval(point_values[o][2], draws[o][2], level),
            loop_length=bs.percentile_interval(point_values[o][3], draws[o][3], level),
        )
        for o in orientations
    )
    tau_point = tau(breaks, baseline)
    n_disconfirmations = len(old_enough) if side is Side.BOTH else len(entries_for(side, old_enough))
    stance_of, _ = fast.decode(enc, point_category, point_applies)

    return Measures(
        trajectory_closed=inputs.trajectory_closed,
        cites_observation=inputs.cites_observation,
        n_disconfirmations=n_disconfirmations,
        members=inputs.members,
        citations_on_claim=sum(r.cited for r in results),
        coverage=inputs.coverage,
        favoured_side=side,
        oriented=oriented,
        tau=bs.percentile_interval(tau_point, tau_draws, level),
        tau_measurable=len(breaks) >= 1 and tau_point is not None,
        honoured=bs.percentile_interval(honoured_share(conditions), honoured_draws, level),
        honoured_measurable=len(conditions) >= params.h0,
        chi=chi(inputs.citations_out, inputs.citations_total, inputs.coverage, params.r),
        diagnostics={
            "families": families,
            "observed_disagreement": observed,
            "noise_rate": noise,
            "uncheckable_uses_on_favourable": {
                o.value: uncheckable_uses_on_favourable(results, stance_of, inputs.filters, o) for o in orientations
            },
        },
    )
