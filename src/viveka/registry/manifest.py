"""Reading and writing registry/FROZEN.json.

Shape (format 1)::

    {"format": 1, "version": 3,
     "components": {"thresholds": {"sha256": "sha256:...", "files": ["registry/thresholds.yaml"],
                                   "file_sha256": {"registry/thresholds.yaml": "sha256:..."},
                                   "frozen_in": 2, "frozen_at": "...", "ledger_id": "frz_..."}}}

The Claude Code hooks read ``version`` and ``components[*].files`` from this file
(.claude/hooks/_common.py), so those keys must keep their meaning.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from viveka.hashing import sha256_bytes
from viveka.paths import FROZEN
from viveka.registry.errors import RegistryError

FORMAT = 1


def empty() -> dict:
    return {"format": FORMAT, "version": 0, "components": {}}


def read(root: Path) -> dict:
    path = root / FROZEN
    if not path.exists():
        return empty()
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegistryError(f"{FROZEN} is not valid JSON: {exc}") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != FORMAT
        or not isinstance(manifest.get("version"), int)
        or not isinstance(manifest.get("components"), dict)
    ):
        raise RegistryError(f"{FROZEN} does not have the expected format {FORMAT} shape")
    return manifest


def write(root: Path, manifest: dict) -> None:
    """Write atomically: a crash leaves either the old manifest or the new one, never half of one."""
    path = root / FROZEN
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def content_hash(manifest: dict) -> str:
    """Hash of the frozen content only: version and each component's tree hash."""
    core = {
        "version": manifest["version"],
        "components": {name: comp["sha256"] for name, comp in sorted(manifest["components"].items())},
    }
    return sha256_bytes(json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def frozen_names(manifest: dict) -> list[str]:
    return sorted(manifest["components"])
