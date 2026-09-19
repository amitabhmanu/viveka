"""Typed access to registry/thresholds.yaml and registry/fitted.yaml.

Decision D-11 (19 Sep 2026) splits the parameters: values set by simulation or convention live in
``thresholds`` and freeze before any cluster sizes are seen; n, fitted on calibration fields at M8, lives in
``fitted`` and freezes on its own. The loader reads both files into one set of parameters.

``PARAMETERS`` lists every parameter the code may use. The loader rejects a
thresholds file that lacks any of them (spec §5: "the loader must reject a
registry with any parameter used by code but missing from the file"), and
reading a parameter whose value is still null raises instead of returning None.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from viveka.registry.errors import MissingParameter, RegistryError, UnsetParameter

THRESHOLDS = "registry/thresholds.yaml"
FITTED = "registry/fitted.yaml"

FITTED_PARAMETERS: tuple[str, ...] = ("n_min_disconfirmations",)

THRESHOLD_PARAMETERS: tuple[str, ...] = (
    "m_min_members",
    "v_min_citations",
    "r_min_coverage",
    "l_lag_years",
    "delta",
    "delta_margin",
    "c_max_insulating_share",
    "k_min_loop",
    "j_idle_round_years",
    "interval_level",
    "t_tau_threshold",
    "h_honoured_threshold",
    "h0_min_met_conditions",
    "w_window_years",
    "o_min_overlap",
    "sweep",
    "e_max_error_share",
    "i_max_indeterminate_share",
    "kappa_min",
    "q_min_coders",
    "g_max_leakage_pp",
    "s_max_label_change_share",
    "bootstrap_draws",
    "omega_prominence_strata",
)

PARAMETERS: tuple[str, ...] = FITTED_PARAMETERS + THRESHOLD_PARAMETERS

_CORE_KEYS = {"symbol", "used_in", "meaning", "value", "status", "source_run"}


@dataclass(frozen=True)
class Parameter:
    name: str
    symbol: str
    value: Any
    status: str
    source_run: str | None
    extra: dict = field(default_factory=dict)


class Thresholds:
    def __init__(self, parameters: dict[str, Parameter], version: int, state: str):
        self._parameters = parameters
        self.version = version
        self.state = state

    def parameter(self, name: str) -> Parameter:
        if name not in PARAMETERS:
            raise KeyError(f"{name!r} is not a registered parameter")
        return self._parameters[name]

    def value(self, name: str) -> Any:
        p = self.parameter(name)
        if p.value is None:
            raise UnsetParameter(f"parameter {name} ({p.symbol}) has no value yet (status: {p.status})")
        return p.value

    __getitem__ = value

    def unset(self) -> list[str]:
        return [n for n in PARAMETERS if self._parameters[n].value is None]

    def overridden(self, **values: Any) -> Thresholds:
        """An in-memory copy with some values replaced, for diagnostics; the registry file is untouched."""
        parameters = dict(self._parameters)
        for name, value in values.items():
            parameters[name] = replace(self.parameter(name), value=value, source_run=None)
        return Thresholds(parameters, version=self.version, state=self.state)


def _read(root: Path, rel: str, names: tuple[str, ...]) -> tuple[dict, dict[str, Parameter]]:
    try:
        data = yaml.safe_load((root / rel).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RegistryError(f"cannot read {rel}: {exc}") from exc
    raw = (data or {}).get("parameters") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        raise RegistryError(f"{rel} has no 'parameters' mapping")
    missing = [name for name in names if name not in raw]
    if missing:
        raise MissingParameter(f"{rel} is missing parameters used by the code: {', '.join(missing)}")
    parameters = {}
    for name in names:
        entry = raw[name] or {}
        parameters[name] = Parameter(
            name=name,
            symbol=str(entry.get("symbol", name)),
            value=entry.get("value"),
            status=str(entry.get("status")),
            source_run=entry.get("source_run"),
            extra={k: v for k, v in entry.items() if k not in _CORE_KEYS},
        )
    return data, parameters


def load_thresholds(root: Path) -> Thresholds:
    """Both parameter files as one set; version and state are the thresholds file's."""
    data, parameters = _read(root, THRESHOLDS, THRESHOLD_PARAMETERS)
    _, fitted = _read(root, FITTED, FITTED_PARAMETERS)
    merged = {**fitted, **parameters}
    return Thresholds({name: merged[name] for name in PARAMETERS}, version=int(data.get("version", 0)),
                      state=str(data.get("state", "draft")))
