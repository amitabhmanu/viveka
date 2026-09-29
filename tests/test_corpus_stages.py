import json

import httpx
import pytest
from conftest import write_lf
from corpus_fakes import FIELD_YAML, small_world, write_case, write_field
from pdf_fixture import text_pdf

from viveka import cli
from viveka.cases import CaseError
from viveka.corpus import commands, tables
from viveka.corpus.audit import AuditError, write_once
from viveka.provenance import ProvenanceError, load_manifest, verify_run
from viveka.registry.errors import RegistryError


@pytest.fixture
def world(registry_root, monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "OA-SECRET")
    monkeypatch.setenv("VIVEKA_CONTACT_EMAIL", "test@example.invalid")
    monkeypatch.setenv("S2_API_KEY", "S2-SECRET")
    monkeypatch.setattr("viveka.corpus.http.time.sleep", lambda s: None)
    write_case(registry_root)
    return registry_root, small_world()


def no_network():
    def handler(request):
        raise AssertionError(f"unexpected network call to {request.url.host}")

    return httpx.MockTransport(handler)


def run_cli(root, *argv, transport=None):
    lines = []
    args = cli._parser().parse_args([*argv, "--root", str(root)])
    if args.command in ("social", "eligibility"):
        from viveka.social.commands import run as run_social

        return run_social(args, root, out=lines.append), "\n".join(lines)
    code = commands.run(args, root, transport=transport, out=lines.append)
    return code, "\n".join(lines)


def table(root, manifest, name):
    return tables.read(root / manifest["params"]["tables"][name])


def test_fetch_writes_tables_manifest_and_archive(world):
    root, fake = world
    run_id = commands.fetch_case(root, "cold-fusion", "dev", transport=fake.transport(), out=lambda s: None)
    manifest = load_manifest(root, run_id)
    assert manifest["stage"] == "S1" and verify_run(root, run_id) == []
    assert manifest["registry"]["components"]["cases/cold-fusion"].startswith("draft:")
    assert manifest["usage"]["live_calls"]["openalex"] == {"list": 3, "singleton": 1}
    assert manifest["usage"]["usd"]["openalex"] == pytest.approx(0.0003)
    works = {w["work_id"] for w in table(root, manifest, "works")}
    assert works == {"W1", "W2", *(f"W{10 + i}" for i in range(10)), "W30", "W31", "W32", "W33"}
    frames = table(root, manifest, "frames")
    assert sum(f["frame_id"] == "citing" for f in frames) == 11  # ten citing works and the null result
    assert sum(f["frame_id"] == "venue" for f in frames) == 4  # the census, not S1, excludes the editorial
    assert any(c["citation_id"] == "W10:W1" for c in table(root, manifest, "citations"))
    assert all(c.url.params.get("api_key") == "OA-SECRET" for c in fake.calls)
    raw = (root / "data" / "raw").rglob("*.json")
    assert not any("OA-SECRET" in p.read_text(encoding="utf-8") for p in raw)
    assert len(manifest["inputs"]) == 4


def test_rerun_replays_from_the_archive_with_identical_tables(world):
    root, fake = world
    first = load_manifest(root, commands.fetch_case(root, "cold-fusion", "dev", transport=fake.transport(),
                                                    out=lambda s: None))
    second = load_manifest(root, commands.fetch_case(root, "cold-fusion", "dev", transport=no_network(),
                                                     out=lambda s: None))
    assert second["usage"]["live_calls"] == {} and second["usage"]["replayed"]["openalex"] == 4
    assert first["params"]["tables"] == second["params"]["tables"]


def test_unresolved_registered_work_fails_the_run(world):
    root, fake = world
    del fake.works["W2"]
    before = {p.parent.name for p in (root / "runs").glob("*/manifest.json")}  # the copy includes real runs
    with pytest.raises(CaseError, match="W2"):
        commands.fetch_case(root, "cold-fusion", "dev", transport=fake.transport(), out=lambda s: None)
    new = [p.parent.name for p in (root / "runs").glob("*/manifest.json") if p.parent.name not in before]
    assert [load_manifest(root, run)["status"] for run in new] == ["failed"]


