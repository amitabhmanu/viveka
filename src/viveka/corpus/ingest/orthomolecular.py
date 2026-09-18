"""Adapter ``orthomolecular_toc_v2``: the Journal of Orthomolecular Medicine archive at orthomolecular.org.

Each year has an index page linking its issues' contents pages; the online archive runs from 1986 to
2009. A contents page groups papers under named anchors (``<a name="articles">``, ``"editorial"``,
``"case"``, ``"center"``, ``"correspondence"``, ``"memoriam"``, ``"books"``, ``"news"``), whose headings'
wording and markup vary over the years; the anchor decides the work type through the registry's
mapping. Each paper is a title, a line of authors, "Page N" and a link to its PDF named
``<year>-v<volume>n<issue>-p<page>.pdf``, from which volume, issue and first page are read. Commented-out
markup is ignored. Authors are read from the author line with degrees removed.
"""

from __future__ import annotations

import re

from viveka.corpus.config import Venue
from viveka.corpus.http import Fetcher, Request
from viveka.corpus.ingest import IngestedWork, document_request
from viveka.corpus.ingest.names import authors_of
from viveka.corpus.ingest.text import html_text

_TOC = re.compile(r'href="((?:[^"]*/)?toc[\w-]*\.shtml)"', re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_ANCHOR = re.compile(r'<a\s+name="(?P<name>[\w-]+)"[^>]*>', re.I)
_PDF = re.compile(r'<a[^>]*href="(?P<href>(?:[^"]*/)?pdf/(?P<stem>(?P<year>\d{4})-v(?P<volume>\d+)n(?P<issue>\d+)'
                  r'-p(?P<page>\d+))\.pdf)"[^>]*>.*?</a>', re.I | re.S)
_PAGE_LINE = re.compile(r"^Page\s*\d+", re.I)



def index_request(venue: Venue, year: int) -> Request:
    return document_request(venue.venue_id, f"{venue.url}/{year}/index.shtml")


def toc_urls(venue: Venue, year: int, page: bytes) -> list[str]:
    found = sorted({m.group(1).rsplit("/", 1)[-1] for m in _TOC.finditer(page.decode("latin-1"))})
    return [f"{venue.url}/{year}/{name}" for name in found]


def parse_toc(venue: Venue, url: str, page: bytes) -> list[IngestedWork]:
    source = _COMMENT.sub(" ", page.decode("latin-1"))
    anchors = [(m.start(), m.end(), m["name"].lower()) for m in _ANCHOR.finditer(source)]
    if not anchors:
        return []
    works: dict[str, IngestedWork] = {}
    previous = anchors[0][0]
    for m in _PDF.finditer(source):
        if m.start() < anchors[0][0]:
            continue
        before = [a for a in anchors if a[0] < m.start()]
        at, _, section = before[-1]
        segment = source[max(previous, at) : m.start()]
        heading = at >= previous  # a section starts in this segment, so its heading is the first line
        previous = m.end()
        lines = [line.strip() for line in html_text(segment.encode("latin-1"), "latin-1").splitlines()
                 if line.strip()]
        if heading and lines:
            lines = lines[1:]
        page_at = next((i for i, line in enumerate(lines) if _PAGE_LINE.match(line)), len(lines))
        head = lines[:page_at]
        author_line = head[-1] if len(head) >= 2 else ""
        title = " ".join(head[:-1] if len(head) >= 2 else head)
        works.setdefault(m["stem"], IngestedWork(
            venue=venue.venue_id, key=m["stem"], title=title, year=int(m["year"]),
            volume=str(int(m["volume"])), issue=str(int(m["issue"])), first_page=str(int(m["page"])),
            authors=authors_of(author_line), work_type=venue.types.get(section, venue.default_type),
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
