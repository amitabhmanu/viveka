"""Adapter ``eprints_json_v1``: an EPrints repository's per-year JSON export (the CRSQ archive).

Each record gives title, creators, date, volume, number, item type and the article's PDF. The
repository lists what the society deposited: its departments (letters, notes) are absent, so the
frame is the repository's research articles, and its item types map to work types in the registry.
"""

from __future__ import annotations

import json
import re

from viveka.corpus.config import Venue
from viveka.corpus.http import Fetcher
from viveka.corpus.ingest import Author, IngestedWork, document_request


def year_request(venue: Venue, year: int):
    return document_request(venue.venue_id, f"{venue.url}/cgi/exportview/year/{year}/JSON/{year}.js")


def work_of(venue: Venue, item: dict) -> IngestedWork | None:
    publication = item.get("publication")
    if publication and publication not in venue.aliases:
        return None
    date = str(item.get("date") or "")
    creators = tuple(Author(str(c["name"]["family"]).strip(), (c["name"].get("given") or None))
                     for c in item.get("creators") or [] if (c.get("name") or {}).get("family"))
    first_page = re.match(r"\s*(\d+)", str(item.get("pagerange") or ""))
    document = next((f.get("uri") for d in item.get("documents") or [] if d.get("format") == "application/pdf"
                     for f in d.get("files") or [] if f.get("uri")), None)
    return IngestedWork(
        venue=venue.venue_id, key=str(item["eprintid"]), title=" ".join(str(item.get("title") or "").split()),
        year=int(date[:4]) if date[:4].isdigit() else None,
        volume=str(item["volume"]) if item.get("volume") is not None else None,
        issue=str(item["number"]) if item.get("number") is not None else None,
        first_page=first_page.group(1) if first_page else None, authors=creators,
        work_type=venue.types.get(str(item.get("type")), venue.default_type), document_url=document)


def list_works(fetcher: Fetcher, venue: Venue, start: int, end: int) -> list[IngestedWork]:
    works = []
    for year in range(start, end + 1):
        page = fetcher.get_document(year_request(venue, year))
        if page.status != 200 or page.content is None:
            continue
        for item in json.loads(page.content.decode("utf-8")):
            work = work_of(venue, item)
            if work is not None:
                works.append(work)
    return works
