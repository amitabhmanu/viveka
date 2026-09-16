from corpus_fakes import FakeSources, fake_fetcher, oa_work

from viveka.census import Reference
from viveka.corpus import crossref, openalex, semanticscholar
from viveka.corpus.ids import chunks, normalize_doi, short_id


def test_identifiers():
    assert short_id("https://openalex.org/W123") == "W123" and short_id("S5") == "S5" and short_id(None) is None
    for raw in ("https://doi.org/10.1/ABC", "doi:10.1/abc", " 10.1/Abc ", "http://dx.doi.org/10.1/abc"):
        assert normalize_doi(raw) == "10.1/abc"
    assert normalize_doi("") is None and chunks([1, 2, 3], 2) == [[1, 2], [3]]


def test_frame_filters_split_long_or_lists():
    seeds = [f"W{i}" for i in range(60)]
    filters = openalex.frame_filters(True, seeds, 1989, 2025)
    assert len(filters) == 2 and all(f.startswith("cites:") and f.endswith(",publication_year:1989-2025")
                                     for f in filters)
    assert openalex.frame_filters(False, ["S2", "S1"], 1990, 1991) == [
        "primary_location.source.id:S1|S2,publication_year:1990-1991"]


def test_cursor_paging_collects_every_result(tmp_path):
    fake = FakeSources()
    fake.add(oa_work("W1", 1989), *(oa_work(f"W{10 + i}", 1990, refs=["W1"]) for i in range(5)))
    with fake_fetcher(tmp_path, fake) as fetcher:
        pages = list(openalex.iter_pages(fetcher, "cites:W1,publication_year:1989-2000", 2))
    assert len(pages) == 3 and sum(len(p.body["results"]) for p in pages) == 5


def test_doi_lookup_batches_and_reports_only_found(tmp_path):
    fake = FakeSources()
    fake.add(*(oa_work(f"W{i}", 2000, doi=f"10.5/{i}") for i in range(120)), oa_work("W999", 2000, doi="10.5/a,b"))
    wanted = [f"https://doi.org/10.5/{i}" for i in range(120)] + ["10.5/missing", "10.5/a,b", None]
    with fake_fetcher(tmp_path, fake) as fetcher:
        found = openalex.lookup_dois(fetcher, wanted, 50, fields=openalex.ID_FIELDS)
    assert len(found) == 121 and "10.5/missing" not in found and "10.5/a,b" in found
    kinds = [c.url.path for c in fake.calls]
    assert kinds.count("/works") == 3 and sum(p.startswith("/works/doi:") for p in kinds) == 1


def test_rows_from_a_work():
    work = oa_work("W7", 1991, doi="10.1/X", refs=["W2", "W1", "W2"], source="S5",
                   authors=(("A1", "Ann"), ("A2", "Bo")))
    row = openalex.work_row(work)
    assert row == {"work_id": "W7", "doi": "10.1/x", "title": "Work W7", "year": 1991, "venue_id": "S5",
                   "venue_name": "Venue S5", "type": "article", "cited_by_count": 3, "source": "openalex"}
    assert [r["author_id"] for r in openalex.author_rows(work)] == ["A1", "A2"]
    assert openalex.authorship_rows(work)[1] == {"work_id": "W7", "author_id": "A2", "position": "middle",
                                                 "institution_ids": ["I1"]}
    assert [r["citation_id"] for r in openalex.citation_rows(work)] == ["W7:W1", "W7:W2"]


def test_crossref_reference_lists():
    assert crossref.references_of({"message": {"reference-count": 0}}) is None
    assert crossref.references_of(None) is None
    refs = crossref.references_of({"message": {"reference": [
        {"DOI": "10.1/A"}, {"unstructured": "book"},
        {"journal-title": "Phys. Rev. Lett.", "volume": "56", "first-page": "3", "year": "1986b"}]}})
    assert refs.dois == ("10.1/a", None, None) and refs.total == 3 and refs.source == "crossref"
    assert refs.entries[1] == Reference(None, text="book")
    assert refs.entries[2] == Reference(None, 1986, "56", "3", "Phys. Rev. Lett.")
    assert crossref.work_request("10.1/a(b)").url.endswith("/works/10.1%2Fa%28b%29")
    request = openalex.biblio_request(1986, "56", "3", 1)
    assert dict(request.params)["filter"] == "publication_year:1985-1987,biblio.volume:56,biblio.first_page:3"
    assert request.kind == "list"


def test_semantic_scholar_paging_and_offset_limit(tmp_path):
    items = [{"contexts": [f"see [{i}]"], "intents": ["background"], "isInfluential": i == 0,
              "citingPaper": {"paperId": f"p{i}", "externalIds": {"DOI": f"10.8/{i}"}}} for i in range(2500)]
    fake = FakeSources(s2_citations={"10.1/seed": items})
    with fake_fetcher(tmp_path, fake) as fetcher:
        found, cut = semanticscholar.iter_citations(fetcher, "10.1/seed", 1000, 10_000)
        partial, truncated = semanticscholar.iter_citations(fetcher, "10.1/seed", 1000, 1500)
        none, _ = semanticscholar.iter_citations(fetcher, "10.1/other", 1000, 10_000)
    assert len(found) == 2500 and not cut
    assert len(partial) == 1499 and truncated
    assert none == []
    rows = semanticscholar.context_rows("W1", items[0])
    assert rows == [{"cited_work": "W1", "citing_doi": "10.8/0", "citing_s2_id": "p0", "context_index": 0,
                     "text": "see [0]", "intents": ["background"], "is_influential": True,
                     "source": "semanticscholar"}]