def test_census_needs_a_fetch_then_measures_coverage(world):
    root, fake = world
    with pytest.raises(CaseError, match="corpus fetch"):
        commands.census_case(root, "cold-fusion", "dev", transport=fake.transport(), out=lambda s: None)
    commands.fetch_case(root, "cold-fusion", "dev", transport=fake.transport(), out=lambda s: None)
    lines = []
    run_id = commands.census_case(root, "cold-fusion", "dev", transport=fake.transport(), out=lines.append)
    manifest = load_manifest(root, run_id)
    assert verify_run(root, run_id) == [] and manifest["seed"] == 20260915
    rows = {(r["frame_id"], r["year"]): r for r in table(root, manifest, "coverage")}
    # 1990: W10, W12, W14, W16, W18 (each with a DOI-less reference findable by volume and page) and the null
    # result W2 (one reference, resolvable)
    assert rows[("citing", 1990)] == {"case_id": "cold-fusion", "frame_id": "citing", "kind": "mainstream",
                                      "year": 1990, "frame_works": 6, "frame_works_excluded": 0, "sampled": 6,
                                      "measured": 6, "unmeasured": 0, "refs": 21, "resolved": 11,
                                      "refs_excluded": 0, "refs_unclassifiable": 0, "doiless": 5,
                                      "doiless_sampled": 5, "doiless_matched": 5, "doiless_rescued": 1,
                                      "doiless_unparseable": 0, "resolved_estimated": 16.0}
    # 1991: W11, W13, W15, W17 measured, each citing "An old book" (unclassifiable, so not counted); W19 has no DOI
    r1991 = rows[("citing", 1991)]
    assert (r1991["measured"], r1991["unmeasured"], r1991["refs"], r1991["refs_unclassifiable"],
            r1991["resolved_estimated"]) == (4, 1, 12, 4, 8.0)
    venue = rows[("venue", 1995)]
    assert (venue["frame_works"], venue["frame_works_excluded"], venue["unmeasured"], venue["refs"]) == (3, 1, 3, 0)
    report = "\n".join(lines)
    assert "| citing | mainstream | 11 | 0 | 11 | 9.1% | 33 | 0/4 | 15.2% | 5/5 (1) | 0/5 | 72.7% | yes |" in report
    assert "| venue | community | 3 | 1 | 3 | 100.0% | 0 | 0/0 | n/a | 0/0 (0) | 0/0 | n/a | no |" in report
    assert manifest["usage"]["live_calls"]["crossref"] == {"free": 14}  # 13 reference lists, 1 bibliographic query
    assert all(c.url.params.get("mailto") == "test@example.invalid" for c in fake.calls
               if c.url.host == "api.crossref.org")


def test_manual_imports_measure_unindexed_venue_works(world):
    root, fake = world
    commands.fetch_case(root, "cold-fusion", "dev", transport=fake.transport(), out=lambda s: None)
    csv = root / "data" / "raw" / "manual" / "iccf.csv"
    write_lf(csv, "work_id,ref_index,ref_text,doi,entered_by,source_note\n"
                  "W30,1,Fleischmann and Pons,10.1/seed,AM,p.1\nW30,2,A lab notebook,,AM,p.1\n")
    run_id = commands.census_case(root, "cold-fusion", "dev", manual=csv, transport=fake.transport(),
                                  out=lambda s: None)
    manifest = load_manifest(root, run_id)
    venue = next(r for r in table(root, manifest, "coverage") if r["frame_id"] == "venue")
    assert (venue["measured"], venue["refs"], venue["resolved"], venue["refs_unclassifiable"]) == (1, 1, 1, 1)
    assert any(i["path"] == "data/raw/manual/iccf.csv" for i in manifest["inputs"])
    outside = root / "iccf.csv"
    write_lf(outside, csv.read_text(encoding="utf-8"))
    code, text = run_cli(root, "census", "--case", "cold-fusion", "--fold", "dev", "--manual", str(outside),
                         transport=fake.transport())
    assert code == 1 and "data/raw/manual" in text


