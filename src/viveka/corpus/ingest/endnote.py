"""Adapter ``endnote_v1``: a library's EndNote export (LENR-CANR.org's ``EndNoteExport.txt``, for the ICCF
proceedings; decision D-8).

The export is one tagged-text file with a record per item: ``%0`` type, ``%A`` authors ("Family, I."),
``%D`` year, ``%T`` title, ``%B`` the proceedings or journal, ``%V`` volume, ``%P`` pages and ``%U`` the
PDF. A record belongs to the venue when its ``%B`` matches the venue's registered ``record_pattern`` and its
year is not after ``last_year``. The record type maps to a work type through ``types``.

Many PDF links carry a ``#page=`` fragment that skips a cover page; for a PDF of one paper the fragment is
dropped. A PDF linked from several records is a whole volume, and each fragment is where a paper starts: a
paper then reads from its start page to the page before the next paper's (the last to the volume's end),
recorded as ``<url>#pages=<a>-<b>``, and the volume is fetched and archived once. A record in a volume
without a start page gets no document, since its pages cannot be told apart, and its paper is unmeasured.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict

from viveka.corpus.config import Venue
from viveka.corpus.http import Fetcher
from viveka.corpus.ingest import Author, IngestedWork, document_request, fold_name

_TAG = re.compile(r"^%(\S) ?(.*)$")


def export_request(venue: Venue):
    return document_request(venue.venue_id, venue.url)


def records(content: bytes) -> list[dict[str, list[str]]]:
    """Every record of an EndNote tagged export, as tag -> values in order."""
    text = content.decode("cp1252", errors="replace")
    out: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] | None = None
    for line in text.splitlines():
        m = _TAG.match(line)
        if not m:
            continue
        tag, value = m.group(1), m.group(2).strip()
        if tag == "0":
            current = defaultdict(list)
            out.append(current)
        if current is not None and value:
            current[tag].append(value)
    return [dict(r) for r in out]


def _author(name: str) -> Author | None:
    family, _, given = name.partition(",")
    family = " ".join(family.split())
    return Author(family, " ".join(given.split()) or None) if fold_name(family) else None


def _key(year: int | None, title: str, authors: tuple[Author, ...]) -> str:
    basis = f"{year}|{' '.join(title.lower().split())}|{fold_name(authors[0].family) if authors else ''}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]


def _start(record: dict[str, list[str]]) -> tuple[str | None, int | None]:
    """A record's PDF (without fragment) and the page its ``#page=`` fragment points to."""
    url = (record.get("U") or [None])[0]
    if not url or not url.lower().split("#")[0].endswith(".pdf"):
        return None, None
    m = re.search(r"#page=(\d+)", url)
    return url.split("#")[0], int(m.group(1)) if m else None


def _pages(base: str, start: int, volume_starts: list[int]) -> str:
    later = sorted(p for p in set(volume_starts) if p > start)
    return f"{base}#pages={start}-{later[0] - 1 if later else ''}"


def works_of(venue: Venue, content: bytes) -> list[IngestedWork]:
    if not venue.record_pattern:
        raise ValueError(f"venue {venue.venue_id}: endnote_v1 needs a record_pattern")
    pattern = re.compile(venue.record_pattern, re.I)
    chosen = []
    for record in records(content):
        year_text = (record.get("D") or [""])[0][:4]
        year = int(year_text) if year_text.isdigit() else None
        if not any(pattern.search(b) for b in record.get("B", [])):
            continue
        if venue.last_year is not None and (year is None or year > venue.last_year):
            continue
        chosen.append((record, year))
    pdfs = Counter(u.split("#")[0] for record, _ in chosen for u in record.get("U", [])[:1])
    starts: dict[str, list[int]] = defaultdict(list)  # volume PDF -> the start pages of its papers
    for record, _ in chosen:
        base, page = _start(record)
        if base and page and pdfs[base] > 1:
            starts[base].append(page)
    works = []
    for record, year in chosen:
        title = " ".join((record.get("T") or [""])[0].split())
        authors = tuple(a for a in (_author(n) for n in record.get("A", [])) if a is not None)
        base, page = _start(record)
        document = base
        if base and pdfs[base] > 1:
            document = _pages(base, page, starts[base]) if page else None
        first_page = re.match(r"\s*(\d+)", (record.get("P") or [""])[0])
        works.append(IngestedWork(
            venue=venue.venue_id, key=_key(year, title, authors), title=title, year=year,
            volume=(record.get("V") or [None])[0], issue=None,
            first_page=first_page.group(1) if first_page else None, authors=authors,
            work_type=venue.work_type((record.get("0") or [""])[0]), document_url=document))
    seen: set[str] = set()
    unique = []
    for work in works:  # the same paper listed twice keeps its first record
        if work.key not in seen:
            seen.add(work.key)
            unique.append(work)
    return unique


def list_works(fetcher: Fetcher, venue: Venue, start: int, end: int) -> list[IngestedWork]:
    export = fetcher.get_document(export_request(venue))
    if export.status != 200 or export.content is None:
        return []
    return works_of(venue, export.content)
