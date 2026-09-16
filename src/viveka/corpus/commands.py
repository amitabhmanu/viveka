"""`viveka corpus`, `viveka case` and `viveka census`: stages S1-S2 (spec §7) and the drafting aid.

``corpus fetch`` (S1) resolves a case's registered works in OpenAlex and collects every work in its
frames; ``corpus contexts`` adds Semantic Scholar citation contexts for the bearing set; ``census``
(S2) samples each frame and measures reference coverage. Each stage runs inside a RunContext over
``cases/<case>`` and its upstream components (corpus, events/<claim>, schemas), so outside the
development fold the case, its claim and the corpus settings must be frozen first.
"""

from __future__ import annotations

import argparse
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from viveka import env
from viveka.cases import Case, CaseError, Claim, WorkRef, bearing_set, load_case
from viveka.census import (
    FrameWork,
    References,
    Summary,
    biblio_of,
    coverage_rows,
    doiless_sample,
    match_found,
    outcome,
    sample_frame,
    summarize,
)
from viveka.corpus import crossref, openalex, semanticscholar, tables
from viveka.corpus.config import LIVE_SOURCES, CensusSettings, CorpusConfig, load_corpus_config
from viveka.corpus.http import Fetcher, FetchError, UsageMeter
from viveka.corpus.ids import normalize_doi, short_id
from viveka.corpus.manual import MANUAL_DIR, ManualImportError, load_manual
from viveka.paths import rel_posix
from viveka.provenance import FOLDS, RunContext, recent_runs
from viveka.registry.verify import require_frozen

Out = Callable[[str], None]
ASSUMED_REFS_PER_WORK = 40  # dry-run estimate only, for sampled works whose reference lists are not archived yet


# ---------------------------------------------------------------- fetchers


def make_fetcher(root: Path, config: CorpusConfig, *, need: Sequence[str] = (), offline: bool = False,
                 transport: httpx.BaseTransport | None = None, run_id: str | None = None) -> Fetcher:
    """A fetcher with the registered rates, prices and cap; credentials are required only for live use."""
    env.load(root)
    secrets: dict[str, dict[str, dict[str, str]]] = {}
    if not offline:
        if "openalex" in need:
            secrets["openalex"] = {"params": {"api_key": env.require(env.OPENALEX_API_KEY)}}
        if "crossref" in need:
            secrets["crossref"] = {"params": {"mailto": env.require(env.CONTACT_EMAIL)}}
        if "semanticscholar" in need and env.get(env.S2_API_KEY):  # optional: the public API needs no account
            secrets["semanticscholar"] = {"headers": {"x-api-key": env.require(env.S2_API_KEY)}}
    rates = {s: config.rate(s) for s in LIVE_SOURCES}
    if "semanticscholar" not in secrets:
        rates["semanticscholar"] = float(config.semanticscholar["keyless_requests_per_second"])
    meter = UsageMeter(root, prices={s: config.api[s].get("prices_usd", {}) for s in LIVE_SOURCES},
                       caps={"openalex": float(config.openalex["daily_usd_cap"])})
    return Fetcher(root, rates=rates, meter=meter, terms=config.terms,
                   secrets=secrets, contact_email=None if offline else env.get(env.CONTACT_EMAIL),
                   transport=transport, offline=offline, run_id=run_id)


def _finish(ctx: RunContext, fetcher: Fetcher) -> None:
    ctx.usage.update(fetcher.usage.as_manifest())
    for path in fetcher.used_paths.values():
        ctx.record_input(path)


# ---------------------------------------------------------------- S1: corpus


def resolve_refs(fetcher: Fetcher, config: CorpusConfig, refs: Sequence[WorkRef]) -> dict[WorkRef, dict | None]:
    found: dict[WorkRef, dict | None] = {}
    for ref in refs:
        if ref.openalex:
            response = fetcher.get(openalex.work_request(ref.openalex))
            found[ref] = response.body if response.status == 200 else None
    by_doi = openalex.lookup_dois(fetcher, [r.doi for r in refs if not r.openalex], int(config.openalex["doi_batch"]))
    for ref in refs:
        if not ref.openalex:
            found[ref] = by_doi.get(ref.doi or "")
    return found


def _seed_ids(case: Case, resolved: dict[WorkRef, dict | None]) -> list[str]:
    return sorted({short_id(obj["id"]) for ref, obj in resolved.items() if ref in case.seeds and obj})


