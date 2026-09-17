"""Offline stand-ins for OpenAlex, Crossref and Semantic Scholar, shaped like their documented responses,
plus a small registered case for stage tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

import httpx
from conftest import write_lf

from viveka.corpus.http import Fetcher, UsageMeter
from viveka.corpus.ids import normalize_doi, short_id

OA = "https://openalex.org/"


def oa_work(wid: str, year: int, doi: str | None = None, refs=(), source: str | None = None,
            authors=(("A1", "Ann Author"),), title: str | None = None, source_name: str | None = None,
            biblio: tuple[str, str] | None = None, work_type: str = "article") -> dict:
    return {
        "id": OA + wid,
        "doi": f"https://doi.org/{doi}" if doi else None,
        "display_name": title or f"Work {wid}",
        "publication_year": year,
        "type": work_type,
        "biblio": {"volume": biblio[0], "first_page": biblio[1]} if biblio else {},
        "primary_location": ({"source": {"id": OA + source, "display_name": source_name or f"Venue {source}"}}
                             if source else None),
        "authorships": [{"author_position": "first" if i == 0 else "middle",
                         "author": {"id": OA + aid, "display_name": name},
                         "institutions": [{"id": OA + "I1"}]} for i, (aid, name) in enumerate(authors)],
        "referenced_works": [OA + r for r in refs],
        "cited_by_count": 3,
    }


@dataclass
class FakeSources:
    works: dict[str, dict] = field(default_factory=dict)
    crossref_refs: dict[str, list] = field(default_factory=dict)  # doi -> per reference: a DOI, None, or a raw entry
    s2_citations: dict[str, list[dict]] = field(default_factory=dict)  # doi -> citation items
    crossref_search: list[tuple[str, list[dict]]] = field(default_factory=list)  # (query substring, items)
    calls: list[httpx.Request] = field(default_factory=list)

    def add(self, *works: dict) -> None:
        for work in works:
            self.works[short_id(work["id"])] = work

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        raw = unquote(request.url.raw_path.decode("ascii").split("?", 1)[0])
        params = dict(request.url.params)
        if request.url.host == "api.openalex.org":
            return self._openalex(raw, params)
        if request.url.host == "api.crossref.org":
            return self._crossref(raw, params)
        if request.url.host == "api.semanticscholar.org":
            return self._s2(raw, params)
        return httpx.Response(404)

    # -- OpenAlex
    def _by_doi(self, doi: str) -> dict | None:
        return next((w for w in self.works.values() if normalize_doi(w["doi"]) == normalize_doi(doi)), None)

    def _openalex(self, path: str, params: dict) -> httpx.Response:
        if path.startswith("/works/doi:"):
            work = self._by_doi(path.removeprefix("/works/doi:"))
            return httpx.Response(200, json=work) if work else httpx.Response(404)
        if path.startswith("/works/"):
            work = self.works.get(path.removeprefix("/works/"))
            return httpx.Response(200, json=work) if work else httpx.Response(404)
        if path == "/sources":
            return httpx.Response(200, json={"meta": {"count": 1}, "results": [
                {"id": OA + "S5", "display_name": "Venue S5", "issn_l": None, "type": "conference",
                 "works_count": 3, "host_organization_name": None}]})
        if path != "/works":
            return httpx.Response(404)
        selected = sorted(self.works.values(), key=lambda w: w["id"])
        if "search" in params:
            selected = [w for w in selected if params["search"].lower() in w["display_name"].lower()]
        for clause in (params.get("filter") or "").split(","):
            if not clause:
                continue
            key, _, value = clause.partition(":")
            values = set(value.split("|"))
            if key == "doi":
                selected = [w for w in selected if normalize_doi(w["doi"]) in {normalize_doi(v) for v in values}]
            elif key == "cites":
                selected = [w for w in selected if values & {short_id(r) for r in w["referenced_works"]}]
            elif key == "primary_location.source.id":
                selected = [w for w in selected
                            if w["primary_location"] and short_id(w["primary_location"]["source"]["id"]) in values]
            elif key in ("biblio.volume", "biblio.first_page"):
                field_name = key.split(".", 1)[1]
                selected = [w for w in selected if w.get("biblio", {}).get(field_name) in values]
            elif key == "publication_year":
                start, end = (int(x) for x in value.split("-"))
                selected = [w for w in selected if start <= w["publication_year"] <= end]
            else:
                return httpx.Response(400)
        per_page = int(params.get("per_page", 25))
        cursor = params.get("cursor", "*")
        offset = 0 if cursor in ("*", None) else int(cursor.removeprefix("c"))
        page = selected[offset : offset + per_page]
        more = offset + per_page < len(selected)
        return httpx.Response(200, json={"meta": {"count": len(selected),
                                                  "next_cursor": f"c{offset + per_page}" if more else None},
                                         "results": page})

    # -- Crossref
    def _crossref(self, path: str, params: dict) -> httpx.Response:
        if path == "/works":
            query = params.get("query.bibliographic", "").lower()
            items = next((items for needle, items in self.crossref_search if needle.lower() in query), [])
            return httpx.Response(200, json={"status": "ok", "message": {"items": items}})
        doi = normalize_doi(path.removeprefix("/works/"))
        if doi in self.crossref_refs:
            refs = [{"key": f"ref{i}", **(d if isinstance(d, dict) else {"DOI": d} if d else
                                          {"unstructured": "An old book"})}
                    for i, d in enumerate(self.crossref_refs[doi])]
            return httpx.Response(200, json={"status": "ok", "message": {"DOI": doi, "reference-count": len(refs),
                                                                         "reference": refs}})
        if self._by_doi(doi):
            return httpx.Response(200, json={"status": "ok", "message": {"DOI": doi, "reference-count": 0}})
        return httpx.Response(404)

    # -- Semantic Scholar
    def _s2(self, path: str, params: dict) -> httpx.Response:
        doi = normalize_doi(path.split("/paper/DOI:", 1)[-1].removesuffix("/citations"))
        items = self.s2_citations.get(doi)
        if items is None:
            return httpx.Response(404)
        offset, limit = int(params.get("offset", 0)), int(params.get("limit", 100))
        if offset + limit >= 10_000:
            return httpx.Response(400)
        body = {"offset": offset, "data": items[offset : offset + limit]}
        if offset + limit < len(items):
            body["next"] = offset + limit
        return httpx.Response(200, json=body)


def fake_fetcher(root: Path, fake: FakeSources, **kwargs) -> Fetcher:
    meter = UsageMeter(root, prices={}, caps={})
    return Fetcher(root, rates={}, meter=meter, terms=lambda s: None, transport=fake.transport(),
                   sleep=lambda s: None, **kwargs)


EVENTS_YAML = """\
format: 1
claim: cold-fusion
wording: "Electrochemically loaded palladium deuteride produces excess heat of nuclear origin."
events:
  - id: null-1990
    date: "1990-03"
    kind: disconfirmation
    works: [{openalex: W2}]
    note: A null replication.
    source: Test fixture.
