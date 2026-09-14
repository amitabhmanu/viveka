"""Pilot power and robustness, estimated on membership-level scenarios.

``pilot_power`` answers, for each case: how often do the simulated lineages pass
gate 1, and how often does the field summary come out as predicted? At M5 the
scenario sizes come from the real pilot measurements (stage S4); in M3 they are
synthetic. ``robustness`` answers: how many determinate verdicts survive when the
membership is perturbed, as the stability gate will perturb partitions?
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from viveka.sim.config import SimulationConfig
from viveka.sim.lineages import Scenario, membership, simulate_scenario
from viveka.verdict.field_summary import summarise
from viveka.verdict.params import GateParams
from viveka.verdict.reasons import DETERMINATE, NOT_SCORED, Reason
from viveka.verdict.stability import match_lineages, stable_verdict


@dataclass(frozen=True)
class PilotPower:
    case: str
    predicted: str
    reach_probability: float
    eligibility_rate: float
    summaries: dict[str, int]


def _rng(seed: int, *key: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence(entropy=seed, spawn_key=key))


def pilot_power(scenarios: Sequence[Scenario], params: GateParams, config: SimulationConfig, replicates: int,
                seed: int) -> list[PilotPower]:
    report = []
    for index, scenario in enumerate(scenarios):
        summaries: dict[str, int] = {}
        scored = eligible = 0
        for replicate in range(replicates):
            verdicts = simulate_scenario(scenario, config, params, _rng(seed, index, replicate))
            summary = summarise(scenario.root, scenario.parents(), verdicts).summary
            summaries[summary.value] = summaries.get(summary.value, 0) + 1
            for v in verdicts:
                if v.result.verdict not in NOT_SCORED:
                    scored += 1
                    eligible += v.result.reason is not Reason.INSUFFICIENT_DATA
        report.append(PilotPower(
            case=scenario.name,
            predicted=scenario.predicted.value,
            reach_probability=summaries.get(scenario.predicted.value, 0) / replicates,
            eligibility_rate=eligible / scored if scored else 0.0,
            summaries=summaries,
        ))
    return report


def robustness(scenario: Scenario, params: GateParams, config: SimulationConfig, replicates: int, seed: int,
               jitter: float = 0.1, churn: float = 0.1) -> float:
    """Share of determinate verdicts that stay identical when membership is scaled by 1 ± jitter."""
    kept = total = 0
    for replicate in range(replicates):
        base = simulate_scenario(scenario, config, params, _rng(seed, 1, replicate))
        variant = simulate_scenario(scenario, config, params, _rng(seed, 2, replicate), member_scale=1.0 + jitter)
        base_members = membership(scenario, churn, _rng(seed, 3, replicate))
        variant_members = membership(scenario, churn, _rng(seed, 3, replicate))
        for window, (b, v) in enumerate(zip(base_members, variant_members, strict=True)):
            matched = match_lineages(b, v)
            for lv in (x for x in base if x.window == (window, window) and x.result.verdict in DETERMINATE):
                total += 1
                partner_id = matched.get(lv.lineage_id)
                partner = next((x.result for x in variant if x.lineage_id == partner_id and x.window == lv.window),
                               None)
                kept += stable_verdict([lv.result, partner]) == lv.result
    return kept / total if total else 0.0
