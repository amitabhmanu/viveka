"""Identifier normalisation shared by the source adapters."""

from __future__ import annotations

from collections.abc import Sequence

_DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:")


def short_id(value: str | None) -> str | None:
    """``https://openalex.org/W123`` -> ``W123``; bare ids pass through."""
    if not value:
        return None
    return str(value).rstrip("/").rsplit("/", 1)[-1]


def normalize_doi(value: str | None) -> str | None:
    """Lower-case DOI without resolver prefix, or None."""
    if not value:
        return None
    doi = str(value).strip()
    for prefix in _DOI_PREFIXES:
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
            break
    doi = doi.strip().lower()
    return doi or None


def chunks[T](items: Sequence[T], size: int) -> list[list[T]]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]