def collect_corpus(fetcher: Fetcher, config: CorpusConfig, case: Case, claim: Claim) -> dict[str, list[dict]]:
    bearing = bearing_set(case, claim)
    resolved = resolve_refs(fetcher, config, bearing)
    missing = [r.key for r in bearing if resolved[r] is None]
    if missing:
        raise CaseError(f"registered works not found in OpenAlex: {', '.join(missing)}; fix the case or claim "
                        "definition (a frozen one needs a bump)")
    seed_ids = _seed_ids(case, resolved)
    per_page = int(config.openalex["per_page"])
    works: dict[str, dict] = {short_id(obj["id"]): obj for obj in resolved.values() if obj}
    frame_rows = []
    for frame in case.frames:
        values = seed_ids if frame.cites_seeds else list(frame.sources)
        for flt in openalex.frame_filters(frame.cites_seeds, values, case.start, case.end):
            for page in openalex.iter_pages(fetcher, flt, per_page):
                for obj in (page.body or {}).get("results") or []:
                    work_id = short_id(obj.get("id"))
                    works.setdefault(work_id, obj)
                    frame_rows.append({"case_id": case.case_id, "frame_id": frame.frame_id, "kind": frame.kind,
                                       "work_id": work_id, "year": obj.get("publication_year")})
    objs = list(works.values())
    return {
        "works": [openalex.work_row(o) for o in objs],
        "authors": [row for o in objs for row in openalex.author_rows(o)],
        "authorships": [row for o in objs for row in openalex.authorship_rows(o)],
        "citations": [row for o in objs for row in openalex.citation_rows(o)],
        "frames": frame_rows,
    }


@dataclass
class Projection:
    calls: Counter = field(default_factory=Counter)  # (source, kind) -> live calls still needed
    unknown: list[str] = field(default_factory=list)

    def usd(self, config: CorpusConfig) -> float:
        return sum(n * config.price(source, kind) for (source, kind), n in self.calls.items())

    def lines(self, config: CorpusConfig) -> list[str]:
        out = [f"  {source} {kind}: {n} live call(s)" for (source, kind), n in sorted(self.calls.items())]
        out.append(f"  projected OpenAlex spend: ${self.usd(config):.4f} (cap ${config.openalex['daily_usd_cap']:.2f}"
                   " per day, including other runs today)")
        out += [f"  not projectable yet: {u}" for u in self.unknown]
        return out or ["  nothing to fetch: every request is already archived"]


def project_fetch(fetcher: Fetcher, config: CorpusConfig, case: Case, claim: Claim) -> Projection:
    """Live calls S1 still needs, read from the archive alone (the fetcher must be offline)."""
    projection = Projection()
    bearing = bearing_set(case, claim)
    resolved: dict[WorkRef, dict | None] = {}
    complete = True
    for ref in bearing:
        if ref.openalex:
            hit = fetcher.archived(openalex.work_request(ref.openalex))
            if hit is None:
                projection.calls[("openalex", "singleton")] += 1
                complete = False
            else:
                resolved[ref] = hit.body
    doi_refs = [r for r in bearing if not r.openalex]
    found: dict[str, dict] = {}
    wanted = sorted({r.doi for r in doi_refs if r.doi})
    for chunk in [wanted[i : i + int(config.openalex["doi_batch"])]
                  for i in range(0, len(wanted), int(config.openalex["doi_batch"]))]:
        hit = fetcher.archived(openalex.doi_batch_request(chunk))
        if hit is None:
            projection.calls[("openalex", "list")] += 1
            complete = False
        else:
            found.update({normalize_doi(o.get("doi")): o for o in (hit.body or {}).get("results") or []})
    for ref in doi_refs:
        resolved[ref] = found.get(ref.doi or "")
    if not complete:
        projection.unknown.append("frame sizes: registered works are not resolved yet (use --probe)")
        return projection
    seed_ids = _seed_ids(case, resolved)
    per_page = int(config.openalex["per_page"])
    for frame in case.frames:
        values = seed_ids if frame.cites_seeds else list(frame.sources)
        for flt in openalex.frame_filters(frame.cites_seeds, values, case.start, case.end):
            first = fetcher.archived(openalex.list_request(flt, "*", per_page))
            if first is None:
                projection.calls[("openalex", "list")] += 1
                projection.unknown.append(f"frame {frame.frame_id}: size unknown until its first page is probed")
                continue
            pages = max(1, math.ceil(int(((first.body or {}).get("meta") or {}).get("count", 0)) / per_page))
            archived, page = 1, first
            while archived < pages:
                cursor = ((page.body or {}).get("meta") or {}).get("next_cursor")
                page = fetcher.archived(openalex.list_request(flt, cursor, per_page)) if cursor else None
                if page is None:
                    break
                archived += 1
            projection.calls[("openalex", "list")] += pages - archived
    return projection


