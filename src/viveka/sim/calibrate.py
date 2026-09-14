"""Grid simulation and the D-7 derivations of δ, c, k, t, h, m and v.

Every threshold is set so that the reading it guards against happens by noise alone
in at most ``alpha`` of replicates, at every size in the grid:

* δ - a symmetric (healthy) community's Δ or Ω interval lying wholly above δ. Because a
  healthy reading needs both intervals wholly inside ±δ, δ is also at least the value at
  which healthy communities of the largest grid size read inside ±δ with probability
  ``power`` (user decision, 14 Sep 2026: the two-sided rule). δ is the larger of the two edges;
* k - a healthy community's L interval lying wholly at or above k;
* t, h - a healthy community's τ or H interval lying wholly below t or h;
* c - an insulated community's insulating-share interval lying wholly below c.

Then v is the citation volume, and m the membership, at the first grid size where Δ
(and, for m, τ too) separates healthy from insulated communities with probability at
least ``power``. The run is deterministic given the registered seed, whatever the
number of worker processes.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

import numpy as np

from viveka.measures.evaluate import measure_commitment
from viveka.measures.types import Interval
from viveka.registry.thresholds import Thresholds
from viveka.sim.config import SimulationConfig
from viveka.sim.generate import simulate_commitment
from viveka.verdict.gates import verdict
from viveka.verdict.params import GateParams

PROFILES = ("healthy", "insulated")


def profile_key(name: str) -> int:
    """A stable integer for a profile name, used in seed spawn keys."""
    return int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:4], "big")


def replicate_rng(seed: int, profile: str, members: int, replicate: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence(entropy=seed,
                                                        spawn_key=(profile_key(profile), members, replicate)))


def measurement_params(thresholds: Thresholds, bootstrap_draws: int | None = None) -> GateParams:
    """Gate parameters sufficient for measuring: the conventions are real, the thresholds being set are NaN."""
    return GateParams(
        n=0, m=0, v=0,
        r=float(thresholds.value("r_min_coverage")),
        lag=float(thresholds.value("l_lag_years")),
        delta=math.nan, c=math.nan, k=math.nan,
        j=float(thresholds.value("j_idle_round_years")),
        t=math.nan, h=math.nan,
        h0=int(thresholds.value("h0_min_met_conditions")),
        interval_level=float(thresholds.value("interval_level")),
        bootstrap_draws=int(bootstrap_draws or thresholds.value("bootstrap_draws")),
        omega_strata=int(thresholds.value("omega_prominence_strata")),
    )


def _iv(interval: Interval | None) -> list[float] | None:
    return None if interval is None else [interval.point, interval.lower, interval.upper]


def simulate_row(task: tuple[SimulationConfig, GateParams, str, int, int]) -> dict:
    """One replicate: generate, measure, and keep every interval. Top-level so worker processes can pickle it."""
    config, params, profile, members, replicate = task
    rng = replicate_rng(config.seed, profile, members, replicate)
    inputs, truth = simulate_commitment(config.profiles[profile], members, config, params.lag, rng)
    m = measure_commitment(inputs, params, rng)
    return {
        "profile": profile, "members": members, "replicate": replicate,
        "results": truth.results, "citations": m.citations_on_claim, "favoured": m.favoured_side.value,
        "oriented": [{"side": o.side.value, "delta": _iv(o.delta), "omega": _iv(o.omega),
                      "share": _iv(o.insulating_share), "loop": _iv(o.loop_length)} for o in m.oriented],
        "tau": _iv(m.tau), "tau_measurable": m.tau_measurable,
        "honoured": _iv(m.honoured), "honoured_measurable": m.honoured_measurable,
    }


@dataclass(frozen=True)
class GridTable:
    rows: tuple[dict, ...]
    replicates: int
    members_grid: tuple[int, ...]
    profiles: tuple[str, ...]
    bootstrap_draws: int
    seed: int

    def at(self, profile: str, members: int) -> list[dict]:
        return [r for r in self.rows if r["profile"] == profile and r["members"] == members]


def run_grid(config: SimulationConfig, params: GateParams, profiles: Sequence[str] = PROFILES, workers: int = 1,
             progress: Callable[[str, int, int, int], None] | None = None) -> GridTable:
    groups = [(profile, members) for profile in profiles for members in config.members_grid]
    rows: list[dict] = []
    executor = ProcessPoolExecutor(max_workers=workers) if workers > 1 else None
    try:
        for done, (profile, members) in enumerate(groups, start=1):
            tasks = [(config, params, profile, members, r) for r in range(config.replicates)]
            if executor:
                rows.extend(executor.map(simulate_row, tasks, chunksize=max(1, len(tasks) // (workers * 4))))
            else:
                rows.extend(map(simulate_row, tasks))
            if progress:
                progress(profile, members, done, len(groups))
    finally:
        if executor:
            executor.shutdown()
    return GridTable(tuple(rows), config.replicates, tuple(config.members_grid), tuple(profiles),
                     params.bootstrap_draws, config.seed)


# ---------------------------------------------------------------- derivations


def _lower(iv: list[float] | None) -> float:
    return -math.inf if iv is None else iv[1]


def _upper(iv: list[float] | None) -> float:
    return math.inf if iv is None else iv[2]


def _widest_bound(oriented: dict) -> float:
    """The largest |bound| of an orientation's Δ and Ω intervals; infinite if either is missing."""
    bounds = []
    for iv in (oriented["delta"], oriented["omega"]):
        if iv is None:
            return math.inf
        bounds += [abs(iv[1]), abs(iv[2])]
    return max(bounds)


