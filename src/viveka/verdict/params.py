"""Gate parameters, taken from the registry's thresholds."""

from __future__ import annotations

from dataclasses import dataclass

from viveka.registry.thresholds import Thresholds


@dataclass(frozen=True)
class GateParams:
    n: int  # minimum disconfirmations old enough to have drawn a response
    m: int  # minimum members
    v: int  # minimum citations bearing on the claim
    r: float  # minimum coverage
    lag: float  # ℓ, years allowed for a response
    delta: float  # δ
    c: float  # largest insulating share compatible with S
    k: float  # shortest loop compatible with A
    j: float  # idle-round horizon, years
    t: float  # τ threshold
    h: float  # H threshold
    h0: int  # met conditions before H is measurable
    interval_level: float
    bootstrap_draws: int
    omega_strata: int

    @classmethod
    def from_thresholds(cls, th: Thresholds) -> GateParams:
        """Raises UnsetParameter for any value the registry has not set yet."""
        return cls(
            n=int(th["n_min_disconfirmations"]),
            m=int(th["m_min_members"]),
            v=int(th["v_min_citations"]),
            r=float(th["r_min_coverage"]),
            lag=float(th["l_lag_years"]),
            delta=float(th["delta"]),
            c=float(th["c_max_insulating_share"]),
            k=float(th["k_min_loop"]),
            j=float(th["j_idle_round_years"]),
            t=float(th["t_tau_threshold"]),
            h=float(th["h_honoured_threshold"]),
            h0=int(th["h0_min_met_conditions"]),
            interval_level=float(th["interval_level"]),
            bootstrap_draws=int(th["bootstrap_draws"]),
            omega_strata=int(th["omega_prominence_strata"]),
        )