def probe(fetcher: Fetcher, config: CorpusConfig, case: Case, claim: Claim) -> None:
    """Live: resolve the registered works and fetch each frame's first page, so a dry run can project exactly."""
    resolved = resolve_refs(fetcher, config, bearing_set(case, claim))
    seed_ids = _seed_ids(case, resolved)
    for frame in case.frames:
        values = seed_ids if frame.cites_seeds else list(frame.sources)
        for flt in openalex.frame_filters(frame.cites_seeds, values, case.start, case.end):
            fetcher.get(openalex.list_request(flt, "*", int(config.openalex["per_page"])))


def fetch_case(root: Path, case_id: str, fold: str, *, transport: httpx.BaseTransport | None = None,
               out: Out = print) -> str:
    case, claim = load_case(root, case_id)
    config = load_corpus_config(root)
    with RunContext(root, "S1", case_id, fold, [f"cases/{case_id}"],
                    params={"window": [case.start, case.end]}) as ctx:
        with make_fetcher(root, config, need=("openalex",), transport=transport, run_id=ctx.run_id) as fetcher:
            try:
                rows = collect_corpus(fetcher, config, case, claim)
            finally:
                _finish(ctx, fetcher)
        written = {}
        for name in ("works", "authors", "authorships", "citations", "frames"):
            path = ctx.store(tables.to_parquet(name, rows[name]), "parquet", rows=len(rows[name]))
            written[name] = rel_posix(path, root)
        ctx.params["tables"] = written
    frame_sizes = Counter(frame for frame, _ in {(r["frame_id"], r["work_id"]) for r in rows["frames"]})
    out(f"run {ctx.run_id}: {len({r['work_id'] for r in rows['works']})} works; "
        + ", ".join(f"frame {f.frame_id}: {frame_sizes.get(f.frame_id, 0)}" for f in case.frames))
    out(_usage_line(ctx.usage))
    return ctx.run_id


# ---------------------------------------------------------------- S1: contexts


def fetch_contexts(root: Path, case_id: str, fold: str, *, transport: httpx.BaseTransport | None = None,
                   out: Out = print) -> str:
    case, claim = load_case(root, case_id)
    config = load_corpus_config(root)
    s2 = config.semanticscholar
    with RunContext(root, "S1-contexts", case_id, fold, [f"cases/{case_id}"]) as ctx:
        with make_fetcher(root, config, need=("openalex", "semanticscholar"), transport=transport,
                          run_id=ctx.run_id) as fetcher:
            try:
                resolved = resolve_refs(fetcher, config, bearing_set(case, claim))
                rows, truncated, without_doi = [], [], []
                for obj in (o for o in resolved.values() if o):
                    work_id, doi = short_id(obj["id"]), normalize_doi(obj.get("doi"))
                    if not doi:
                        without_doi.append(work_id)
                        continue
                    items, cut = semanticscholar.iter_citations(fetcher, doi, int(s2["page_size"]),
                                                                int(s2["max_offset"]))
                    if cut:
                        truncated.append(work_id)
                    rows += [row for item in items for row in semanticscholar.context_rows(work_id, item)]
            finally:
                _finish(ctx, fetcher)
        path = ctx.store(tables.to_parquet("contexts", rows), "parquet", rows=len(rows))
        ctx.params.update({"tables": {"contexts": rel_posix(path, root)}, "truncated": sorted(truncated),
                           "without_doi": sorted(without_doi),
                           "semanticscholar_key": env.get(env.S2_API_KEY) is not None})
    out(f"run {ctx.run_id}: {len(rows)} citation contexts"
        + (f"; truncated at the offset limit for {', '.join(truncated)}" if truncated else "")
        + (f"; no DOI for {', '.join(without_doi)}" if without_doi else ""))
    out(_usage_line(ctx.usage))
    return ctx.run_id


# ---------------------------------------------------------------- S2: census


