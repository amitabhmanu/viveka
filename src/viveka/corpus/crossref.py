"""Crossref adapter: a work's full reference list, the census denominator.

Crossref reference lists have been open by default since 6 June 2022. Each entry carries a DOI
when the publisher deposited one or Crossref matched the reference to a DOI; entries without one
keep their structured fields (year, volume, first page, journal) or unstructured string, which the
census uses to match a sample of them.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from viveka.census import Reference, References
from viveka.corpus.http import Request
from viveka.corpus.ids import normalize_doi

BASE = "https://api.crossref.org"
SOURCE = "crossref"


def work_request(doi: str) -> Request:
    return Request.build(SOURCE, "free", f"{BASE}/works/{quote(doi, safe='')}")


def _text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def reference_of(entry: dict) -> Reference:
    year = re.match(r"\d{4}", str(entry.get("year") or ""))
    return Reference(
        doi=normalize_doi(entry.get("DOI")),
        year=int(year.group()) if year else None,
        volume=_text(entry.get("volume")),
        first_page=_text(entry.get("first-page")),
        journal=_text(entry.get("journal-title")),
        text=_text(entry.get("unstructured")),
        article_title=_text(entry.get("article-title")),
        volume_title=_text(entry.get("volume-title")),
        series_title=_text(entry.get("series-title")),
    )


def references_of(body: dict | None) -> References | None:
    """The work's reference list, or None when Crossref holds none (the work is then unmeasured)."""
    message = (body or {}).get("message") or {}
    refs = message.get("reference") or []
    if not refs:
        return None
    return References(tuple(reference_of(r) for r in refs), SOURCE)