def test_strict_folds_refuse_draft_definitions(world):
    root, fake = world
    with pytest.raises((ProvenanceError, RegistryError)):
        commands.fetch_case(root, "cold-fusion", "pilot", transport=fake.transport(), out=lambda s: None)
    assert fake.calls == []


def test_dry_runs_project_without_network(world):
    root, fake = world
    code, text = run_cli(root, "corpus", "fetch", "--case", "cold-fusion", "--fold", "dev", "--dry-run",
                         transport=no_network())
    assert code == 0 and "not projectable yet" in text and "openalex list: 1" in text
    code, text = run_cli(root, "corpus", "fetch", "--case", "cold-fusion", "--fold", "dev", "--probe",
                         transport=fake.transport())
    assert code == 0 and "not projectable yet" not in text
    commands.fetch_case(root, "cold-fusion", "dev", transport=fake.transport(), out=lambda s: None)
    code, text = run_cli(root, "corpus", "fetch", "--case", "cold-fusion", "--fold", "dev", "--dry-run",
                         transport=no_network())
    assert "nothing to fetch: every request is already archived" in text  # no call left to project or price
    code, text = run_cli(root, "census", "--case", "cold-fusion", "--fold", "dev", "--dry-run",
                         transport=no_network())
    assert code == 0 and "crossref free: 13 live call(s)" in text and "assumed 40 references" in text


def test_contexts_stage(world):
    root, fake = world
    fake.s2_citations["10.1/seed"] = [
        {"contexts": ["as reported [1]", "cf. [1]"], "intents": ["background"], "isInfluential": False,
         "citingPaper": {"paperId": "p1", "externalIds": {"DOI": "10.2/c0"}}}]
    run_id = commands.fetch_contexts(root, "cold-fusion", "dev", transport=fake.transport(), out=lambda s: None)
    manifest = load_manifest(root, run_id)
    rows = table(root, manifest, "contexts")
    assert [(r["cited_work"], r["citing_doi"], r["context_index"]) for r in rows] == [
        ("W1", "10.2/c0", 0), ("W1", "10.2/c0", 1)]
    assert manifest["params"]["truncated"] == [] and manifest["params"]["without_doi"] == []
    assert manifest["params"]["semanticscholar_key"] is True
    assert all(c.headers.get("x-api-key") == "S2-SECRET" for c in fake.calls if c.url.host.endswith("scholar.org"))


def test_contexts_run_without_a_semantic_scholar_key_at_the_keyless_rate(world, monkeypatch):
    root, fake = world
    monkeypatch.delenv("S2_API_KEY")
    fake.s2_citations["10.1/seed"] = [{"contexts": ["as reported [1]"], "intents": [], "isInfluential": False,
                                       "citingPaper": {"paperId": "p1", "externalIds": {}}}]
    sleeps = []
    monkeypatch.setattr("viveka.corpus.http.time.sleep", sleeps.append)
    run_id = commands.fetch_contexts(root, "cold-fusion", "dev", transport=fake.transport(), out=lambda s: None)
    manifest = load_manifest(root, run_id)
    assert manifest["params"]["semanticscholar_key"] is False
    assert len(table(root, manifest, "contexts")) == 1
    s2_calls = [c for c in fake.calls if c.url.host.endswith("scholar.org")]
    assert s2_calls and not any("x-api-key" in c.headers for c in s2_calls)
    config = commands.load_corpus_config(root)
    assert any(s == pytest.approx(1 / config.semanticscholar["keyless_requests_per_second"], rel=0.05)
               for s in sleeps) or len(s2_calls) == 1


def test_missing_credentials_are_named(world, monkeypatch):
    root, fake = world
    monkeypatch.delenv("OPENALEX_API_KEY")
    code, text = run_cli(root, "corpus", "fetch", "--case", "cold-fusion", "--fold", "dev",
                         transport=fake.transport())
    assert code == 1 and "OPENALEX_API_KEY" in text and fake.calls == []