def latest_run(root: Path, stage: str, case_id: str, fold: str, components: dict[str, str]) -> dict | None:
    """The newest successful run of ``stage`` for the case, fold and exact registry component hashes."""
    for manifest in recent_runs(root, limit=10_000):
        if (manifest.get("stage") == stage and manifest.get("case") == case_id and manifest.get("fold") == fold
                and manifest.get("status") == "ok" and manifest["registry"]["components"] == components):
            return manifest
    return None


def draw_sample(case: Case, frames_rows: list[dict], works_rows: list[dict], per_year: int, seed: int
                ) -> tuple[dict[str, list[FrameWork]], dict[str, list[FrameWork]], dict[str, str], int]:
    doi_of = {w["work_id"]: w["doi"] for w in works_rows}
    by_frame: dict[str, list[FrameWork]] = defaultdict(list)
    kinds = {f.frame_id: f.kind for f in case.frames}
    undated = 0
    for row in frames_rows:
        if row["year"] is None:
            undated += 1
            continue
        by_frame[row["frame_id"]].append(FrameWork(row["work_id"], int(row["year"]), doi_of.get(row["work_id"])))
    samples = {fid: sample_frame(case.case_id, fid, works, per_year, seed) for fid, works in by_frame.items()}
    return dict(by_frame), samples, kinds, undated


def _fetch_inputs(root: Path, case_id: str, fold: str) -> tuple[dict, list[dict], list[dict]]:
    components = require_frozen(root, [f"cases/{case_id}"], fold)
    fetch = latest_run(root, "S1", case_id, fold, components)
    if fetch is None:
        raise CaseError(f"no successful S1 run for {case_id} in fold {fold} with the current registry; "
                        "run `viveka corpus fetch` first")
    return (fetch, tables.read(root / fetch["params"]["tables"]["frames"]),
            tables.read(root / fetch["params"]["tables"]["works"]))


def _manual_refs(root: Path, manual: Path | None) -> dict[str, References]:
    if manual is None:
        return {}
    resolved = manual.resolve()
    if not resolved.is_relative_to((root / MANUAL_DIR).resolve()):
        raise ManualImportError(f"manual reference lists must be placed under {MANUAL_DIR}/")
    return load_manual(resolved)


def match_references(fetcher: Fetcher, case_id: str, work_id: str, references: References,
                     settings: CensusSettings) -> dict[int, bool | None]:
    """Match a work's sampled DOI-less references in OpenAlex; None marks one whose year, volume and page
    can't be read."""
    found: dict[int, bool | None] = {}
    for index in doiless_sample(case_id, work_id, references, settings.doiless_sample_per_work, settings.seed):
        biblio = biblio_of(references.entries[index])
        if biblio is None:
            found[index] = None
            continue
        response = fetcher.get(openalex.biblio_request(biblio.year, biblio.volume, biblio.first_page,
                                                       settings.match_year_tolerance))
        results = ((response.body or {}).get("results") or []) if response.status == 200 else []
        found[index] = match_found(biblio, [openalex.source_name(r) for r in results]) if results else False
    return found


