"""OpenAlex adapter: work lookups, filtered lists with cursor paging, and row normalisation.

Prices (checked 15 Sep 2026): a single-work lookup is free, a list or filter call costs $0.0001,
a search $0.001. ``referenced_works`` holds only references OpenAlex matched to its own works,
which is why the census takes reference lists from Crossref instead.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from viveka.corpus.http import Fetcher, FetchError, Request, Response
from viveka.corpus.ids import chunks, normalize_doi, short_id

BASE = "https://api.openalex.org"
SOURCE = "openalex"
OR_LIMIT = 50  # values per OR filter
WORK_FIELDS = ("id", "doi", "display_name", "publication_year", "type", "primary_location", "authorships",
               "referenced_works", "cited_by_count")
ID_FIELDS = ("id", "doi")


def _select(fields: Sequence[str]) -> str:
    return ",".join(fields)


def work_request(openalex_id: str, fields: Sequence[str] = WORK_FIELDS) -> Request:
    return Request.build(SOURCE, "singleton", f"{BASE}/works/{openalex_id}", select=_select(fields))


def doi_request(doi: str, fields: Sequence[str] = WORK_FIELDS) -> Request:
    return Request.build(SOURCE, "singleton", f"{BASE}/works/doi:{doi}", select=_select(fields))


def doi_batch_request(dois: Sequence[str], fields: Sequence[str] = WORK_FIELDS) -> Request:
    return Request.build(SOURCE, "list", f"{BASE}/works", filter="doi:" + "|".join(dois), per_page=200,
                         select=_select(fields))


def list_request(filter_value: str, cursor: str, per_page: int, fields: Sequence[str] = WORK_FIELDS) -> Request:
    return Request.build(SOURCE, "list", f"{BASE}/works", filter=filter_value, cursor=cursor, per_page=per_page,
                         select=_select(fields))


def biblio_request(year: int, volume: str, first_page: str, year_tolerance: int) -> Request:
    """Works at a year (± tolerance), volume and first page: the census's match for a DOI-less reference.

    Volume and page are single tokens (see ``census.biblio_of``), so they cannot break the filter syntax.
    """
    flt = (f"publication_year:{year - year_tolerance}-{year + year_tolerance},"
           f"biblio.volume:{volume},biblio.first_page:{first_page}")
    return Request.build(SOURCE, "list", f"{BASE}/works", filter=flt, per_page=25, select="id,primary_location")


def source_name(obj: dict) -> str | None:
    return (((obj.get("primary_location") or {}).get("source")) or {}).get("display_name")


def title_search_request(title: str) -> Request:
    return Request.build(SOURCE, "search", f"{BASE}/works", search=title, per_page=5, select=_select(WORK_FIELDS))


def source_search_request(name: str) -> Request:
    return Request.build(SOURCE, "search", f"{BASE}/sources", search=name, per_page=5,
                         select="id,display_name,issn_l,type,works_count,host_organization_name")


def frame_filters(cites_seeds: bool, values: Sequence[str], start: int, end: int) -> list[str]:
    """OpenAlex filters for a frame: works citing the seeds, or published in the given sources, within the window."""
    field = "cites" if cites_seeds else "primary_location.source.id"
    return [f"{field}:{'|'.join(chunk)},publication_year:{start}-{end}" for chunk in chunks(sorted(values), OR_LIMIT)]


def iter_pages(fetcher: Fetcher, filter_value: str, per_page: int) -> Iterator[Response]:
    cursor: str | None = "*"
    while cursor:
        response = fetcher.get(list_request(filter_value, cursor, per_page))
        if response.status != 200 or response.body is None:
            raise FetchError(f"openalex list {filter_value!r}: HTTP {response.status}")
        yield response
        results = response.body.get("results") or []
        cursor = (response.body.get("meta") or {}).get("next_cursor") if results else None


def _batchable(doi: str) -> bool:
    return "|" not in doi and "," not in doi


def lookup_dois(fetcher: Fetcher, dois: Sequence[str | None], batch: int,
                fields: Sequence[str] = WORK_FIELDS) -> dict[str, dict]:
    """The OpenAlex work for each DOI that OpenAlex has; DOIs it lacks are absent from the result."""
    wanted = sorted({d for d in (normalize_doi(x) for x in dois) if d})
    found: dict[str, dict] = {}
    for chunk in chunks([d for d in wanted if _batchable(d)], batch):
        response = fetcher.get(doi_batch_request(chunk, fields))
        if response.status != 200 or response.body is None:
            raise FetchError(f"openalex DOI lookup: HTTP {response.status}")
        for obj in response.body.get("results") or []:
            doi = normalize_doi(obj.get("doi"))
            if doi:
                found.setdefault(doi, obj)
    for doi in (d for d in wanted if not _batchable(d)):
        response = fetcher.get(doi_request(doi, fields))
        if response.status == 200 and response.body is not None:
            found[doi] = response.body
    return found


# ---------------------------------------------------------------- rows


def work_row(obj: dict) -> dict:
    source = ((obj.get("primary_location") or {}).get("source")) or {}
    return {
        "work_id": short_id(obj.get("id")),
        "doi": normalize_doi(obj.get("doi")),
        "title": obj.get("display_name"),
        "year": obj.get("publication_year"),
        "venue_id": short_id(source.get("id")),
        "venue_name": source.get("display_name"),
        "type": obj.get("type"),
        "cited_by_count": obj.get("cited_by_count"),
        "source": SOURCE,
    }


def author_rows(obj: dict) -> list[dict]:
    rows = []
    for authorship in obj.get("authorships") or []:
        author = authorship.get("author") or {}
        if author.get("id"):
            rows.append({"author_id": short_id(author["id"]), "display_name": author.get("display_name"),
                         "disambiguation_source": SOURCE, "confidence": None})
    return rows


def authorship_rows(obj: dict) -> list[dict]:
    work_id = short_id(obj.get("id"))
    rows = []
    for authorship in obj.get("authorships") or []:
        author = authorship.get("author") or {}
        if author.get("id"):
            institutions = sorted(short_id(i["id"]) for i in authorship.get("institutions") or [] if i.get("id"))
            rows.append({"work_id": work_id, "author_id": short_id(author["id"]),
                         "position": authorship.get("author_position"), "institution_ids": institutions})
    return rows


def citation_rows(obj: dict) -> list[dict]:
    citing = short_id(obj.get("id"))
    cited = sorted({short_id(r) for r in obj.get("referenced_works") or [] if r})
    return [{"citation_id": f"{citing}:{c}", "citing_work": citing, "cited_work": c} for c in cited]