def test_a_calibration_field_runs_through_fetch_and_census(world):
    root, fake = world
    write_field(root)
    code, text = run_cli(root, "field", "validate", "test-field")
    assert code == 0 and "pseudoscience, 1 frame(s) over 1 source(s)" in text and "1 absent venue(s)" in text
    run_id = commands.fetch_case(root, "test-field", "dev", field=True, transport=fake.transport(), out=lambda s: None)
    manifest = load_manifest(root, run_id)
    assert manifest["registry"]["components"]["fields/test-field"].startswith("draft:")
    assert "cases/cold-fusion" not in manifest["registry"]["components"]
    assert {w["work_id"] for w in table(root, manifest, "works")} == {"W30", "W31", "W32", "W33"}  # no seeds
    lines = []
    census = load_manifest(root, commands.census_case(root, "test-field", "dev", field=True,
                                                      transport=fake.transport(), out=lines.append))
    assert set(census["registry"]["components"]) == {"schemas", "corpus", "fields/test-field"}
    (row,) = table(root, census, "coverage")
    assert (row["frame_id"], row["frame_works"], row["frame_works_excluded"], row["unmeasured"]) == ("venues", 3, 1, 3)
    report = "\n".join(lines)
    assert "| venues | community | 3 | 1 | 3 | 100.0% |" in report and "- An unindexed bulletin" in report
    code, text = run_cli(root, "corpus", "contexts", "--field", "test-field", "--fold", "dev",
                         transport=no_network())
    assert code == 1 and "no bearing set" in text
    code, text = run_cli(root, "census", "--field", "test-field", "--fold", "dev", "--dry-run", transport=no_network())
    assert code == 0 and "census dry run for test-field: 3 sampled works" in text


def test_a_field_without_frames_gets_an_empty_census_listing_its_absent_venues(world):
    root, fake = world
    write_field(root, FIELD_YAML.replace("frames:\n  - {id: venues, kind: community, sources: [S5]}\n", "frames: []\n"))
    commands.fetch_case(root, "test-field", "dev", field=True, transport=fake.transport(), out=lambda s: None)
    lines = []
    census = load_manifest(root, commands.census_case(root, "test-field", "dev", field=True,
                                                      transport=fake.transport(), out=lines.append))
    assert table(root, census, "coverage") == []
    report = "\n".join(lines)
    assert "No frames: none of this field's venues" in report and "- An unindexed bulletin" in report


