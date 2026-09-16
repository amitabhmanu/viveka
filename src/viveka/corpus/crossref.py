"""Crossref adapter: a work's full reference list, the census denominator.

Crossref reference lists have been open by default since 6 June 2022. Each entry carries a DOI
when the publisher deposited one or Crossref matched the reference to a DOI; entries without one
keep their structured fields (year, volume, first page, journal) or unstructured string, which the
census uses to match a sample of them.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from viveka.census import Candidate, Reference, References
from viveka.corpus.http import Request
from viveka.corpus.ids import normalize_doi

BASE = "https://api.crossref.org"
SOURCE = "crossref"


def work_request(doi: str) -> Request:
    return Request.build(SOURCE, "free", f"{BASE}/works/{quote(doi, safe='')}")


def bibliographic_request(query: str) -> Request:
    """Crossref's matcher for citation strings: the top items it considers the cited work (free)."""
    return Request.build(SOURCE, "free", f"{BASE}/works", rows=3,
                         select="DOI,title,container-title,volume,page,issued,type,score",
                         **{"query.bibliographic": query})


def candidates_of(body: dict | None) -> list[Candidate]:
    candidates = []
    for item in ((body or {}).get("message") or {}).get("items") or []:
        parts = ((item.get("issued") or {}).get("date-parts") or [[None]])[0] or [None]
        page = str(item.get("page") or "").split("-")[0].strip()
        candidates.append(Candidate(
            doi=normalize_doi(item.get("DOI")),
            score=float(item.get("score") or 0.0),
            year=parts[0] if isinstance(parts[0], int) else None,
            volume=_text(item.get("volume")),
            first_page=page or None,
            journal=_text((item.get("container-title") or [None])[0]),
            title=_text((item.get("title") or [None])[0]),
            kind=_text(item.get("type")),
        ))
    return candidates


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
