"""Adapter ``ojs_v1``: journals on Open Journal Systems (OJS 3 default theme and OJS 2 classic contents pages).

The issue archive (``<url>/issue/archive``, then ``/issue/archive/2``, ... until a page adds no issue)
lists the issues; an issue page's heading gives its volume, number and year ("Vol. 1 No. 1 (1990)";
"Vol 2010" when the volume is the year). Its contents group articles under section headings, and
each article gives a title, an author line, sometimes pages, and a PDF galley whose view link
(``article/view/<id>/<galley>``) becomes a download link (``article/download/<id>/<galley>``). The
section decides the work type through the registry's names and patterns; an article without a PDF
galley has no document, so it is unmeasured if sampled.
"""

from __future__ import annotations

import html
import re

from viveka.corpus.config import Venue
from viveka.corpus.http import Fetcher, Request
from viveka.corpus.ingest import IngestedWork, document_request
from viveka.corpus.ingest.names import authors_of

_ISSUE = re.compile(r'href="(?P<url>[^"]*/issue/view/(?P<id>\d+))(?:/[^"]*)?"')
# Section headings (OJS 3: <h2> in the contents; OJS 2: <h4 class="tocSectionTitle">) and article starts
# (OJS 3: <div class="obj_article_summary">; OJS 2: <table class="tocArticle">). An article's block ends where
# the next heading or article begins.
_TOKEN = re.compile(r'<h2[^>]*>(?P<s3>.*?)</h2>|<h4 class="tocSectionTitle">(?P<s2>.*?)</h4>|'
                    r'(?P<article><div class="obj_article_summary">|<table class="tocArticle")', re.S | re.I)
_ARTICLE = re.compile(r'href="(?P<url>[^"]*/article/view/(?P<id>[^/"]+))"[^>]*>(?P<title>.*?)</a>', re.S)
_GALLEY = re.compile(r'href="(?P<url>[^"]*/article/view/[^/"]+/[^/"]+)"[^>]*>\s*PDF', re.S | re.I)
_AUTHORS = re.compile(r'class="(?:authors|tocAuthors)"[^>]*>(?P<text>.*?)</(?:div|td)>', re.S)
_PAGES = re.compile(r'class="(?:pages|tocPages)"[^>]*>\s*(?P<first>\d+)', re.S)
_VOLUME = re.compile(r"Vol\.?\s*(?P<volume>\d+)(?:\s*No\.?\s*(?P<issue>[\w-]+))?", re.I)
_YEAR = re.compile(r"\((?P<year>(?:18|19|20)\d{2})\)|Vol\.?\s*(?P<vyear>(?:18|19|20)\d{2})\b", re.I)


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def archive_request(venue: Venue, page: int) -> Request:
    suffix = "" if page == 1 else f"/{page}"
    return document_request(venue.venue_id, f"{venue.url}/issue/archive{suffix}")


def issue_urls(page: bytes) -> list[str]:
    seen: dict[str, str] = {}
    for m in _ISSUE.finditer(page.decode("utf-8", errors="replace")):
        seen.setdefault(m["id"], m["url"])
    return list(seen.values())


def parse_issue(venue: Venue, page: bytes) -> list[IngestedWork]:
    source = page.decode("utf-8", errors="replace")
    title = re.search(r"<title>(.*?)</title>", source, re.S)
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", source, re.S)
    label = " ".join(_text(m.group(1)) for m in (h1, title) if m)
    volume = _VOLUME.search(label)
    year = _YEAR.search(label)
    year_value = int(year["year"] or year["vyear"]) if year else None
    tokens = list(_TOKEN.finditer(source))
    works, section = [], None
    for i, m in enumerate(tokens):
        if m["article"] is None:
            section = _text(m["s3"] if m["s3"] is not None else m["s2"])
            continue
        block = source[m.end() : tokens[i + 1].start() if i + 1 < len(tokens) else len(source)]
        article = _ARTICLE.search(block)
        if not article:
            continue
        galley = _GALLEY.search(block)
        authors = _AUTHORS.search(block)
        pages = _PAGES.search(block)
        works.append(IngestedWork(
            venue=venue.venue_id, key=article["id"], title=_text(article["title"]), year=year_value,
            volume=volume["volume"] if volume else None, issue=volume["issue"] if volume else None,
            first_page=str(int(pages["first"])) if pages else None,
            authors=authors_of(_text(authors["text"])) if authors else (),
            work_type=venue.work_type(section),
            document_url=galley["url"].replace("/article/view/", "/article/download/") if galley else None))
    return works


def list_works(fetcher: Fetcher, venue: Venue, start: int, end: int) -> list[IngestedWork]:
    issues: list[str] = []
    page_number = 1
    while True:
        page = fetcher.get_document(archive_request(venue, page_number))
        if page.status != 200 or page.content is None:
            break
        new = [u for u in issue_urls(page.content) if u not in issues]
        if not new:
            break
        issues += new
        page_number += 1
    works: dict[str, IngestedWork] = {}
    for url in issues:
        page = fetcher.get_document(document_request(venue.venue_id, url))
        if page.status == 200 and page.content is not None:
            for work in parse_issue(venue, page.content):
                works.setdefault(work.key, work)
    return list(works.values())