def test_an_ingested_venue_is_listed_extracted_and_matched_against_its_own_catalogue(world):
    root, fake = world
    base = "https://crsq.creationresearch.org"
    listing = [
        {"eprintid": 11, "title": "Rapid erosion", "date": "1995-06", "volume": 32, "number": 1, "type": "article",
         "creators": [{"name": {"family": "Wills", "given": "E. L."}}],
         "documents": [{"format": "application/pdf", "files": [{"uri": f"{base}/id/file/11"}]}]},
        {"eprintid": 12, "title": "Trace marks", "date": "1995-09", "volume": 32, "number": 2, "type": "article",
         "creators": [{"name": {"family": "Cole", "given": "J. H."}}],
         "documents": [{"format": "application/pdf", "files": [{"uri": f"{base}/id/file/12"}]}]},
        {"eprintid": 13, "title": "Index", "date": "1995-12", "volume": 32, "number": 3, "type": "book_section"},
    ]
    fake.documents[f"{base}/cgi/exportview/year/1995/JSON/1995.js"] = (json.dumps(listing).encode(), "application/json")
    fake.documents[f"{base}/id/file/11"] = (text_pdf([
        "Rapid erosion", "Body text.", "References",
        "Cole, J. H. 1995. Trace marks in sediments. CRSQ 32:10-12.",
        "Doe, A. 1990. A long book. University Press. York.",
        "Roe, B. 1986. Reanalysis. Physical Review Letters 56:3-6."]), "application/pdf")
    fake.documents[f"{base}/id/file/12"] = (text_pdf(["Trace marks", "No reference list."]), "application/pdf")
    write_field(root, FIELD_YAML.replace("sources: [S5]}", "ingest: [crsq]}"))
    fetch = load_manifest(root, commands.fetch_case(root, "test-field", "dev", field=True, transport=fake.transport(),
                                                    out=lambda s: None))
    assert fetch["params"]["ingestion"] == {"venues": {"crsq": "eprints_json_v1"}}
    assert {w["work_id"]: w["type"] for w in table(root, fetch, "works")} == {
        "X:crsq:11": "article", "X:crsq:12": "article", "X:crsq:13": "other"}
    assert {a["author_id"] for a in table(root, fetch, "authors")} == {"name:wills:e", "name:cole:j"}
    lines = []
    census = load_manifest(root, commands.census_case(root, "test-field", "dev", field=True,
                                                      transport=fake.transport(), out=lines.append))
    (row,) = table(root, census, "coverage")
    assert (row["frame_works"], row["frame_works_excluded"], row["sampled"], row["measured"], row["unmeasured"],
            row["refs"], row["refs_excluded"], row["doiless_sampled"], row["doiless_matched"]) == (2, 1, 2, 1, 1, 2, 1,
                                                                                                 2, 2)
    sample = {r["work_id"]: r["reference_source"] for r in table(root, census, "census_sample")}
    assert sample == {"X:crsq:11": "ingested", "X:crsq:12": "none"}
    assert census["params"]["ingestion"]["catalogue_match"] == "ingested_catalogue_v1"
    assert "Venues ingested from their own archives (crsq)" in "\n".join(lines)
    code, text = run_cli(root, "census", "--field", "test-field", "--fold", "dev", "--dry-run", transport=no_network())
    assert code == 0 and "2 sampled works" in text  # documents replay from the archive

    # The audit: sheets from the census, filled in by hand, then stated in the report of a re-run census.
    code, text = run_cli(root, "corpus", "audit", "--field", "test-field", "--fold", "dev", transport=no_network())
    assert code == 0 and "3 references from 1 papers" in text
    sheet = root / "data" / "raw" / "manual" / "audit" / f"test-field-{census['run_id']}-references.csv"
    rows = sheet.read_text(encoding="utf-8").splitlines()
    assert rows[0].startswith("work_id,ref_index,document_url,extracted_text") and len(rows) == 4
    code, text = run_cli(root, "census", "--field", "test-field", "--fold", "dev", "--audit", str(sheet),
                         transport=no_network())
    assert code == 1 and "verdict must be one of" in text  # an unfilled sheet is refused
    verdicts = iter(["correct", "correct", "merged"])
    write_lf(sheet, "\n".join([rows[0], *(r[: -len(",,,")] + f",{next(verdicts)},,AM" for r in rows[1:])]) + "\n")
    works = sheet.with_name(sheet.name.replace("-references", "-works"))
    head, row = works.read_text(encoding="utf-8").splitlines()
    write_lf(works, f"{head}\n{row[: -len(',,')]},4,AM\n")
    lines = []
    commands.census_case(root, "test-field", "dev", field=True, audit=sheet, transport=no_network(), out=lines.append)
    report = "\n".join(lines)
    assert "3 extracted references checked against their documents: correct 2, wrong fields 0, merged 1" in report
    assert "have 3 extracted references against 4 in the documents" in report and "not yet audited" not in report
    with pytest.raises(AuditError, match="never overwritten"):
        write_once(sheet, b"x")


def test_a_document_the_publisher_refuses_leaves_its_paper_unmeasured_and_is_counted(world):
    root, fake = world
    base = "https://crsq.creationresearch.org"
    listing = [
        {"eprintid": n, "title": f"Paper {n}", "date": "1995-06", "volume": 32, "number": 1, "type": "article",
         "creators": [{"name": {"family": "Wills", "given": "E. L."}}],
         "documents": [{"format": "application/pdf", "files": [{"uri": f"{base}/id/file/{n}"}]}]}
        for n in (11, 12)]
    fake.documents[f"{base}/cgi/exportview/year/1995/JSON/1995.js"] = (json.dumps(listing).encode(), "application/json")
    fake.documents[f"{base}/id/file/11"] = (text_pdf([
        "Paper 11", "References", "Roe, B. 1986. Reanalysis. Physical Review Letters 56:3-6."]), "application/pdf")
    fake.refused_documents.add(f"{base}/id/file/12")
    write_field(root, FIELD_YAML.replace("sources: [S5]}", "ingest: [crsq]}"))
    commands.fetch_case(root, "test-field", "dev", field=True, transport=fake.transport(), out=lambda s: None)
    lines = []
    census = load_manifest(root, commands.census_case(root, "test-field", "dev", field=True,
                                                      transport=fake.transport(), out=lines.append))
    (row,) = table(root, census, "coverage")
    assert (row["sampled"], row["measured"], row["unmeasured"]) == (2, 1, 1)
    assert "Documents the publisher refused (HTTP 401/403" in "\n".join(lines) and "): crsq 1." in "\n".join(lines)
    replay = []
    commands.census_case(root, "test-field", "dev", field=True, transport=no_network(), out=replay.append)
    assert "): crsq 1." in "\n".join(replay)  # the refusal replays from the archive


