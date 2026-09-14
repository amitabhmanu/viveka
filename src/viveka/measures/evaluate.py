"""Compute every measure for one commitment, with bootstrap intervals, oriented to the favoured side.

Orientation invariance is a design constraint: items are processed in an order
that never depends on which side a result supports, and every random draw is
taken the same way whatever the registration, so reversing every ``Side`` in the
inputs yields identical measure values.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from viveka.measures import bootstrap as bs
from viveka.measures.aggregate import majority, votes_for
from viveka.measures.conduct import chi, honoured_share, tau
from viveka.measures.delta import delta, uncheckable_uses_on_favourable
from viveka.measures.ledger_stats import LedgerRules, final_code, insulating_share, loop_length
from viveka.measures.omega import omega
from viveka.measures.side import favoured_side
from viveka.measures.types import (
    Applies,
    CommitmentInputs,
    FinalCode,
    Interval,
    LedgerCode,
    LedgerEntry,
    RoundInfo,
    RoundOutcome,
    Side,
    Stance,
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


@dataclass(frozen=True)
class _Aggregated:
    stance_of: dict[str, tuple[Stance, str | None]]
    applies_of: dict[tuple[str, str], Applies]
    ledger: list[tuple[LedgerCode, RoundInfo | None] | None]


def _stance_key(value: tuple[Stance, str | None]) -> str:
    return f"{value[0].value}|{value[1] or ''}"


def _aggregate(
    families: Sequence[str],
    stances: Mapping[str, dict[str, tuple[Stance, str | None]]],
    applicability: Mapping[tuple[str, str], dict[str, Applies]],
    ledger: Sequence[LedgerEntry],
    rng: np.random.Generator,
    noise: float,
) -> _Aggregated:
    stance_of: dict[str, tuple[Stance, str | None]] = {}
    for rid in sorted(stances):
        winner = majority(votes_for(families, stances[rid]), rng, key=_stance_key)
        if winner is None:
            continue
        if noise:
            new_stance = bs.perturb(winner[0], list(Stance), noise, rng)
            winner = (new_stance, winner[1] if new_stance is Stance.DISCOUNT else None)
        stance_of[rid] = winner

    applies_of: dict[tuple[str, str], Applies] = {}
    for key in sorted(applicability):
        winner = majority(votes_for(families, applicability[key]), rng)
        if winner is None:
            continue
        applies_of[key] = bs.perturb(winner, list(Applies), noise, rng) if noise else winner

    coded: list[tuple[LedgerCode, RoundInfo | None] | None] = []
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
    return _Aggregated(stance_of, applies_of, coded)


def _finals(entries_idx: Sequence[int], agg: _Aggregated, ledger: Sequence[LedgerEntry], as_of: float, j: float,
            rules: LedgerRules) -> list[FinalCode | None]:
    out = []
    for i in entries_idx:
        coded = agg.ledger[i]
        out.append(None if coded is None else final_code(coded[0], coded[1], as_of, j, rules))
    return out


def measure_commitment(inputs: CommitmentInputs, params: GateParams, rng: np.random.Generator,
                       rules: LedgerRules | None = None) -> Measures:
    rules = rules or LedgerRules()
    results = tuple(sorted(inputs.results, key=lambda r: r.result_id))
    ledger = tuple(sorted(inputs.ledger, key=lambda e: (e.when, e.event_id)))
    old_enough = [i for i, e in enumerate(ledger) if e.when + params.lag <= inputs.window_end]

    stances: dict[str, dict[str, tuple[Stance, str | None]]] = {}
    for label in inputs.stances:
        stances.setdefault(label.result_id, {})[label.family] = (label.stance, label.filter_id)
    applicability: dict[tuple[str, str], dict[str, Applies]] = {}
    for a in inputs.applicability:
        applicability.setdefault((a.result_id, a.filter_id), {})[a.family] = a.value
    families = sorted(
        {s.family for s in inputs.stances} | {a.family for a in inputs.applicability}
        | {f for e in ledger for f in e.codes}
    )

    labelled_items: dict[str, dict[str, object]] = {f"s:{k}": dict(v) for k, v in stances.items()}
    labelled_items.update({f"a:{k[0]}:{k[1]}": dict(v) for k, v in applicability.items()})
    labelled_items.update({f"l:{e.event_id}": dict(e.codes) for e in ledger})
    observed = bs.observed_disagreement(labelled_items)
    anchored = inputs.anchored_disagreement
    noise = float(anchored) if anchored is not None and anchored > observed else 0.0

    # Point estimates: every family once, no noise; ties broken by a generator derived from the caller's.
    point_rng = np.random.default_rng(int(rng.integers(2**63)))
    point = _aggregate(families, stances, applicability, ledger, point_rng, 0.0)
    side = favoured_side(results, {rid: s for rid, (s, _) in point.stance_of.items()})
    orientations = [Side.P, Side.NOT_P] if side is Side.BOTH else [side]

    def entries_for(orientation: Side, indices: Sequence[int]) -> list[int]:
        return [i for i in indices if ledger[i].against is orientation]

    point_values = {}
    for o in orientations:
        finals = _finals(entries_for(o, old_enough), point, ledger, inputs.window_end, params.j, rules)
        risks = [ledger[i].p_placed_at_risk for i in entries_for(o, old_enough)]
        point_values[o] = (
            delta(results, point.stance_of, point.applies_of, inputs.filters, o),
            omega(results, o, params.omega_strata),
            insulating_share(finals),
            float(loop_length(finals, risks)) if finals else None,
        )

    draws: dict[Side, list[list[float | None]]] = {o: [[], [], [], []] for o in orientations}
    tau_draws: list[float | None] = []
    honoured_draws: list[float | None] = []
    breaks, baseline, conditions = inputs.qualifying_breaks, inputs.baseline_changes, inputs.conditions_honoured

    for _ in range(params.bootstrap_draws):
        fams = families if noise else bs.resample_families(rng, families)
        agg = _aggregate(fams, stances, applicability, ledger, rng, noise)
        res_b = [results[i] for i in bs.resample_indices(rng, len(results))]
        led_b = [old_enough[i] for i in bs.resample_indices(rng, len(old_enough))]
        for o in orientations:
            draws[o][0].append(delta(res_b, agg.stance_of, agg.applies_of, inputs.filters, o))
            draws[o][1].append(omega(res_b, o, params.omega_strata))
            draws[o][2].append(insulating_share(_finals(entries_for(o, led_b), agg, ledger, inputs.window_end,
                                                        params.j, rules)))
            ordered = entries_for(o, old_enough)
            finals = _finals(ordered, agg, ledger, inputs.window_end, params.j, rules)
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
            "families": tuple(families),
            "observed_disagreement": observed,
            "noise_rate": noise,
            "uncheckable_uses_on_favourable": {
                o.value: uncheckable_uses_on_favourable(results, point.stance_of, inputs.filters, o)
                for o in orientations
            },
        },
    )
