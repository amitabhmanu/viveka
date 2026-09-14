"""Simulation settings (registry/simulation.yaml) as immutable objects."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SIMULATION = "registry/simulation.yaml"


@dataclass(frozen=True)
class Profile:
    name: str
    cite_favourable: float
    cite_unfavourable: float
    discount_favourable: float
    discount_unfavourable: float
    uncheckable_unfavourable: float
    ledger: Mapping[str, float]
    rounds: Mapping[str, float]
    retention_after_break: float
    retention_after_baseline: float
    honoured: float


@dataclass(frozen=True)
class CoderFamily:
    name: str
    kind: str
    flip_rate: float


@dataclass(frozen=True)
class SimulationConfig:
    alpha: float
    power: float
    replicates: int
    seed: int
    members_grid: tuple[int, ...]
    results_per_member: float
    qualifying_breaks_per_member: float
    baseline_changes_per_member: float
    ties_per_member: float
    disconfirmations_per_window: int
    met_conditions_per_window: int
    support_share: float
    filter_property_probability: float
    window_end: int
    window_length_years: int
    profiles: Mapping[str, Profile]
    families: tuple[CoderFamily, ...]

    def replace(self, **changes: Any) -> SimulationConfig:
        return dataclasses.replace(self, **changes)

    def with_profile(self, name: str, **changes: Any) -> SimulationConfig:
        """A copy with one profile added or modified (used to build planted variants)."""
        base = self.profiles.get(name) or self.profiles["healthy"]
        profiles = dict(self.profiles)
        profiles[name] = dataclasses.replace(base, name=name, **changes)
        return dataclasses.replace(self, profiles=profiles)


def from_mapping(data: Mapping[str, Any]) -> SimulationConfig:
    rates, evidence, control = data["rates"], data["evidence"], data["control"]
    profiles = {
        name: Profile(name=name, **{k: (dict(v) if isinstance(v, Mapping) else v) for k, v in spec.items()})
        for name, spec in data["profiles"].items()
    }
    return SimulationConfig(
        alpha=float(control["alpha"]),
        power=float(control["power"]),
        replicates=int(control["replicates"]),
        seed=int(control["seed"]),
        members_grid=tuple(int(m) for m in data["grid"]["members"]),
        results_per_member=float(rates["results_per_member"]),
        qualifying_breaks_per_member=float(rates["qualifying_breaks_per_member"]),
        baseline_changes_per_member=float(rates["baseline_changes_per_member"]),
        ties_per_member=float(rates["ties_per_member"]),
        disconfirmations_per_window=int(rates["disconfirmations_per_window"]),
        met_conditions_per_window=int(rates["met_conditions_per_window"]),
        support_share=float(evidence["support_share"]),
        filter_property_probability=float(evidence["filter_property_probability"]),
        window_end=int(evidence["window_end"]),
        window_length_years=int(evidence["window_length_years"]),
        profiles=profiles,
        families=tuple(CoderFamily(str(c["name"]), str(c["kind"]), float(c["flip_rate"])) for c in data["coders"]),
    )


def load_simulation_config(root: Path) -> SimulationConfig:
    return from_mapping(yaml.safe_load((root / SIMULATION).read_text(encoding="utf-8")))


def tiny(**changes: Any) -> SimulationConfig:
    """Registered profiles and coder model on a small grid, for fast tests."""
    here = Path(__file__).resolve().parents[3]
    base = load_simulation_config(here) if (here / SIMULATION).is_file() else None
    if base is None:
        raise FileNotFoundError(f"{SIMULATION} not found next to the package")
    return base.replace(replicates=12, members_grid=(20, 80), **changes)
