"""Adapter ``orthomolecular_toc_v1``: the Journal of Orthomolecular Medicine archive at orthomolecular.org.

Each year has an index page linking its issues' contents pages. A contents page groups papers under
bold section headings ("Articles:", "Case Reports:", "Correspondence:", ...); each paper is an italic
title, a line of authors, "Page N" and a link to its PDF named ``<year>-v<volume>n<issue>-p<page>.pdf``.
The section decides the work type through the registry's mapping; authors are read from the author
line with degrees removed.
"""

from __future__ import annotations

import html
import re

from viveka.corpus.config import Venue
from viveka.corpus.http import Fetcher, Request
from viveka.corpus.ingest import Author, IngestedWork, document_request

_TOC = re.compile(r'href="((?:[^"]*/)?toc[\w-]*\.shtml)"', re.I)
_SECTION = re.compile(r"<b>\s*(?P<section>[^<:]{2,60}?)\s*:\s*(?:</a>\s*)?(?:</font>\s*)?</b>", re.I)
_ENTRY = re.compile(
    r"<i>(?P<title>(?:(?!<i>).)*?)</i>\s*<br>(?P<authors>(?:(?!<i>).)*?)<br>\s*Page\s*(?P<page>\d+)"
    r"(?:(?!<i>).)*?href=\"(?P<href>(?:[^\"]*/)?pdf/(?P<stem>(?P<year>\d{4})-v(?P<volume>\d+)n(?P<issue>\d+)"
    r"-p\d+)\.pdf)\"", re.I | re.S)
_ET_AL = re.compile(r"\bet\.?\s*al\.?", re.I)


def index_request(venue: Venue, year: int) -> Request:
    return document_request(venue.venue_id, f"{venue.url}/{year}/index.shtml")


def toc_urls(venue: Venue, year: int, page: bytes) -> list[str]:
    found = sorted({m.group(1).rsplit("/", 1)[-1] for m in _TOC.finditer(page.decode("latin-1"))})
    return [f"{venue.url}/{year}/{name}" for name in found]


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _is_name(part: str) -> bool:
    words = part.split()
    if len(words) < 2:
        return False
    for w in words:
        if re.fullmatch(r"(?:[A-Z]\.)+", w):
            continue  # initials
        if w.endswith(".") or "(" in w or not re.search(r"[a-z]{2,}", w) or not w[0].isupper():
            return False
    return True


def authors_of(line: str) -> tuple[Author, ...]:
    """Names from an author line such as "Mike Marlowe, Ph.D., Joan Goulding, M.A.S.C.H. and A. Hoffer"."""
    line = re.sub(r"\d+", "", _ET_AL.sub("", line))
    authors = []
    for part in (" ".join(p.split()) for p in re.split(r",|;|\band\b|&", line)):
        words = part.split()
        while len(words) > 2 and re.fullmatch(r"(?:[A-Z][a-z]?\.)+", words[-1]):
            words.pop()  # a degree written without a comma ("Hoes M.D.")
        if _is_name(" ".join(words)) and not re.fullmatch(r"(?:[A-Z]\.)+", words[-1]):
            *given, family = words
            authors.append(Author(family, " ".join(given) or None))
    return tuple(authors)


def parse_toc(venue: Venue, url: str, page: bytes) -> list[IngestedWork]:
    source = page.decode("latin-1")
    sections = [(m.start(), _text(m["section"])) for m in _SECTION.finditer(source)]
    works: dict[str, IngestedWork] = {}
    for m in _ENTRY.finditer(source):
        section = next((name for at, name in reversed(sections) if at < m.start()), "")
        works.setdefault(m["stem"], IngestedWork(
            venue=venue.venue_id, key=m["stem"], title=_text(m["title"]), year=int(m["year"]),
            volume=str(int(m["volume"])), issue=str(int(m["issue"])), first_page=str(int(m["page"])),
            authors=authors_of(_text(m["authors"])), work_type=venue.types.get(section, venue.default_type),
            document_url=f"{url.rsplit('/', 1)[0]}/{m['href']}"))
    return list(works.values())


def list_works(fetcher: Fetcher, venue: Venue, start: int, end: int) -> list[IngestedWork]:
    works = []
    for year in range(start, end + 1):
        index = fetcher.get_document(index_request(venue, year))
        if index.status != 200 or index.content is None:
            continue
        for url in toc_urls(venue, year, index.content):
            toc = fetcher.get_document(document_request(venue.venue_id, url))
            if toc.status == 200 and toc.content is not None:
                works += parse_toc(venue, url, toc.content)
    return works
