"""Writing simulated values into the draft thresholds registry, with provenance.

Only parameters whose status is ``simulated`` are written, each with the run that
produced it as ``source_run``. The file is edited round-trip, so comments and layout
survive, and the write is recorded in the change ledger as a change plus a reason,
exactly as a hand edit would be.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from pathlib import Path

from ruamel.yaml import YAML

from viveka import ledger
from viveka.hashing import sha256_file
from viveka.paths import RUNS
from viveka.registry.thresholds import THRESHOLDS

PARAMETER_NAMES = {
    "delta": "delta",
    "c": "c_max_insulating_share",
    "k": "k_min_loop",
    "t": "t_tau_threshold",
    "h": "h_honoured_threshold",
    "m": "m_min_members",
    "v": "v_min_citations",
}


class DraftWriteRefused(RuntimeError):
    pass


def _round(value: float | int | None) -> float | int | None:
    if value is None or isinstance(value, int):
        return value
    return round(float(value), 6)


def write_draft(root: Path, values: Mapping[str, float | int | None], run_id: str, reason: str) -> dict:
    if not (root / RUNS / run_id / "manifest.json").is_file():
        raise DraftWriteRefused(f"run {run_id} has no manifest; simulated values need a verifiable source run")
    path = root / THRESHOLDS
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    # Keep the file's explicit `null` spelling; ruamel's default would write nothing after the colon.
    yaml.representer.add_representer(
        type(None), lambda representer, _: representer.represent_scalar("tag:yaml.org,2002:null", "null"))
    data = yaml.load(path.read_text(encoding="utf-8"))
    parameters = data["parameters"]

    written = {}
    for key, name in PARAMETER_NAMES.items():
        entry = parameters[name]
        if entry["status"] != "simulated":
            raise DraftWriteRefused(f"{name} has status {entry['status']!r}; only simulated parameters are written")
        if key not in values:
            continue
        entry["value"] = _round(values[key])
        entry["source_run"] = run_id
        written[name] = entry["value"]

    sha_before = sha256_file(path)
    buffer = io.StringIO()
    yaml.dump(data, buffer)
    path.write_bytes(buffer.getvalue().encode("utf-8"))

    change_id = ledger.new_id("chg")
    ledger.append(root, {"id": change_id, "type": "change", "time": ledger.now_iso(), "session_id": None,
                         "tool": "viveka sim thresholds", "path": THRESHOLDS, "sha_before": sha_before,
                         "sha_after": sha256_file(path)})
    ledger.append(root, {"id": ledger.new_id("rsn"), "type": "reason", "time": ledger.now_iso(),
                         "session_id": None, "for": [change_id], "reason": reason, "decision": "D-7"})
    return written
