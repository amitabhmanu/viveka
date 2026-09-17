"""Adapter ``arj_volumes_v1``: Answers Research Journal volumes at answersresearchjournal.org.

A volume page lists its papers as cards: a link to the paper's page, its title, "pp. a–b" and its
contributors. Volume n is the year ``first_volume_year + n - 1``. The paper page, fetched only when
the census samples it, holds the reference list as one paragraph per reference.
"""

from __future__ import annotations

import html
import re

from viveka.corpus.config import Venue
from viveka.corpus.http import Fetcher, Request
from viveka.corpus.ingest import Author, IngestedWork, document_request

_CARD = re.compile(r'<article class="paper-card">(.*?)</article>', re.S)
_TITLE = re.compile(r'<h4>\s*<a href="(?P<href>/[^"]+)"[^>]*>(?P<title>.*?)</a>', re.S)
_PAGES = re.compile(r"pp\.\s*(\d+)")
_CONTRIB = re.compile(r'<span class="contribName">(.*?)</span>', re.S)
_ET_AL = re.compile(r",?\s*et\.?\s*al\.?", re.I)


def volume_request(venue: Venue, number: int) -> Request:
    return document_request(venue.venue_id, f"{venue.url}/volumes/v{number}/")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_volume(venue: Venue, number: int, page: bytes) -> list[IngestedWork]:
    year = (venue.first_volume_year or 0) + number - 1
    works = []
    for card in _CARD.findall(page.decode("utf-8", errors="replace")):
        title = _TITLE.search(card)
        if not title:
            continue
        pages = _PAGES.search(card)
        authors = []
        for contrib in _CONTRIB.findall(card):
            for name in re.split(r",|\band\b|&", _ET_AL.sub("", _text(contrib))):
                if name.strip():
                    *given, family = name.split()
                    authors.append(Author(family, " ".join(given) or None))
        works.append(IngestedWork(
            venue=venue.venue_id, key=title["href"].strip("/"), title=_text(title["title"]), year=year,
            volume=str(number), issue=None, first_page=pages.group(1) if pages else None, authors=tuple(authors),
            work_type=venue.default_type, document_url=f"{venue.url}{title['href']}"))
    return works


def list_works(fetcher: Fetcher, venue: Venue, start: int, end: int) -> list[IngestedWork]:
    if venue.first_volume_year is None:
        raise ValueError(f"venue {venue.venue_id}: arj_volumes_v1 needs first_volume_year")
    works = []
    for number in range(max(1, start - venue.first_volume_year + 1), end - venue.first_volume_year + 2):
        page = fetcher.get_document(volume_request(venue, number))
        if page.status == 200 and page.content is not None:
            works += parse_volume(venue, number, page.content)
    return works