def derive_thresholds(table: GridTable, alpha: float, power: float) -> dict:
    delta_by_size, k_by_size, t_by_size, h_by_size, c_by_size = [], [], [], [], []
    for members in table.members_grid:
        healthy, insulated = table.at("healthy", members), table.at("insulated", members)
        n, allowed = len(healthy), math.floor(alpha * len(healthy))

        # δ: at most `allowed` healthy replicates with a Δ or Ω lower bound strictly above δ.
        stats = sorted(max((max(_lower(o["delta"]), _lower(o["omega"])) for o in r["oriented"]), default=-math.inf)
                       for r in healthy)
        edge = stats[n - allowed - 1]
        delta_by_size.append(max(0.0, edge) if math.isfinite(edge) else 0.0)

        # k: at most `allowed` healthy replicates with an L lower bound at or above k.
        loops = sorted(max((max(_lower(o["loop"]), 0.0) for o in r["oriented"]), default=0.0) for r in healthy)
        k_by_size.append(math.floor(loops[n - allowed - 1]) + 1)

        # t, h: at most `allowed` healthy replicates with a measurable upper bound strictly below the threshold.
        for key, measurable, bucket in (("tau", "tau_measurable", t_by_size), ("honoured", "honoured_measurable",
                                                                                h_by_size)):
            uppers = sorted(r[key][2] for r in healthy if r[measurable] and r[key] is not None)
            if len(uppers) > allowed:
                bucket.append(uppers[allowed])

        # c: at most `allowed_i` insulated replicates whose insulating-share upper bound lies strictly below c.
        allowed_i = math.floor(alpha * len(insulated))
        uppers = sorted(u for u in (max((_upper(o["share"]) for o in r["oriented"]), default=math.inf)
                                    for r in insulated) if math.isfinite(u))
        if len(uppers) > allowed_i:
            c_by_size.append(uppers[allowed_i])

    false_insulated_edge = max(delta_by_size) if delta_by_size else None
    # Healthy reach: at the largest size, the smallest δ with both intervals inside ±δ in `power` of replicates.
    reach = sorted(max((_widest_bound(o) for o in r["oriented"]), default=math.inf)
                   for r in table.at("healthy", max(table.members_grid)))
    reach_edge = reach[math.ceil(power * len(reach)) - 1] if reach else math.inf
    if false_insulated_edge is None:
        delta = None
    elif math.isfinite(reach_edge):
        delta = max(false_insulated_edge, reach_edge)
    else:
        delta = false_insulated_edge

    return {
        "delta": delta,
        "details": {"delta_false_insulated_edge": false_insulated_edge,
                    "delta_healthy_reach_edge": reach_edge if math.isfinite(reach_edge) else None},
        "k": max(k_by_size) if k_by_size else None,
        "t": min(t_by_size) if t_by_size else None,
        "h": min(h_by_size) if h_by_size else None,
        "c": min(c_by_size) if c_by_size else None,
    }


