"""Crossref adapter: a work's full reference list, the census denominator.

Crossref reference lists have been open by default since 6 June 2022. Each entry carries a DOI
when the publisher deposited one or Crossref matched the reference to a DOI.
"""

from __future__ import annotations

from urllib.parse import quote

from viveka.census import References
from viveka.corpus.http import Request
from viveka.corpus.ids import normalize_doi

BASE = "https://api.crossref.org"
SOURCE = "crossref"


def work_request(doi: str) -> Request:
    return Request.build(SOURCE, "free", f"{BASE}/works/{quote(doi, safe='')}")


def references_of(body: dict | None) -> References | None:
    """The work's reference list, or None when Crossref holds none (the work is then unmeasured)."""
    message = (body or {}).get("message") or {}
    refs = message.get("reference") or []
    if not refs:
        return None
    return References(tuple(normalize_doi(r.get("DOI")) for r in refs), SOURCE)
