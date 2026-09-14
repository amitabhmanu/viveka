"""Membership-level lineage scenarios: communities over dated windows, with churn, branching and closure.

Edge-level network generation belongs to M5, where community detection needs it.
Here each lineage is a set of member ids per window. Members churn from window to
window; a branch starts from part of its parent's membership, so the two share
ancestry; and a lineage that lets the claim go is closed after its last engaged
window.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import yaml

from viveka.measures.evaluate import measure_commitment
from viveka.sim.config import SimulationConfig
from viveka.sim.generate import simulate_commitment
from viveka.verdict.field_summary import LineageVerdict, Summary
from viveka.verdict.gates import verdict
from viveka.verdict.params import GateParams
from viveka.verdict.reasons import Verdict, VerdictResult


@dataclass(frozen=True)
class LineageSpec:
    lineage_id: str
    start: int
    members: int
    profile: str
    parent: str | None = None
    end: int | None = None  # last window in which the lineage engages the claim; closed afterwards


@dataclass(frozen=True)
class Scenario:
    name: str
    windows: int
    root: str
    predicted: Summary
    lineages: tuple[LineageSpec, ...]

    def parents(self) -> dict[str, list[str]]:
        return {spec.lineage_id: [spec.parent] if spec.parent else [] for spec in self.lineages}


def membership(scenario: Scenario, churn: float, rng: np.random.Generator) -> list[dict[str, frozenset[str]]]:
    """Member-id sets per window for every lineage that has started."""
    counter = 0
    current: dict[str, list[str]] = {}
    by_window: list[dict[str, frozenset[str]]] = []

    def fresh(count: int) -> list[str]:
        nonlocal counter
        ids = [f"u{counter + i}" for i in range(count)]
        counter += count
        return ids

    for window in range(scenario.windows):
        snapshot: dict[str, frozenset[str]] = {}
        for spec in scenario.lineages:
            if window < spec.start:
                continue
            if spec.lineage_id not in current:
                inherited: list[str] = []
                if spec.parent and spec.parent in current:
                    pool = current[spec.parent]
                    take = min(len(pool), spec.members) // 2
                    inherited = list(rng.choice(pool, size=take, replace=False)) if take else []
                current[spec.lineage_id] = inherited + fresh(spec.members - len(inherited))
            else:
                members = current[spec.lineage_id]
                leaving = int(round(churn * len(members)))
                keep = list(rng.choice(members, size=len(members) - leaving, replace=False)) if leaving else members
                current[spec.lineage_id] = keep + fresh(leaving)
            snapshot[spec.lineage_id] = frozenset(current[spec.lineage_id])
        by_window.append(snapshot)
    return by_window


def simulate_scenario(scenario: Scenario, config: SimulationConfig, params: GateParams, rng: np.random.Generator,
                      member_scale: float = 1.0) -> list[LineageVerdict]:
    """A verdict for every lineage in every window it exists; windows after a lineage's end are closed."""
    verdicts = []
    for window in range(scenario.windows):
        for spec in scenario.lineages:
            if window < spec.start:
                continue
            if spec.end is not None and window > spec.end:
                verdicts.append(LineageVerdict(spec.lineage_id, (window, window), VerdictResult(Verdict.CLOSED)))
                continue
            members = max(1, round(spec.members * member_scale))
            inputs, _ = simulate_commitment(config.profiles[spec.profile], members, config, params.lag, rng)
            verdicts.append(LineageVerdict(spec.lineage_id, (window, window),
                                           verdict(measure_commitment(inputs, params, rng), params)))
    return verdicts


def scenarios_from_mapping(data: Mapping) -> list[Scenario]:
    out = []
    for item in data["scenarios"]:
        lineages = tuple(
            LineageSpec(lineage_id=str(spec["id"]), start=int(spec.get("start", 0)), members=int(spec["members"]),
                        profile=str(spec["profile"]), parent=spec.get("parent"),
                        end=None if spec.get("end") is None else int(spec["end"]))
            for spec in item["lineages"]
        )
        out.append(Scenario(str(item["name"]), int(item["windows"]), str(item["root"]), Summary(item["predicted"]),
                            lineages))
    return out


def load_scenarios(text: str) -> list[Scenario]:
    return scenarios_from_mapping(yaml.safe_load(text))
