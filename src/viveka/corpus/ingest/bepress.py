"""Adapter ``bepress_v1``: journals on bepress Digital Commons (the Indian Journal of Research in Homoeopathy).

``<url>/all_issues.html`` links every issue (``<url>/vol<V>/iss<I>/``); an issue page's heading gives
"Volume V, Issue I (YEAR)", and its contents group articles under section headings (``<h2>``). Each
article is a ``div.doc`` with a PDF link (``cgi/viewcontent.cgi?...``), a link to its page
(``<url>/vol<V>/iss<I>/<n>``) and an author line. The section decides the work type through the
registry's names and patterns.
"""

from __future__ import annotations

import html
import re

from viveka.corpus.config import Venue
from viveka.corpus.http import Fetcher, Request
from viveka.corpus.ingest import IngestedWork, document_request
from viveka.corpus.ingest.names import authors_of

_ISSUE = re.compile(r'href="(?P<url>[^"]*/vol(?P<volume>\d+)/iss(?P<issue>\d+)/?)"')
_HEADING = re.compile(r"Volume\s*(?P<volume>\d+),\s*Issue\s*(?P<issue>\d+)\s*\((?P<year>\d{4})\)", re.I)
_TOKEN = re.compile(r'<h2[^>]*>(?P<section>.*?)</h2>|(?P<doc><div class="doc">)', re.S | re.I)
_PDF = re.compile(r'href="(?P<url>[^"]*viewcontent\.cgi\?[^"]+)"')
_ARTICLE = re.compile(r'href="(?P<url>[^"]*/vol\d+/iss\d+/(?P<n>\d+))/?"[^>]*>(?P<title>.*?)</a>', re.S)
_AUTHORS = re.compile(r'<span class="auth">(?P<text>.*?)</span>', re.S)


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def issues_request(venue: Venue) -> Request:
    return document_request(venue.venue_id, f"{venue.url}/all_issues.html")


def issue_urls(venue: Venue, page: bytes) -> list[str]:
    found: dict[tuple[int, int], str] = {}
    for m in _ISSUE.finditer(page.decode("utf-8", errors="replace")):
        found.setdefault((int(m["volume"]), int(m["issue"])), f"{venue.url}/vol{m['volume']}/iss{m['issue']}/")
    return [found[k] for k in sorted(found)]


def parse_issue(venue: Venue, page: bytes) -> list[IngestedWork]:
    source = page.decode("utf-8", errors="replace")
    heading = _HEADING.search(_text(source))
    tokens = list(_TOKEN.finditer(source))
    works, section = [], None
    for i, m in enumerate(tokens):
        if m["doc"] is None:
            section = _text(m["section"])
            continue
        block = source[m.end() : tokens[i + 1].start() if i + 1 < len(tokens) else len(source)]
        article = _ARTICLE.search(block)
        if not article or not heading:
            continue
        pdf = _PDF.search(block)
        authors = _AUTHORS.search(block)
        works.append(IngestedWork(
            venue=venue.venue_id, key=f"v{heading['volume']}-i{heading['issue']}-{article['n']}",
            title=_text(article["title"]), year=int(heading["year"]), volume=heading["volume"],
            issue=heading["issue"], first_page=None, authors=authors_of(_text(authors["text"])) if authors else (),
            work_type=venue.work_type(section), document_url=html.unescape(pdf["url"]) if pdf else None))
    return works


def list_works(fetcher: Fetcher, venue: Venue, start: int, end: int) -> list[IngestedWork]:
    index = fetcher.get_document(issues_request(venue))
    if index.status != 200 or index.content is None:
        return []
    works = []
    for url in issue_urls(venue, index.content):
        page = fetcher.get_document(document_request(venue.venue_id, url))
        if page.status == 200 and page.content is not None:
            works += parse_issue(venue, page.content)
    return works
