import datetime as dt
import json

import httpx
import pytest

from viveka.corpus.http import Fetcher, FetchError, NotArchived, Request, SpendCapExceeded, UsageMeter

DAY = dt.date(2026, 9, 15)


def make(tmp_path, handler, *, cap=1.0, offline=False, sleeps=None, day=DAY):
    meter = UsageMeter(tmp_path, prices={"openalex": {"list": 0.0001, "singleton": 0.0}}, caps={"openalex": cap},
                       today=lambda: day)
    return Fetcher(tmp_path, rates={"openalex": 5}, meter=meter, terms=lambda s: f"terms:{s}",
                   secrets={"openalex": {"params": {"api_key": "SECRET"}}}, transport=httpx.MockTransport(handler),
                   offline=offline, sleep=sleeps.append if sleeps is not None else (lambda s: None),
                   clock=lambda: 0.0)


def listing(value):
    return Request.build("openalex", "list", "https://api.openalex.org/works", filter=value)


def ok(request):
    return httpx.Response(200, json={"results": [], "meta": {"count": 0}})


def test_archive_replays_and_keeps_secrets_out(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        return ok(request)

    with make(tmp_path, handler) as fetcher:
        first, second = fetcher.get(listing("x:1")), fetcher.get(listing("x:1"))
    assert first.live and not second.live and len(seen) == 1
    assert seen[0].url.params["api_key"] == "SECRET"
    files = list((tmp_path / "data" / "raw" / "openalex").rglob("*.json"))
    assert len(files) == 2 and all("SECRET" not in p.read_text(encoding="utf-8") for p in files)
    meta = json.loads(next(p for p in files if p.name.endswith(".meta.json")).read_text(encoding="utf-8"))
    assert meta["terms_reference"] == "terms:openalex" and meta["params"] == {"filter": "x:1"}
    assert meta["sha256"].startswith("sha256:") and meta["retrieved_at"]
    assert fetcher.usage.as_manifest() == {"live_calls": {"openalex": {"list": 1}}, "replayed": {"openalex": 1},
                                           "usd": {"openalex": 0.0001}}


def test_request_key_ignores_parameter_order():
    a = Request.build("openalex", "list", "u", filter="x", per_page=5)
    b = Request("openalex", "list", "u", (("per_page", "5"), ("filter", "x")))
    assert a.key() == Request("openalex", "list", "u", tuple(sorted(b.params))).key()
    assert a.key() != listing("x").key()


def test_cap_refuses_the_call_that_would_cross_it_across_processes_and_resets_daily(tmp_path):
    with make(tmp_path, ok, cap=0.00025) as fetcher:
        fetcher.get(listing("a"))
        fetcher.get(listing("b"))
        with pytest.raises(SpendCapExceeded, match="cap"):
            fetcher.get(listing("c"))
    with make(tmp_path, ok, cap=0.00025) as again:  # a new process reads today's usage log
        with pytest.raises(SpendCapExceeded):
            again.get(listing("d"))
        again.get(Request.build("openalex", "singleton", "https://api.openalex.org/works/W1"))  # free calls go on
        again.get(listing("a"))  # archived: replayed, not charged
    with make(tmp_path, ok, cap=0.00025, day=DAY + dt.timedelta(days=1)) as tomorrow:
        assert tomorrow.get(listing("e")).live


def test_retries_transient_errors_and_archives_not_found(tmp_path):
    queue = [httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(503)]
    sleeps = []

    def handler(request):
        if request.url.path.endswith("/W404"):
            return httpx.Response(404)
        return queue.pop(0) if queue else ok(request)

    with make(tmp_path, handler, sleeps=sleeps) as fetcher:
        assert fetcher.get(listing("x")).status == 200
        missing = Request.build("openalex", "singleton", "https://api.openalex.org/works/W404")
        assert fetcher.get(missing).status == 404
        assert not fetcher.get(missing).live
    assert 3.0 in sleeps and 2.0 in sleeps
    assert fetcher.usage.live_calls["openalex"] == {"list": 3, "singleton": 1}  # every attempt is charged


def test_hard_errors_raise_without_leaking_the_key(tmp_path):
    with make(tmp_path, lambda r: httpx.Response(401)) as fetcher, pytest.raises(FetchError) as info:
        fetcher.get(listing("x"))
    assert "HTTP 401" in str(info.value) and "SECRET" not in str(info.value)


def test_offline_fetcher_never_calls_out(tmp_path):
    def handler(request):
        raise AssertionError("network used")

    with make(tmp_path, handler, offline=True) as fetcher, pytest.raises(NotArchived):
        fetcher.get(listing("x"))
    assert not (tmp_path / "data" / "usage").exists()


def test_rate_limit_spaces_calls(tmp_path):
    sleeps = []
    with make(tmp_path, ok, sleeps=sleeps) as fetcher:
        fetcher.get(listing("a"))
        fetcher.get(listing("b"))
    assert sleeps == [pytest.approx(0.2)]
