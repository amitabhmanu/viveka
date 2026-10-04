"""Semantic Scholar adapter: citation contexts and intents for citations to a work.

Checked 15 Sep 2026: the citations endpoint returns ``contexts``, ``intents`` and ``isInfluential``
per citing paper, pages of up to 1000, and refuses offset + limit of 10,000 or more. Coverage of
pre-2000 and paywalled literature is incomplete.
"""

from __future__ import annotations

from viveka.corpus.http import Fetcher, FetchError, Request
from viveka.corpus.ids import normalize_doi

BASE = "https://api.semanticscholar.org/graph/v1"
SOURCE = "semanticscholar"
FIELDS = "contexts,intents,isInfluential,externalIds,title,year"


def citations_request(doi: str, offset: int, limit: int) -> Request:
    return Request.build(SOURCE, "free", f"{BASE}/paper/DOI:{doi}/citations", fields=FIELDS, offset=offset,
                         limit=limit)


def iter_citations(fetcher: Fetcher, doi: str, page_size: int, max_offset: int) -> tuple[list[dict], bool]:
    """Every citation item S2 returns for the DOI, and whether the offset limit cut the list short."""
    items: list[dict] = []
    offset = 0
    while True:
        limit = min(page_size, max_offset - 1 - offset)
        if limit <= 0:
            return items, True
        response = fetcher.get(citations_request(doi, offset, limit))
        if response.status == 404:
            return items, False
        if response.status != 200 or response.body is None:
            raise FetchError(f"semanticscholar citations of {doi}: HTTP {response.status}")
        items.extend(response.body.get("data") or [])
        following = response.body.get("next")
        if following is None:
            return items, False
        offset = int(following)


def context_rows(cited_work: str, item: dict) -> list[dict]:
    citing = item.get("citingPaper") or {}
    external = citing.get("externalIds") or {}
    intents = sorted(str(i) for i in item.get("intents") or [])
    return [
        {"cited_work": cited_work, "citing_doi": normalize_doi(external.get("DOI")),
         "citing_s2_id": citing.get("paperId"), "context_index": index, "text": text, "intents": intents,
         "is_influential": bool(item.get("isInfluential")), "source": SOURCE}
        for index, text in enumerate(item.get("contexts") or [])
    ]
