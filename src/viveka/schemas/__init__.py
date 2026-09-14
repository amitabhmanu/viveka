"""JSON Schemas shipped with the package (ledger records, run manifests)."""

from __future__ import annotations

import json
from functools import cache
from importlib import resources


@cache
def load(name: str) -> dict:
    """Load ``<name>.schema.json`` from this package."""
    text = resources.files(__name__).joinpath(f"{name}.schema.json").read_text(encoding="utf-8")
    return json.loads(text)