def test_field_overlap_is_a_registered_run_over_the_latest_fetches(world):
    root, fake = world
    write_field(root)
    commands.fetch_case(root, "test-field", "dev", field=True, transport=fake.transport(), out=lambda s: None)
    commands.fetch_case(root, "cold-fusion", "dev", transport=fake.transport(), out=lambda s: None)
    code, text = run_cli(root, "field", "overlap", "--fold", "dev")
    assert code == 0 and "| cold-fusion | test-field | openalex_id | 1 | 1 | 1 | 100.0% | yes: cold-fusion |" in text
    run = next(m for m in (load_manifest(root, p.parent.name) for p in (root / "runs").glob("*/manifest.json"))
               if m["stage"] == "S1-overlap")
    assert run["params"]["max_overlap"] == 0.2 and "core_min_works" in run["params"]
    assert "17kev-neutrino" in run["params"]["without_fetch"]
    (row,) = [r for r in table(root, run, "overlap") if {r["subject_a"], r["subject_b"]} == {"cold-fusion",
                                                                                             "test-field"}]
    assert (row["shared"], row["exceeds"]) == (1, True)  # the fake venue works share one author


def test_a_calibration_fold_refuses_a_draft_field(world):
    root, fake = world
    write_field(root)
    with pytest.raises(RegistryError, match="fields/test-field"):
        commands.fetch_case(root, "test-field", "calibration", field=True, transport=no_network(),
                            out=lambda s: None)


def test_case_validate_and_resolve(world):
    root, fake = world
    code, text = run_cli(root, "case", "validate", "cold-fusion")
    assert code == 0 and "1 events" in text and "venue (community)" in text
    code, text = run_cli(root, "corpus", "resolve", "--doi", "https://doi.org/10.1/SEED", transport=fake.transport())
    assert code == 0 and text.startswith("W1  doi=10.1/seed  1989")
    code, text = run_cli(root, "corpus", "resolve", "--source", "venue", transport=fake.transport())
    assert code == 0 and text.startswith("S5  Venue S5")


def test_social_build_clusters_a_fetched_case_and_marks_the_run_provisional(world):
    from viveka.social.commands import social_build, social_dry_run

    root, fake = world
    lines = []
    assert social_dry_run(root, "cold-fusion", "dev", out=lines.append) == 1 and "fetch first" in lines[0]
    commands.fetch_case(root, "cold-fusion", "dev", transport=fake.transport(), out=lambda s: None)
    lines = []
    run = load_manifest(root, social_build(root, "cold-fusion", "dev", out=lines.append))
    assert run["stage"] == "S3" and run["params"]["provisional"] is True
    assert run["params"]["methods_run"] == ["leiden"] and run["params"]["methods_unavailable"] == ["hsbm"]
    assert "thresholds" in run["registry"]["components"] and "Provisional" in "\n".join(lines)
    clusters, lineages = table(root, run, "clusters"), table(root, run, "lineages")
    assert clusters and {r["resolution"] for r in clusters} == set(run["params"]["resolutions"])
    assert all(r["members"] >= run["params"]["lineage_min_members"] for r in lineages)
    again = load_manifest(root, social_build(root, "cold-fusion", "dev", out=lambda s: None))
    assert again["params"]["tables"]["clusters"] == run["params"]["tables"]["clusters"]  # deterministic


