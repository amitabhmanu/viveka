"""Credentials and contact details for data sources (spec §2).

The pipeline loads them from the git-ignored ``.env`` file, which Claude Code may not
read. Values are never printed, archived or written to run manifests.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

OPENALEX_API_KEY = "OPENALEX_API_KEY"
S2_API_KEY = "S2_API_KEY"
CONTACT_EMAIL = "VIVEKA_CONTACT_EMAIL"


class MissingCredential(RuntimeError):
    pass


def load(root: Path) -> None:
    """Load ``<root>/.env``; variables already set in the environment win."""
    load_dotenv(root / ".env", override=False)


def get(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def require(name: str) -> str:
    value = get(name)
    if value is None:
        raise MissingCredential(f"set {name} in .env (the pipeline reads it; the value is never shown)")
    return value
