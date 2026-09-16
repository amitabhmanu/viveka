"""Live smoke tests: one small call per source, confirming the response shapes the adapters and fakes assume.

Run only on request (`uv run pytest -m live`), with keys in .env. Cost: one OpenAlex list call ($0.0001).
"""

import pytest
from conftest import REPO

from viveka import env
from viveka.corpus import crossref, openalex, semanticscholar
from viveka.corpus.commands import make_fetcher
from viveka.corpus.config import load_corpus_config
from viveka.corpus.http import Request

pytestmark = pytest.mark.live


@pytest.fixture
def fetcher(tmp_path, monkeypatch):
    env.load(REPO)
    for name in (env.OPENALEX_API_KEY, env.CONTACT_EMAIL):
        if env.get(name) is None:
            pytest.skip(f"{name} is not set")
    config = load_corpus_config(REPO)
    need = ("openalex", "crossref") + (("semanticscholar",) if env.get(env.S2_API_KEY) else ())
    with make_fetcher(tmp_path, config, need=need) as live:  # archive and usage log go to tmp_path
        yield live


def test_openalex_crossref_and_s2_shapes(fetcher):
    listing = fetcher.get(Request.build("openalex", "list", f"{openalex.BASE}/works",
                                        filter="publication_year:1990,has_doi:true,type:article", per_page=1,
                                        cursor="*", select=",".join(openalex.WORK_FIELDS)))
    assert listing.status == 200
    print("openalex meta:", {k: v for k, v in listing.body["meta"].items() if k != "next_cursor"})
    work = listing.body["results"][0]
    assert set(openalex.WORK_FIELDS) <= set(work)
    assert "next_cursor" in listing.body["meta"]  # only present when a cursor is requested, as iter_pages does
    doi = openalex.work_row(work)["doi"]

    record = fetcher.get(crossref.work_request(doi))
    assert record.status == 200 and "reference-count" in record.body["message"]

    if env.get(env.S2_API_KEY):
        citations = fetcher.get(semanticscholar.citations_request(doi, 0, 1))
        assert citations.status in (200, 404)
        if citations.status == 200:
            assert "data" in citations.body