def census_case(root: Path, case_id: str, fold: str, *, manual: Path | None = None,
                transport: httpx.BaseTransport | None = None, out: Out = print) -> str:
    case, _ = load_case(root, case_id)
    config = load_corpus_config(root)
    settings = config.census
    fetch, frames_rows, works_rows = _fetch_inputs(root, case_id, fold)
    by_frame, samples, kinds, undated = draw_sample(case, frames_rows, works_rows, settings.works_per_year,
                                                    settings.seed)
    manual_refs = _manual_refs(root, manual)
    with RunContext(root, "S2", case_id, fold, [f"cases/{case_id}"], seed=settings.seed,
                    params={"fetch_run": fetch["run_id"], "works_per_year": settings.works_per_year,
                            "max_unmeasured_share": settings.max_unmeasured_share,
                            "resolution": settings.resolution,
                            "doiless_sample_per_work": settings.doiless_sample_per_work,
                            "match_year_tolerance": settings.match_year_tolerance}) as ctx:
        ctx.record_input(root / fetch["params"]["tables"]["frames"])
        ctx.record_input(root / fetch["params"]["tables"]["works"])
        if manual is not None:
            ctx.record_input(manual.resolve())
        with make_fetcher(root, config, need=("openalex", "crossref"), transport=transport,
                          run_id=ctx.run_id) as fetcher:
            try:
                references: dict[str, References | None] = {}
                for work in (w for sample in samples.values() for w in sample):
                    if work.work_id in references:
                        continue
                    if work.work_id in manual_refs:
                        references[work.work_id] = manual_refs[work.work_id]
                    elif work.doi:
                        response = fetcher.get(crossref.work_request(work.doi))
                        references[work.work_id] = (crossref.references_of(response.body)
                                                    if response.status == 200 else None)
                    else:
                        references[work.work_id] = None
                reference_dois = [d for r in references.values() if r for d in r.dois if d]
                known = set(openalex.lookup_dois(fetcher, reference_dois, int(config.openalex["doi_batch"]),
                                                 fields=openalex.ID_FIELDS))
                matches = {work_id: match_references(fetcher, case_id, work_id, refs, settings)
                           for work_id, refs in sorted(references.items()) if refs is not None}
            finally:
                _finish(ctx, fetcher)
        coverage, sample_rows = [], []
        for frame_id in sorted(by_frame):
            outcomes = [outcome(w, references[w.work_id], known, matches.get(w.work_id)) for w in samples[frame_id]]
            coverage += coverage_rows(case_id, frame_id, kinds[frame_id], by_frame[frame_id], outcomes)
            sample_rows += [{"case_id": case_id, "frame_id": frame_id, "year": o.work.year, "work_id": o.work.work_id,
                             "status": o.status,
                             "reference_source": o.references.source if o.references else "none",
                             "refs": o.references.total if o.references else 0, "resolved": o.resolved,
                             "doiless": o.doiless, "doiless_sampled": o.doiless_sampled,
                             "doiless_matched": o.doiless_matched, "doiless_unparseable": o.doiless_unparseable}
                            for o in outcomes]
        written = {}
        for name, rows in (("coverage", coverage), ("census_sample", sample_rows)):
            written[name] = rel_posix(ctx.store(tables.to_parquet(name, rows), "parquet", rows=len(rows)), root)
        report = census_report(case, ctx.run_id, fetch["run_id"], config, coverage, undated)
        written["report"] = rel_posix(ctx.store(report.encode("utf-8"), "md"), root)
        ctx.params["tables"] = written
    out(report)
    out(_usage_line(ctx.usage))
    return ctx.run_id