def test_eligibility_reads_the_latest_social_layer_and_records_the_decision(world):
    from viveka.social.commands import eligibility_run, social_build

    root, fake = world
    commands.fetch_case(root, "cold-fusion", "dev", transport=fake.transport(), out=lambda s: None)
    with pytest.raises(CaseError, match="social build"):
        eligibility_run(root, "cold-fusion", "dev", out=lambda s: None)
    social_build(root, "cold-fusion", "dev", out=lambda s: None)
    lines = []
    run = load_manifest(root, eligibility_run(root, "cold-fusion", "dev", out=lines.append))
    assert run["stage"] == "S4" and verify_run(root, run["run_id"]) == []
    assert run["params"]["decision"] == "replace" and run["params"]["eligible_lineages"] == []  # m = 320
    assert run["params"]["n"].startswith("pending") and run["params"]["provisional"] is True
    rows = table(root, run, "eligibility")
    assert rows and not any(r["meets_m"] for r in rows)
    assert any(r["citations_on_claim"] > 0 for r in rows)  # the fake citing works cite the seeds
    assert "Decision at resolution 1: replace" in "\n".join(lines)


def test_a_field_commitment_goes_through_the_social_layer_and_eligibility(world):
    from viveka.social.commands import eligibility_run, social_build

    root, fake = world
    write_lf(root / "registry" / "events" / "p-holds.yaml",
             'format: 1\nclaim: p-holds\nwording: "p holds."\nevents:\n'
             '  - id: e1\n    date: "1990"\n    kind: disconfirmation\n'
             "    works: [{openalex: W1}]\n"
             '    note: "A result against p."\n    source: "Lookup."\n')
    write_field(root, FIELD_YAML.replace("format: 1", "format: 2").rstrip("\n")
                + "\ncommitments:\n  - id: c1\n    claim: p-holds\n    seeds: [{openalex: W2}]\n"
                  '    note: "Cited as support."\n')
    fetch = load_manifest(root, commands.fetch_case(root, "test-field", "dev", field=True,
                                                    transport=fake.transport(), out=lambda s: None))
    frames = table(root, fetch, "frames")
    bearing = {f["work_id"] for f in frames if f["kind"] == "bearing"}
    # The bearing frame holds the commitment's anchors and the works citing them, wherever published: W2 is its
    # seed, W1 its event work, and the citing works come from outside the field's own venue frame.
    assert {"W1", "W2"} <= bearing and bearing - {f["work_id"] for f in frames if f["kind"] == "community"}
    assert fetch["params"]["bearing_frames"] == {"c1": 2}
    census = load_manifest(root, commands.census_case(root, "test-field", "dev", field=True,
                                                      transport=fake.transport(), out=lambda s: None))
    assert {r["frame_id"] for r in table(root, census, "coverage")} == {"venues"}  # never censused
    social = load_manifest(root, social_build(root, "test-field", "dev", field=True, out=lambda s: None))
    clustered = {r["author"] for r in table(root, social, "clusters")}
    assert not (clustered & {f"A{10 + i}" for i in range(10)})  # the citing literature's authors are not nodes
    with pytest.raises(CaseError, match="--commitment"):
        eligibility_run(root, "test-field", "dev", field=True, out=lambda s: None)
    lines = []
    manifest = load_manifest(root, eligibility_run(root, "test-field", "dev", field=True, commitment="c1",
                                                   out=lines.append))
    assert manifest["case"] == "test-field-c1" and manifest["params"]["claim"] == "p-holds"
    assert manifest["registry"]["components"]["fields/test-field"].startswith("draft:")
    assert manifest["params"]["decision"] == "replace" and "Decision at resolution 1" in "\n".join(lines)
    code, text = run_cli(root, "eligibility", "--field", "test-field", "--commitment", "c9", "--fold", "dev")
    assert code == 1 and "no commitment" in text