"""

CASE_YAML = """\
format: 1
case: cold-fusion
claim: cold-fusion
role: pilot
pair: pilot
window: {start: 1989, end: 2000}
seeds:
  - {doi: 10.1/seed, note: founding claim}
frames:
  - {id: citing, kind: mainstream, cites: seeds}
  - {id: venue, kind: community, sources: [S5]}
"""


FIELD_YAML = """\
format: 1
field: test-field
role: calibration
side: pseudoscience
window: {start: 1989, end: 2000}
frames:
  - {id: venues, kind: community, sources: [S5]}
absent_venues:
  - {name: "An unindexed bulletin", issn_l: null, note: "Not an OpenAlex source."}
"""


def write_field(root: Path, text: str = FIELD_YAML) -> None:
    write_lf(root / "registry" / "fields" / "test-field.yaml", text)


def write_case(root: Path, events: str = EVENTS_YAML, case: str = CASE_YAML) -> None:
    write_lf(root / "registry" / "events" / "cold-fusion.yaml", events)
    write_lf(root / "registry" / "cases" / "cold-fusion.yaml", case)


def small_world() -> FakeSources:
    """A seed, a null result, ten citing works over two years, and three works in an unindexed-reference venue."""
    fake = FakeSources()
    fake.add(oa_work("W1", 1989, doi="10.1/seed"), oa_work("W2", 1990, doi="10.1/null", refs=["W1"]))
    for i in range(10):
        year = 1990 + i % 2
        doi = None if i == 9 else f"10.2/c{i}"
        fake.add(oa_work(f"W{10 + i}", year, doi=doi, refs=["W1", "W2"], authors=((f"A{10 + i}", "Author"),)))
    for i in range(3):
        fake.add(oa_work(f"W{30 + i}", 1995, doi=f"10.3/v{i}", source="S5"))
    fake.add(oa_work("W33", 1995, doi="10.3/editorial", source="S5", work_type="editorial"))  # not a paper
    # A DOI-less article that OpenAlex has, findable by volume and page.
    fake.add(oa_work("W3", 1986, doi="10.4/prl", source="S9", source_name="Physical Review Letters",
                     biblio=("56", "3")))
    structured = {"journal-title": "Phys. Rev. Lett.", "volume": "56", "first-page": "3", "year": "1986"}
    # W12 cites the same paper with a wrong first page; only the bibliographic query recovers it.
    miscited = {**structured, "first-page": "4", "article-title": "Reanalysis of the Eotvos experiment"}
    fake.crossref_search.append(("Reanalysis of the Eotvos experiment", [
        {"DOI": "10.4/prl", "score": 62.0, "issued": {"date-parts": [[1986]]}, "volume": "56", "page": "3-6",
         "container-title": ["Physical Review Letters"], "title": ["Reanalysis of the Eotvos experiment"],
         "type": "journal-article"}]))
    for i in range(9):  # every citing work with a DOI: 2 resolvable references, 1 unknown DOI, 1 without DOI
        fake.crossref_refs[f"10.2/c{i}"] = ["10.1/seed", "10.1/null", "10.9/not-indexed",
                                            (miscited if i == 2 else structured) if i % 2 == 0 else None]
    fake.crossref_refs["10.1/null"] = ["10.1/seed"]
    return fake