def project_census(fetcher: Fetcher, config: CorpusConfig, samples: dict[str, list[FrameWork]],
                   manual_refs: dict[str, References]) -> Projection:
    projection = Projection()
    reference_dois: list[str] = []
    unarchived_works = 0
    per_work = config.census.doiless_sample_per_work
    match_calls = sum(min(per_work, len(r.doiless())) for r in manual_refs.values())
    seen: set[str] = set()
    for work in (w for sample in samples.values() for w in sample):
        if work.work_id in seen or work.work_id in manual_refs or not work.doi:
            seen.add(work.work_id)
            continue
        seen.add(work.work_id)
        hit = fetcher.archived(crossref.work_request(work.doi))
        if hit is None:
            projection.calls[("crossref", "free")] += 1
            unarchived_works += 1
            match_calls += per_work
        else:
            refs = crossref.references_of(hit.body) if hit.status == 200 else None
            reference_dois += [d for d in (refs.dois if refs else ()) if d]
            match_calls += min(per_work, len(refs.doiless())) if refs else 0
    reference_dois += [d for r in manual_refs.values() for d in r.dois if d]
    batch = int(config.openalex["doi_batch"])
    known_calls = math.ceil(len(set(reference_dois)) / batch)
    assumed_calls = math.ceil(unarchived_works * ASSUMED_REFS_PER_WORK / batch)
    projection.calls[("openalex", "list")] += known_calls + assumed_calls + match_calls  # matches: an upper bound
    if unarchived_works:
        projection.unknown.append(f"{unarchived_works} reference list(s) not archived yet; assumed "
                                  f"{ASSUMED_REFS_PER_WORK} references each (an estimate, not a bound)")
    return projection


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def census_report(case: Case, run_id: str, fetch_run: str, config: CorpusConfig, coverage: list[dict],
                  undated: int) -> str:
    settings = config.census
    whole = {s.frame_id: s for s in summarize(coverage, settings.max_unmeasured_share)}
    lines = [
        f"# Coverage census: {case.case_id}",
        "",
        f"Run `{run_id}` from corpus run `{fetch_run}`. Window {case.start}–{case.end}; up to "
        f"{settings.works_per_year} works sampled per frame and year (seed {settings.seed}). A reference with a DOI "
        f"resolves when the DOI is in OpenAlex; up to {settings.doiless_sample_per_work} references without a DOI "
        f"per work are matched by year (±{settings.match_year_tolerance}), volume and first page, and each "
        f"frame-year's matched share estimates the rest. A frame or year with more than "
        f"{settings.max_unmeasured_share:.0%} unmeasured works is not measurable.",
        "",
        "Coverage is not compared with *r* here: gate 1 applies *r* per sub-window at S4. DOI-less references "
        "with no readable volume and page (mostly books, theses, reports, preprints and proceedings) count as "
        "unmatched.",
        "",
        "| frame | kind | works | sampled | unmeasured | references | no DOI | DOI-less matched | no volume/page | "
        "coverage (est.) | measurable |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for frame in case.frames:
        s: Summary | None = whole.get(frame.frame_id)
        if s is None:
            lines.append(f"| {frame.frame_id} | {frame.kind} | 0 | 0 | – | 0 | – | – | – | n/a | no (no works) |")
            continue
        lines.append(f"| {s.frame_id} | {s.kind} | {s.frame_works} | {s.sampled} | {_pct(s.unmeasured_share)} | "
                     f"{s.refs} | {_pct(s.doiless / s.refs if s.refs else None)} | "
                     f"{s.doiless_matched}/{s.doiless_sampled} | {s.doiless_unparseable}/{s.doiless_sampled} | "
                     f"{_pct(s.coverage)} | {'yes' if s.measurable else 'no'} |")
    if undated:
        lines += ["", f"{undated} frame work(s) without a publication year were not sampled."]
    for frame in case.frames:
        rows = [r for r in coverage if r["frame_id"] == frame.frame_id]
        if not rows:
            continue
        lines += ["", f"## {frame.frame_id} by year", "",
                  "| year | works | sampled | unmeasured | references | no DOI | DOI-less matched | coverage (est.) | "
                  "measurable |",
                  "|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
        for row in rows:
            (s,) = summarize([row], settings.max_unmeasured_share)
            lines.append(f"| {row['year']} | {row['frame_works']} | {row['sampled']} | {_pct(s.unmeasured_share)} | "
                         f"{row['refs']} | {_pct(s.doiless / s.refs if s.refs else None)} | "
                         f"{s.doiless_matched}/{s.doiless_sampled} | {_pct(s.coverage)} | "
                         f"{'yes' if s.measurable else 'no'} |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- drafting aid


def resolve_lookup(root: Path, *, doi: str | None = None, openalex_id: str | None = None, title: str | None = None,
                   source_name: str | None = None, transport: httpx.BaseTransport | None = None,
                   out: Out = print) -> int:
    """Look up a work or venue for drafting a case. Not a run; spend still counts toward the daily cap."""
    config = load_corpus_config(root)
    if openalex_id:
        request = openalex.work_request(openalex_id)
    elif doi:
        request = openalex.doi_request(normalize_doi(doi) or doi)
    elif title:
        request = openalex.title_search_request(title)
    else:
        request = openalex.source_search_request(source_name or "")
    with make_fetcher(root, config, need=("openalex",), transport=transport) as fetcher:
        response = fetcher.get(request)
    if response.status != 200 or response.body is None:
        out(f"not found (HTTP {response.status})")
        return 1
    results = response.body.get("results") if "results" in response.body else [response.body]
    for obj in results or []:
        if request.url.endswith("/sources"):
            out(f"{short_id(obj.get('id'))}  {obj.get('display_name')}  issn_l={obj.get('issn_l')}  "
                f"type={obj.get('type')}  works={obj.get('works_count')}  host={obj.get('host_organization_name')}")
        else:
            row = openalex.work_row(obj)
            out(f"{row['work_id']}  doi={row['doi']}  {row['year']}  {row['title']}  "
                f"[{row['venue_name']}]  cited_by={row['cited_by_count']}")
    out(_usage_line(fetcher.usage.as_manifest()))
    return 0


# ---------------------------------------------------------------- CLI


def _usage_line(usage: dict) -> str:
    live = ", ".join(f"{s} {sum(k.values())}" for s, k in usage.get("live_calls", {}).items()) or "none"
    spend = usage.get("usd", {}).get("openalex", 0.0)
    replayed = sum(usage.get("replayed", {}).values())
    return f"live calls: {live}; replayed from archive: {replayed}; OpenAlex spend ${spend:.4f}"


def add_parsers(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    corpus = sub.add_parser("corpus", help="Corpus acquisition (S1) and the drafting lookup")
    csub = corpus.add_subparsers(dest="action", required=True)

    p = csub.add_parser("resolve", parents=[common], help="Look up a work or venue in OpenAlex (drafting aid)")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--doi")
    group.add_argument("--openalex", dest="openalex_id")
    group.add_argument("--title")
    group.add_argument("--source", dest="source_name", help="Search venues by name")

    for action, text in (("fetch", "S1: collect the case's works, authorships and citations"),
                         ("contexts", "S1: Semantic Scholar citation contexts for the bearing set")):
        p = csub.add_parser(action, parents=[common], help=text)
        p.add_argument("--case", required=True)
        p.add_argument("--fold", required=True, choices=FOLDS)
        p.add_argument("--dry-run", action="store_true", help="Project live calls from the archive; no network")
        if action == "fetch":
            p.add_argument("--probe", action="store_true",
                           help="Live: resolve registered works and first pages only, then project")

    case = sub.add_parser("case", help="Case definitions")
    casesub = case.add_subparsers(dest="action", required=True)
    p = casesub.add_parser("validate", parents=[common], help="Validate a case, its claim and the corpus settings")
    p.add_argument("case")

    p = sub.add_parser("census", parents=[common], help="S2: coverage census for a case")
    p.add_argument("--case", required=True)
    p.add_argument("--fold", required=True, choices=FOLDS)
    p.add_argument("--dry-run", action="store_true", help="Project live calls from the archive; no network")
    p.add_argument("--manual", type=Path, help=f"CSV of hand-entered reference lists under {MANUAL_DIR}/")


def _dry_run(root: Path, args: argparse.Namespace, out: Out) -> int:
    case, claim = load_case(root, args.case)
    config = load_corpus_config(root)
    with make_fetcher(root, config, offline=True) as fetcher:
        if args.command == "census":
            _, frames_rows, works_rows = _fetch_inputs(root, args.case, args.fold)
            _, samples, _, _ = draw_sample(case, frames_rows, works_rows, config.census.works_per_year,
                                           config.census.seed)
            projection = project_census(fetcher, config, samples, _manual_refs(root, args.manual))
            out(f"census dry run for {args.case}: {sum(len(s) for s in samples.values())} sampled works")
        else:
            projection = project_fetch(fetcher, config, case, claim)
            if args.action == "contexts":
                projection.unknown.append("Semantic Scholar pages: one per 1000 citations of each bearing work")
            out(f"{args.action} dry run for {args.case}:")
    out("\n".join(projection.lines(config)))
    return 0


def run(args: argparse.Namespace, root: Path, *, transport: httpx.BaseTransport | None = None,
        out: Out = print) -> int:
    try:
        if args.command == "case":
            case, claim = load_case(root, args.case)
            out(f"case {case.case_id} valid: claim {claim.claim_id} ({len(claim.events)} events), "
                f"{len(case.seeds)} seeds, frames {', '.join(f'{f.frame_id} ({f.kind})' for f in case.frames)}, "
                f"window {case.start}–{case.end}")
            return 0
        if args.command == "corpus" and args.action == "resolve":
            return resolve_lookup(root, doi=args.doi, openalex_id=args.openalex_id, title=args.title,
                                  source_name=args.source_name, transport=transport, out=out)
        if getattr(args, "probe", False):
            case, claim = load_case(root, args.case)
            config = load_corpus_config(root)
            with make_fetcher(root, config, need=("openalex",), transport=transport) as fetcher:
                probe(fetcher, config, case, claim)
            out(_usage_line(fetcher.usage.as_manifest()))
            return _dry_run(root, args, out)
        if args.dry_run:
            return _dry_run(root, args, out)
        if args.command == "census":
            census_case(root, args.case, args.fold, manual=args.manual, transport=transport, out=out)
        elif args.action == "fetch":
            fetch_case(root, args.case, args.fold, transport=transport, out=out)
        else:
            fetch_contexts(root, args.case, args.fold, transport=transport, out=out)
        return 0
    except (CaseError, FetchError, env.MissingCredential, ManualImportError) as exc:
        out(f"viveka: {exc}")
        return 1
