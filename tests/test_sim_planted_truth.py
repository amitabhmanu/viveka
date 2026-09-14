"""Spec §15 "Planted truth": planted profiles are recovered, and never read the wrong way round.

The gate thresholds are not hand-picked: they are derived (decision D-7, two-sided δ rule)
from a small simulated grid of the registered profiles, exactly as the registry run does.
"""

import dataclasses
import math

import pytest

from viveka.sim.calibrate import derive, recovery, run_grid
from viveka.sim.config import tiny
from viveka.verdict.params import GateParams

MEASURING = GateParams(n=0, m=0, v=0, r=0.7, lag=2.0, delta=math.nan, c=math.nan, k=math.nan, j=10.0, t=math.nan,
                       h=math.nan, h0=3, interval_level=0.9, bootstrap_draws=60, omega_strata=5)


def planted_config():
    cfg = tiny()
    insulated = cfg.profiles["insulated"]
    profiles = dict(cfg.profiles)
    profiles["filter_asymmetric"] = dataclasses.replace(insulated, name="filter_asymmetric", cite_unfavourable=0.8)
    profiles["omission_asymmetric"] = dataclasses.replace(insulated, name="omission_asymmetric",
                                                          discount_unfavourable=0.3, uncheckable_unfavourable=0.0)
    return cfg.replace(profiles=profiles)


@pytest.fixture(scope="module")
def derived_params():
    cfg = planted_config()
    values = derive(run_grid(cfg, MEASURING), cfg)["values"]
    return dataclasses.replace(
        MEASURING, n=2, m=min(cfg.members_grid), v=0,
        delta=values["delta"],
        c=values["c"] if values["c"] is not None else 1.0,
        k=float(values["k"]),
        t=values["t"] if values["t"] is not None else 0.0,
        h=values["h"] if values["h"] is not None else 0.0,
    )


def rate(counts, verdict):
    return sum(c for k, c in counts.items() if k.split(" · ")[0] == verdict) / sum(counts.values())


@pytest.mark.parametrize(
    ("profile", "expected", "wrong"),
    [
        ("healthy", "healthy", "insulated"),
        ("insulated", "insulated", "healthy"),
        ("filter_asymmetric", "insulated", "healthy"),
        ("omission_asymmetric", "insulated", "healthy"),
    ],
)
def test_planted_profiles_are_recovered_and_never_reversed(derived_params, profile, expected, wrong):
    counts = recovery(profile, 80, derived_params, planted_config(), replicates=12, seed=99)
    assert rate(counts, wrong) <= 1 / 12, (derived_params, counts)
    assert rate(counts, expected) >= 0.5, (derived_params, counts)


@pytest.mark.slow
@pytest.mark.parametrize("profile", ["healthy", "insulated", "filter_asymmetric", "omission_asymmetric"])
def test_recovery_rates_replicate_across_independent_seeds(derived_params, profile):
    cfg = planted_config()
    expected = "healthy" if profile == "healthy" else "insulated"
    first = rate(recovery(profile, 80, derived_params, cfg, replicates=60, seed=1), expected)
    second = rate(recovery(profile, 80, derived_params, cfg, replicates=60, seed=2), expected)
    p = (first + second) / 2
    tolerance = 3 * math.sqrt(max(p * (1 - p), 0.01) * 2 / 60)
    assert abs(first - second) <= tolerance, (first, second)