def test_the_fetch_dry_run_projects_each_commitment_s_bearing_frame(world):
    root, fake = world
    write_lf(root / "registry" / "events" / "p-holds.yaml",
             'format: 1\nclaim: p-holds\nwording: "p holds."\nevents:\n'
             '  - id: e1\n    date: "1990"\n    kind: disconfirmation\n'
             "    works: [{openalex: W1}]\n"
             '    note: "A result against p."\n    source: "Lookup."\n')
    write_field(root, FIELD_YAML.replace("format: 1", "format: 2").rstrip("\n")
                + "\ncommitments:\n  - id: c1\n    claim: p-holds\n    seeds: [{openalex: W2}]\n"
                  '    note: "Cited as support."\n')
    # before anything is archived the anchors cannot be resolved, so the frame is named as unprojectable
    code, text = run_cli(root, "corpus", "fetch", "--field", "test-field", "--fold", "dev", "--dry-run",
                         transport=no_network())
    assert code == 0 and "bearing frame c1: its anchors are not resolved yet" in text
    commands.fetch_case(root, "test-field", "dev", field=True, transport=fake.transport(), out=lambda s: None)
    code, text = run_cli(root, "corpus", "fetch", "--field", "test-field", "--fold", "dev", "--dry-run",
                         transport=no_network())
    assert code == 0 and "nothing to fetch" in text  # the bearing frame's pages are archived too


def _relax_gate_one(root):
    """m and v down to 1 in the test registry, so the fixture's small clusters reach gate 1's first two checks."""
    path = root / "registry" / "thresholds.yaml"
    text = path.read_text(encoding="utf-8")
    assert text.count("value: 190") == 1 and text.count("value: 463") == 1
    write_lf(path, text.replace("value: 190", "value: 1").replace("value: 463", "value: 1"))


def test_the_cluster_census_measures_the_windows_that_pass_m_and_v_and_s4_reads_its_coverage(world):
    from viveka.social.commands import eligibility_run, social_build

    root, fake = world
    commands.fetch_case(root, "cold-fusion", "dev", transport=fake.transport(), out=lambda s: None)
    social_build(root, "cold-fusion", "dev", out=lambda s: None)
    eligibility_run(root, "cold-fusion", "dev", out=lambda s: None)
    # At the registered m no window passes, and coverage can withhold eligibility but never grant it
    with pytest.raises(CaseError, match="meets m and v"):
        commands.census_clusters(root, "cold-fusion", "dev", transport=no_network(), out=lambda s: None)

    _relax_gate_one(root)
    social_build(root, "cold-fusion", "dev", out=lambda s: None)
    before = load_manifest(root, eligibility_run(root, "cold-fusion", "dev", out=lambda s: None))
    assert before["params"]["cluster_census_run"] is None
    assert all(r["meets_r"] is None for r in table(root, before, "eligibility"))

    lines = []
    census = load_manifest(root, commands.census_clusters(root, "cold-fusion", "dev", transport=fake.transport(),
                                                          out=lines.append))
    assert census["stage"] == "S2C" and verify_run(root, census["run_id"]) == []
    assert census["params"]["cluster_resolution"] == 1.0 and census["params"]["cluster_frames"] >= 1
    assert census["params"]["s3_run"] and census["params"]["s4_runs"]["cold-fusion"]
    coverage = table(root, census, "coverage")
    assert coverage and {r["kind"] for r in coverage} == {"cluster"}
    assert all("@" in r["frame_id"] for r in coverage)  # one frame per lineage and sub-window
    assert "Coverage census with cluster frames" in "\n".join(lines)

    said = []
    after = load_manifest(root, eligibility_run(root, "cold-fusion", "dev", out=said.append))
    assert after["params"]["cluster_census_run"] == census["run_id"]
    # the closing sentence has to follow the table: with coverage measured, it reports what passed, not the
    # "no lineage passes m and v" line that belongs to a case where nothing did
    decision = [line for line in "\n".join(said).splitlines() if line.startswith("**Decision")][0]
    assert after["params"]["windows_passing_m_and_v"] >= 1
    assert "No lineage passes m and v" not in decision
    assert "eligible pending n" in decision if after["params"]["eligible_lineages"] else True
    rows = table(root, after, "eligibility")
    assert any(r["coverage"] is not None and r["meets_r"] is not None for r in rows if r["resolution"] == 1.0)
    # the sweep's other resolutions have no cluster census of their own, so their coverage stays unmeasured
    assert all(r["meets_r"] is None for r in rows if r["resolution"] != 1.0)
