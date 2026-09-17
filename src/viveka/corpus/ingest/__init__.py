"""Community venues ingested from their own archives (framework corpus row; decisions D-1, D-8).

A venue that OpenAlex does not index is listed by its adapter (``registry/corpus.yaml``, ``ingestion``):
each paper becomes a work with a local id ``X:<venue>:<key>``, its authors are kept by name, and its
document (a web page or PDF) is fetched only when the census samples it. Every response goes through the
same archive as the bibliographic APIs, so a run replays exactly.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

from viveka.census import References
from viveka.corpus.config import Venue
from viveka.corpus.http import Fetcher, Request
from viveka.corpus.ingest import text as extract

PREFIX = "X:"


@dataclass(frozen=True)
class Author:
    family: str
    given: str | None = None


@dataclass(frozen=True)
class IngestedWork:
    venue: str
    key: str
    title: str
    year: int | None
    volume: str | None
    issue: str | None
    first_page: str | None
    authors: tuple[Author, ...]
    work_type: str
    document_url: str | None

    @property
    def work_id(self) -> str:
        return f"{PREFIX}{self.venue}:{self.key}"


def is_ingested(work_id: str) -> bool:
    return work_id.startswith(PREFIX)


def document_request(venue_id: str, url: str) -> Request:
    return Request.build(venue_id, "document", url)


def fold_name(name: str) -> str:
    """A name without accents, case or punctuation, for matching authors across citations."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z]", "", plain.lower())


def author_id(author: Author) -> str:
    initial = fold_name(author.given or "")[:1]
    return f"name:{fold_name(author.family)}:{initial}"


def rows(works: list[IngestedWork], venue: Venue) -> dict[str, list[dict]]:
    """Table rows for listed works: works, authors and authorships by name, and the venue catalogue."""
    out: dict[str, list[dict]] = {"works": [], "authors": [], "authorships": [], "ingested": []}
    for w in works:
        out["works"].append({"work_id": w.work_id, "doi": None, "title": w.title, "year": w.year,
                             "venue_id": f"{PREFIX}{venue.venue_id}", "venue_name": venue.name, "type": w.work_type,
                             "cited_by_count": None, "source": venue.venue_id})
        out["ingested"].append({"work_id": w.work_id, "venue": venue.venue_id, "volume": w.volume, "issue": w.issue,
                                "first_page": w.first_page,
                                "first_author": fold_name(w.authors[0].family) if w.authors else None,
                                "document_url": w.document_url})
        for i, a in enumerate(w.authors):
            position = "first" if i == 0 else "last" if i == len(w.authors) - 1 else "middle"
            out["authors"].append({"author_id": author_id(a), "display_name": " ".join(p for p in (a.given, a.family)
                                                                                     if p),
                                   "disambiguation_source": "name", "confidence": None})
            out["authorships"].append({"work_id": w.work_id, "author_id": author_id(a), "position": position,
                                       "institution_ids": []})
    return out


def references(fetcher: Fetcher, venue_id: str, document_url: str | None) -> References | None:
    """A sampled work's reference list from its archived document, or None (the work is then unmeasured)."""
    if not document_url:
        return None
    document = fetcher.get_document(document_request(venue_id, document_url))
    if document.status != 200 or document.content is None:
        return None
    is_pdf = (document.content_type or "").endswith("pdf") or document.content[:5] == b"%PDF-"
    text = extract.pdf_text(document.content) if is_pdf else extract.html_reference_text(document.content)
    return extract.extract_references(text, paragraphs=not is_pdf)


def _adapters() -> dict[str, Callable[[Fetcher, Venue, int, int], list[IngestedWork]]]:
    from viveka.corpus.ingest import arj, eprints, orthomolecular

    return {"eprints_json_v1": eprints.list_works, "orthomolecular_toc_v1": orthomolecular.list_works,
            "arj_volumes_v1": arj.list_works}


def list_works(fetcher: Fetcher, venue: Venue, start: int, end: int) -> list[IngestedWork]:
    adapters = _adapters()
    if venue.adapter not in adapters:
        raise ValueError(f"venue {venue.venue_id}: unknown adapter {venue.adapter!r}")
    return [w for w in adapters[venue.adapter](fetcher, venue, start, end)
            if w.year is not None and start <= w.year <= end]