def derive_sizes(table: GridTable, thresholds: dict, power: float) -> dict:
    delta, t = thresholds["delta"], thresholds["t"]
    m = v = None
    per_size = []
    for members in table.members_grid:
        healthy, insulated = table.at("healthy", members), table.at("insulated", members)

        def rate(rows, predicate):
            return sum(bool(predicate(r)) for r in rows) / len(rows) if rows else 0.0

        delta_symmetric = rate(healthy, lambda r: r["oriented"] and all(
            o["delta"] is not None and o["delta"][1] >= -delta and o["delta"][2] <= delta for o in r["oriented"]))
        delta_asymmetric = rate(insulated, lambda r: any(
            o["delta"] is not None and o["delta"][1] > delta for o in r["oriented"]))
        if t is None:
            tau_healthy = tau_insulated = 0.0
        else:
            tau_healthy = rate(healthy, lambda r: r["tau_measurable"] and r["tau"] is not None and r["tau"][1] > t)
            tau_insulated = rate(insulated, lambda r: r["tau_measurable"] and r["tau"] is not None
                                 and r["tau"][2] < t)
        citations = int(min(np.median([r["citations"] for r in healthy]),
                            np.median([r["citations"] for r in insulated])))
        per_size.append({"members": members, "citations": citations, "delta_symmetric": delta_symmetric,
                         "delta_asymmetric": delta_asymmetric, "tau_healthy": tau_healthy,
                         "tau_insulated": tau_insulated})
        delta_separates = delta_symmetric >= power and delta_asymmetric >= power
        if v is None and delta_separates:
            v = citations
        if m is None and delta_separates and tau_healthy >= power and tau_insulated >= power:
            m = members
    return {"m": m, "v": v, "per_size": per_size}


def derive(table: GridTable, config: SimulationConfig) -> dict:
    thresholds = derive_thresholds(table, config.alpha, config.power)
    details = thresholds.pop("details")
    sizes = derive_sizes(table, thresholds, config.power) if thresholds["delta"] is not None else \
        {"m": None, "v": None, "per_size": []}
    return {
        "values": {**thresholds, "m": sizes["m"], "v": sizes["v"]},
        "details": details,
        "per_size": sizes["per_size"],
        "settings": {"alpha": config.alpha, "power": config.power, "replicates": table.replicates,
                     "bootstrap_draws": table.bootstrap_draws, "seed": table.seed,
                     "members_grid": list(table.members_grid)},
    }


def recovery(profile: str, members: int, params: GateParams, config: SimulationConfig, replicates: int,
             seed: int) -> dict[str, int]:
    """How often a planted profile reads as each verdict (and reason) under complete gate parameters."""
    counts: dict[str, int] = {}
    for replicate in range(replicates):
        rng = replicate_rng(seed, profile, members, replicate)
        inputs, _ = simulate_commitment(config.profiles[profile], members, config, params.lag, rng)
        result = verdict(measure_commitment(inputs, params, rng), params)
        key = result.verdict.value + (f" · {result.reason.value}" if result.reason else "")
        counts[key] = counts.get(key, 0) + 1
    return counts
