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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from viveka import env
from viveka.cases import Case, CaseError, Claim, WorkRef, bearing_set, load_commitment, load_subject
from viveka.census import (
    CatalogueEntry,
    FrameWork,
    References,
    Summary,
    biblio_of,
    catalogue_match,
    coverage_rows,
    doiless_sample,
    match_found,
    outcome,
    paper_doiless,
    rescue_match,
    rescue_query,
    sample_frame,
    summarize,
)
from viveka.corpus import crossref, ingest, openalex, semanticscholar, tables
from viveka.corpus.audit import AUDIT_DIR, AuditError, AuditResult, draw, read_audit, report_lines, sheets, works_sheet
from viveka.corpus.audit import write_once as write_sheet
from viveka.corpus.clusters import KIND as CLUSTER_KIND
from viveka.corpus.clusters import cluster_frames, needed_windows
from viveka.corpus.config import LIVE_SOURCES, CensusSettings, CorpusConfig, load_corpus_config
from viveka.corpus.http import REFUSED_STATUSES, Fetcher, FetchError, UsageMeter
from viveka.corpus.ids import chunks, normalize_doi, short_id
from viveka.corpus.manual import MANUAL_DIR, ManualImportError, load_manual
from viveka.corpus.overlap import community_authors, overlaps
from viveka.paths import REGISTRY, rel_posix
from viveka.provenance import FOLDS, RunContext, load_manifest, recent_runs
from viveka.registry.thresholds import load_thresholds
from viveka.registry.verify import require_frozen

Out = Callable[[str], None]
BEARING = "bearing"  # a commitment's frame of the results bearing on p (never censused)
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
    if config.ingestion is not None:
        rates.update({venue: config.ingestion.requests_per_second for venue in config.ingestion.venues})
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


def collect_corpus(fetcher: Fetcher, config: CorpusConfig, case: Case, claim: Claim | None,
                   commitments: Sequence[tuple[str, tuple[WorkRef, ...]]] = ()) -> dict[str, list[dict]]:
    """A subject's frames as rows. A calibration field also gets one `bearing` frame per commitment: the works
    citing that commitment's anchors, wherever they were published, which are the results bearing on p
    (`bearing_results_v2`). Those frames are not censused; S4 counts a lineage's citations against them."""
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
    listed: dict[str, list[dict]] = defaultdict(list)
    for frame in case.frames:
        values = seed_ids if frame.cites_seeds else list(frame.sources)
        filters = openalex.frame_filters(frame.cites_seeds, values, case.start, case.end) if values else []
        for flt in filters:
            for page in openalex.iter_pages(fetcher, flt, per_page):
                for obj in (page.body or {}).get("results") or []:
                    work_id = short_id(obj.get("id"))
                    works.setdefault(work_id, obj)
                    frame_rows.append({"case_id": case.case_id, "frame_id": frame.frame_id, "kind": frame.kind,
                                       "work_id": work_id, "year": obj.get("publication_year")})
        for venue_id in frame.ingest:
            venue = config.venue(venue_id)
            found = ingest.rows(ingest.list_works(fetcher, venue, case.start, case.end), venue)
            for name, found_rows in found.items():
                listed[name] += found_rows
            frame_rows += [{"case_id": case.case_id, "frame_id": frame.frame_id, "kind": frame.kind,
                            "work_id": row["work_id"], "year": row["year"]} for row in found["works"]]
    for commitment_id, anchors in commitments:
        found = resolve_refs(fetcher, config, anchors)
        unknown = [r.key for r in anchors if found[r] is None]
        if unknown:
            raise CaseError(f"commitment {commitment_id}: works not found in OpenAlex: {', '.join(unknown)}")
        for obj in found.values():
            if obj:
                works.setdefault(short_id(obj["id"]), obj)
        anchor_ids = [short_id(obj["id"]) for obj in found.values() if obj]
        for flt in openalex.frame_filters(True, anchor_ids, case.start, case.end):
            for page in openalex.iter_pages(fetcher, flt, per_page):
                for obj in (page.body or {}).get("results") or []:
                    work_id = short_id(obj.get("id"))
                    works.setdefault(work_id, obj)
                    frame_rows.append({"case_id": case.case_id, "frame_id": f"{BEARING}-{commitment_id}",
                                       "kind": BEARING, "work_id": work_id,
                                       "year": obj.get("publication_year")})
        frame_rows += [{"case_id": case.case_id, "frame_id": f"{BEARING}-{commitment_id}", "kind": BEARING,
                        "work_id": work_id, "year": works[work_id].get("publication_year")}
                       for work_id in anchor_ids]
    objs = list(works.values())
    return {
        "works": [openalex.work_row(o) for o in objs] + listed["works"],
        "authors": [row for o in objs for row in openalex.author_rows(o)] + listed["authors"],
        "authorships": [row for o in objs for row in openalex.authorship_rows(o)] + listed["authorships"],
        "citations": [row for o in objs for row in openalex.citation_rows(o)],
        "frames": frame_rows,
        "ingested": listed["ingested"],
    }


@dataclass
class Projection:
    calls: Counter = field(default_factory=Counter)  # (source, kind) -> live calls still needed
    unknown: list[str] = field(default_factory=list)

    def usd(self, config: CorpusConfig) -> float:
        return sum(n * config.price(source, kind) for (source, kind), n in self.calls.items())

    def lines(self, config: CorpusConfig) -> list[str]:
        calls = [f"  {source} {kind}: {n} live call(s)" for (source, kind), n in sorted(self.calls.items()) if n]
        if not calls and not self.unknown:
            return ["  nothing to fetch: every request is already archived"]
        return [*calls,
                f"  projected OpenAlex spend: ${self.usd(config):.4f} (cap ${config.openalex['daily_usd_cap']:.2f}"
                " per day, including other runs today)",
                *(f"  not projectable yet: {u}" for u in self.unknown)]


def project_fetch(fetcher: Fetcher, config: CorpusConfig, case: Case, claim: Claim,
                  commitments: Sequence[tuple[str, tuple[WorkRef, ...]]] = ()) -> Projection:
    """Live calls S1 still needs, read from the archive alone (the fetcher must be offline).

    A field's commitments each add a bearing frame (`bearing_results_v2`): the works citing that
    commitment's anchors, wherever published, which is often the largest frame S1 fetches.
    """
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
        for venue_id in frame.ingest:
            projection.unknown.append(f"frame {frame.frame_id}: ingested venue {venue_id} is listed from its archive "
                                      "(free; one request per year, issue or volume page not yet archived)")
        values = seed_ids if frame.cites_seeds else list(frame.sources)
        if not values:
            continue
        for flt in openalex.frame_filters(frame.cites_seeds, values, case.start, case.end):
            _project_pages(fetcher, projection, flt, per_page, f"frame {frame.frame_id}")
    for commitment_id, anchors in commitments:
        anchor_ids, resolved_all = _archived_ids(fetcher, config, anchors, projection)
        if not resolved_all:
            projection.unknown.append(f"bearing frame {commitment_id}: its anchors are not resolved yet "
                                      "(use --probe)")
            continue
        for flt in openalex.frame_filters(True, anchor_ids, case.start, case.end):
            _project_pages(fetcher, projection, flt, per_page, f"bearing frame {commitment_id}")
    return projection


def _project_pages(fetcher: Fetcher, projection: Projection, flt: str, per_page: int, label: str) -> None:
    """The list calls a frame's remaining pages still need, counted from the archive alone."""
    first = fetcher.archived(openalex.list_request(flt, "*", per_page))
    if first is None:
        projection.calls[("openalex", "list")] += 1
        projection.unknown.append(f"{label}: size unknown until its first page is probed")
        return
    pages = max(1, math.ceil(int(((first.body or {}).get("meta") or {}).get("count", 0)) / per_page))
    archived, page = 1, first
    while archived < pages:
        cursor = ((page.body or {}).get("meta") or {}).get("next_cursor")
        page = fetcher.archived(openalex.list_request(flt, cursor, per_page)) if cursor else None
        if page is None:
            break
        archived += 1
    projection.calls[("openalex", "list")] += pages - archived


def _archived_ids(fetcher: Fetcher, config: CorpusConfig, refs: Sequence[WorkRef],
                  projection: Projection) -> tuple[list[str], bool]:
    """The OpenAlex ids of registered works, read from the archive alone, and whether every one was there."""
    ids: list[str] = []
    complete = True
    for ref in refs:
        if not ref.openalex:
            continue
        hit = fetcher.archived(openalex.work_request(ref.openalex))
        if hit is None:
            projection.calls[("openalex", "singleton")] += 1
            complete = False
        elif hit.body:
            ids.append(short_id(hit.body["id"]))
    dois = sorted({r.doi for r in refs if not r.openalex and r.doi})
    batch = int(config.openalex["doi_batch"])
    for chunk in [dois[i : i + batch] for i in range(0, len(dois), batch)]:
        hit = fetcher.archived(openalex.doi_batch_request(chunk))
        if hit is None:
            projection.calls[("openalex", "list")] += 1
            complete = False
        else:
            ids += [short_id(o["id"]) for o in ((hit.body or {}).get("results") or []) if o.get("id")]
    return ids, complete


def probe(fetcher: Fetcher, config: CorpusConfig, case: Case, claim: Claim | None) -> None:
    """Live: resolve the registered works and fetch each frame's first page, so a dry run can project exactly."""
    resolved = resolve_refs(fetcher, config, bearing_set(case, claim))
    seed_ids = _seed_ids(case, resolved)
    for frame in case.frames:
        values = seed_ids if frame.cites_seeds else list(frame.sources)
        for flt in openalex.frame_filters(frame.cites_seeds, values, case.start, case.end) if values else []:
            fetcher.get(openalex.list_request(flt, "*", int(config.openalex["per_page"])))


def _anchors(root: Path, case: Case, commitment) -> tuple[WorkRef, ...]:
    """A commitment's seeds and its claim's event works: what results bearing on p are counted from."""
    from viveka.cases import load_claim

    claim = load_claim(root, commitment.claim)
    seen, refs = set(), []
    for ref in (*commitment.seeds, *(w for e in claim.events for w in e.works)):
        if ref.key not in seen:
            seen.add(ref.key)
            refs.append(ref)
    return tuple(refs)


def fetch_case(root: Path, case_id: str, fold: str, *, field: bool = False,
               transport: httpx.BaseTransport | None = None, out: Out = print) -> str:
    case, claim = load_subject(root, case_id, field)
    config = load_corpus_config(root)
    commitments = tuple((c.commitment_id, _anchors(root, case, c)) for c in case.commitments)
    params: dict = {"window": [case.start, case.end]}
    if commitments:
        params["bearing_frames"] = {cid: len(anchors) for cid, anchors in commitments}
    venues = sorted({v for f in case.frames for v in f.ingest})
    if venues:
        params["ingestion"] = {"venues": {v: config.venue(v).adapter for v in venues}}
    with RunContext(root, "S1", case_id, fold, [case.component], params=params) as ctx:
        with make_fetcher(root, config, need=("openalex",), transport=transport, run_id=ctx.run_id) as fetcher:
            try:
                rows = collect_corpus(fetcher, config, case, claim, commitments)
            finally:
                _finish(ctx, fetcher)
        written = {}
        for name in ("works", "authors", "authorships", "citations", "frames", *(("ingested",) if venues else ())):
            path = ctx.store(tables.to_parquet(name, rows[name]), "parquet", rows=len(rows[name]))
            written[name] = rel_posix(path, root)
        ctx.params["tables"] = written
    frame_sizes = Counter(frame for frame, _ in {(r["frame_id"], r["work_id"]) for r in rows["frames"]})
    out(f"run {ctx.run_id}: {len({r['work_id'] for r in rows['works']})} works; "
        + ", ".join([f"frame {f.frame_id}: {frame_sizes.get(f.frame_id, 0)}" for f in case.frames]
                    + [f"bearing {cid}: {frame_sizes.get(f'{BEARING}-{cid}', 0)}" for cid, _ in commitments]))
    out(_usage_line(ctx.usage))
    return ctx.run_id


# ---------------------------------------------------------------- S1: contexts


def fetch_contexts(root: Path, case_id: str, fold: str, *, field: bool = False, commitment: str | None = None,
                   transport: httpx.BaseTransport | None = None, out: Out = print) -> str:
    """Semantic Scholar's citation contexts for a case's bearing set, or for one commitment of a field.

    The run records, by decade of the citing paper, how many citations Semantic Scholar lists and how many
    of them carry at least one context (decision D-9: a citation without a context is unmeasured, and the
    share with one is reported before any coding).
    """
    if field:
        if not commitment:
            raise CaseError(f"field {case_id} has no bearing set: contexts are fetched per commitment; name one "
                            "with --commitment")
        case, claim = load_commitment(root, case_id, commitment)
    else:
        case, claim = load_subject(root, case_id, False)
    subject = f"{case_id}-{commitment}" if commitment else case_id
    config = load_corpus_config(root)
    s2 = config.semanticscholar
    with RunContext(root, "S1-contexts", subject, fold, [case.component]) as ctx:
        with make_fetcher(root, config, need=("openalex", "semanticscholar"), transport=transport,
                          run_id=ctx.run_id) as fetcher:
            try:
                resolved = resolve_refs(fetcher, config, bearing_set(case, claim))
                rows, truncated, without_doi = [], [], []
                listed: Counter = Counter()
                with_context: Counter = Counter()
                for obj in (o for o in resolved.values() if o):
                    work_id, doi = short_id(obj["id"]), normalize_doi(obj.get("doi"))
                    if not doi:
                        without_doi.append(work_id)
                        continue
                    items, cut = semanticscholar.iter_citations(fetcher, doi, int(s2["page_size"]),
                                                                int(s2["max_offset"]))
                    if cut:
                        truncated.append(work_id)
                    for item in items:
                        year = (item.get("citingPaper") or {}).get("year")
                        decade = f"{int(year) // 10 * 10}s" if isinstance(year, int) else "undated"
                        listed[decade] += 1
                        with_context[decade] += bool(item.get("contexts"))
                    rows += [row for item in items for row in semanticscholar.context_rows(work_id, item)]
            finally:
                _finish(ctx, fetcher)
        path = ctx.store(tables.to_parquet("contexts", rows), "parquet", rows=len(rows))
        ctx.params.update({"tables": {"contexts": rel_posix(path, root)}, "truncated": sorted(truncated),
                           "without_doi": sorted(without_doi), "commitment": commitment,
                           "citations_listed": sum(listed.values()),
                           "citations_with_context": sum(with_context.values()),
                           "by_decade": {d: [listed[d], with_context[d]] for d in sorted(listed)},
                           "semanticscholar_key": env.get(env.S2_API_KEY) is not None})
    total, have = sum(listed.values()), sum(with_context.values())
    out(f"citations listed by Semantic Scholar: {total}; with at least one context: {have}"
        + (f" ({have / total:.1%})" if total else ""))
    for decade in sorted(listed):
        out(f"  {decade}: {with_context[decade]} of {listed[decade]}"
            + (f" ({with_context[decade] / listed[decade]:.1%})" if listed[decade] else ""))
    out(f"run {ctx.run_id}: {len(rows)} citation contexts"
        + (f"; truncated at the offset limit for {', '.join(truncated)}" if truncated else "")
        + (f"; no DOI for {', '.join(without_doi)}" if without_doi else ""))
    out(_usage_line(ctx.usage))
    return ctx.run_id


MEMBER_WINDOWS_PER_SCIENCE = 3  # decision D-28
MEMBER_WINDOWS_SEED = 20261007  # decision D-28


def coding_scope(root: Path, field_id: str, commitment: str, fold: str) -> tuple[dict, dict, list, list[dict]]:
    """The citations D-28 codes for one commitment: (S4 run, fetch run, chosen windows, scope rows), from the
    newest successful S4 run under the current registry, its fetch and its social layer."""
    from viveka.social.commands import _own_works
    from viveka.social.eligibility import bearing_results, lineage_works
    from viveka.social.graph import node_keys
    from viveka.social.scope import coding_windows, eligible_windows, window_citations

    case, claim = load_commitment(root, field_id, commitment)
    subject = f"{field_id}-{commitment}"
    s4 = latest_run(root, "S4", subject, fold, require_frozen(root, [case.component, "thresholds"], fold))
    if s4 is None:
        raise CaseError(f"no successful S4 run for {subject} in fold {fold} with the current registry; run "
                        "`viveka eligibility` first")
    fetch, s3 = load_manifest(root, s4["params"]["fetch_run"]), load_manifest(root, s4["params"]["s3_run"])
    read = {name: tables.read(root / fetch["params"]["tables"][name])
            for name in ("works", "authors", "authorships", "citations", "frames")}
    resolution = float(s4["params"]["primary_resolution"])
    eligible = eligible_windows(tables.read(root / s4["params"]["tables"]["eligibility"]), resolution)
    windows = coding_windows(eligible, case.pair, subject, per_science=MEMBER_WINDOWS_PER_SCIENCE,
                             seed=MEMBER_WINDOWS_SEED)
    keys = node_keys(read["authors"], s3["params"]["nodes"] == "name")
    years, authors = lineage_works(s4["params"]["lineage_works"],
                                   ((r["work_id"], r["year"]) for r in read["works"]),
                                   ((r["work_id"], r["author_id"]) for r in read["authorships"]), keys,
                                   _own_works(read["frames"]))
    citations = [(r["citing_work"], r["cited_work"]) for r in read["citations"]]
    anchors = {ref.openalex for ref in bearing_set(case, claim) if ref.openalex}
    frame_works = {r["work_id"] for r in read["frames"]
                   if r["kind"] == BEARING and r["frame_id"] == f"{BEARING}-{commitment}"}
    bearing = bearing_results(anchors | frame_works, citations)
    members: dict[tuple[float, int, int], set[str]] = {}
    for r in tables.read(root / s3["params"]["tables"]["clusters"]):
        members.setdefault((r["resolution"], r["window_start"], r["cluster"]), set()).add(r["author"])
    rows = window_citations(windows, tables.read(root / s3["params"]["tables"]["lineages"]), members, resolution,
                            years, authors, citations, bearing)
    return s4, fetch, windows, rows


def fetch_member_contexts(root: Path, field_id: str, commitment: str, fold: str, *,
                          transport: httpx.BaseTransport | None = None, out: Out = print) -> str:
    """Semantic Scholar's contexts for the citations D-28 codes: for each citing paper of the scope, its
    references with contexts, kept where the cited paper is a bearing result it cites in the corpus.

    A citation is unmeasured when its citing paper has no DOI, Semantic Scholar does not know the paper, the
    cited result has no DOI to match, or Semantic Scholar gives the reference no context; each is counted."""
    from viveka.social.scope import WINDOWS_RULE

    case, _ = load_commitment(root, field_id, commitment)
    config = load_corpus_config(root)
    s2 = config.semanticscholar
    s4, fetch, windows, scope = coding_scope(root, field_id, commitment, fold)
    works = {r["work_id"]: r for r in tables.read(root / fetch["params"]["tables"]["works"])}
    doi_of = {w: normalize_doi(r["doi"]) for w, r in works.items() if r["doi"]}
    work_of_doi = {doi: w for w, doi in doi_of.items() if doi}
    wanted: dict[str, set[str]] = defaultdict(set)
    for r in scope:
        wanted[r["citing_work"]].add(r["cited_work"])
    pairs = {(c, d) for c, ds in wanted.items() for d in ds}
    subject = f"{field_id}-{commitment}"
    params = {"commitment": commitment, "s4_run": s4["run_id"], "fetch_run": fetch["run_id"],
              "windows_rule": WINDOWS_RULE, "windows_per_science": MEMBER_WINDOWS_PER_SCIENCE,
              "windows_seed": MEMBER_WINDOWS_SEED, "side": case.pair,
              "windows": [list(w) for w in windows], "scope_citations": len(pairs),
              "scope_results": len({d for _, d in pairs}), "citing_works": len(wanted)}
    with RunContext(root, "S1-member-contexts", subject, fold, [case.component, "thresholds"], params=params) as ctx:
        for name in ("works", "citations", "authorships"):
            ctx.record_input(root / fetch["params"]["tables"][name])
        ctx.record_input(root / s4["params"]["tables"]["eligibility"])
        with make_fetcher(root, config, need=("semanticscholar",), transport=transport,
                          run_id=ctx.run_id) as fetcher:
            try:
                rows, truncated, without_doi, unknown = [], [], [], []
                for citing in sorted(wanted):
                    doi = doi_of.get(citing)
                    if not doi:
                        without_doi.append(citing)
                        continue
                    items, cut = semanticscholar.iter_references(fetcher, doi, int(s2["page_size"]),
                                                                 int(s2["max_offset"]))
                    if cut:
                        truncated.append(citing)
                    if not items:
                        unknown.append(citing)
                    for item in items:
                        cited_doi = normalize_doi(((item.get("citedPaper") or {}).get("externalIds") or {}).get("DOI"))
                        cited = work_of_doi.get(cited_doi) if cited_doi else None
                        if cited in wanted[citing]:
                            rows += [dict(r, citing_work=citing)
                                     for r in semanticscholar.reference_rows(doi, None, cited, item)]
            finally:
                _finish(ctx, fetcher)
        with_context = {(r["citing_work"], r["cited_work"]) for r in rows}
        scope_path = ctx.store(tables.to_parquet("scope", scope), "parquet", rows=len(scope))
        path = ctx.store(tables.to_parquet("member_contexts", rows), "parquet", rows=len(rows))
        no_doi_cited = {(c, d) for c, d in pairs if not doi_of.get(d)}
        ctx.params.update({"tables": {"scope": rel_posix(scope_path, root), "member_contexts": rel_posix(path, root)},
                           "citing_without_doi": len(without_doi), "citing_unknown_to_s2": len(unknown),
                           "truncated": sorted(truncated), "cited_without_doi": len(no_doi_cited),
                           "citations_with_context": len(with_context),
                           "results_with_context": len({d for _, d in with_context}),
                           "semanticscholar_key": env.get(env.S2_API_KEY) is not None})
    share = len(with_context) / len(pairs) if pairs else 0.0
    out(f"{subject}: {len(windows)} lineage-window(s), {len(pairs)} citations of {params['scope_results']} bearing "
        f"results from {len(wanted)} citing papers; with a context: {len(with_context)} ({share:.1%}); citing "
        f"papers without DOI {len(without_doi)}, unknown to Semantic Scholar {len(unknown)}")
    out(f"run {ctx.run_id}: {len(rows)} contexts")
    out(_usage_line(ctx.usage))
    return ctx.run_id


def abstract_text(inverted: Mapping[str, Sequence[int]] | None) -> str | None:
    """An abstract from OpenAlex's inverted index (word -> positions), or None when there is none."""
    if not inverted:
        return None
    placed = sorted((position, word) for word, positions in inverted.items() for position in positions)
    text = " ".join(word for _, word in placed).strip()
    return text or None


def latest_member_contexts(root: Path, field_id: str, commitment: str, fold: str) -> dict:
    case, _ = load_commitment(root, field_id, commitment)
    run = latest_run(root, "S1-member-contexts", f"{field_id}-{commitment}", fold,
                     require_frozen(root, [case.component, "thresholds"], fold))
    if run is None:
        raise CaseError(f"no successful member-contexts run for {field_id}-{commitment} in fold {fold} with the "
                        "current registry; run `viveka corpus member-contexts` first")
    return run


def fetch_abstracts(root: Path, field_id: str, commitment: str, fold: str, *,
                    transport: httpx.BaseTransport | None = None, out: Out = print) -> str:
    """OpenAlex abstracts of the bearing results that have at least one member context (the items of the
    direction task, D-28). A result without an abstract is unmeasured for direction and counted."""
    case, _ = load_commitment(root, field_id, commitment)
    config = load_corpus_config(root)
    contexts_run = latest_member_contexts(root, field_id, commitment, fold)
    contexts = tables.read(root / contexts_run["params"]["tables"]["member_contexts"])
    results = sorted({r["cited_work"] for r in contexts})
    params = {"commitment": commitment, "member_contexts_run": contexts_run["run_id"], "results": len(results)}
    with RunContext(root, "S1-abstracts", f"{field_id}-{commitment}", fold, [case.component, "thresholds"],
                    params=params) as ctx:
        ctx.record_input(root / contexts_run["params"]["tables"]["member_contexts"])
        found: dict[str, str | None] = {}
        with make_fetcher(root, config, need=("openalex",), transport=transport, run_id=ctx.run_id) as fetcher:
            try:
                for chunk in chunks(results, openalex.OR_LIMIT):
                    response = fetcher.get(openalex.id_batch_request(chunk, ("id", "abstract_inverted_index")))
                    if response.status != 200 or response.body is None:
                        raise FetchError(f"openalex abstracts: HTTP {response.status}")
                    for obj in response.body.get("results") or []:
                        found[short_id(obj["id"])] = abstract_text(obj.get("abstract_inverted_index"))
            finally:
                _finish(ctx, fetcher)
        rows = [{"work_id": w, "abstract": found.get(w), "source": openalex.SOURCE} for w in results]
        path = ctx.store(tables.to_parquet("abstracts", rows), "parquet", rows=len(rows))
        with_abstract = sum(r["abstract"] is not None for r in rows)
        ctx.params.update({"tables": {"abstracts": rel_posix(path, root)}, "with_abstract": with_abstract,
                           "not_returned": sum(w not in found for w in results)})
    out(f"{field_id}-{commitment}: {len(results)} results with a member context; with an abstract: {with_abstract}"
        + (f" ({with_abstract / len(results):.1%})" if results else ""))
    out(f"run {ctx.run_id}")
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


SOCIAL_TABLES = ("works", "authors", "authorships", "citations", "frames")
# Components S3 reads only through the settings below (or not at all): a change elsewhere in them, such as m, v
# or a census convention, leaves the social layer what it was.
SOCIAL_BY_SETTINGS = frozenset({"schemas", "corpus", "simulation", "thresholds"})


def social_settings(config: CorpusConfig, thresholds: Mapping) -> dict:
    """Every registered value S3 computes from, as its manifest records them."""
    if config.social is None:
        raise CaseError("corpus.yaml registers no social settings")
    return {"graph": config.social.graph, "w": int(thresholds["w_window_years"]),
            "o": float(thresholds["o_min_overlap"]),
            "resolutions": [float(r) for r in thresholds["sweep"]["resolutions"]],
            "leiden_seed": config.social.leiden_seed, "lineage_min_members": config.social.lineage_min_members}


def reusable_social_run(root: Path, case_id: str, fold: str, components: dict[str, str], fetch: dict,
                        settings: Mapping) -> dict | None:
    """The newest successful S3 run that the current registry and fetch would reproduce (decision D-19).

    S3 takes days on the large fields, and an edit to corpus.yaml or thresholds.yaml that it never reads used to
    make every social layer stale. A run stands when it was built from the same subject and claims (every
    component outside `SOCIAL_BY_SETTINGS` has the hash it has now), under the same S3 settings, from exactly
    the tables of the current fetch (content-addressed, so an identical replay of S1 gives the same paths).
    """
    tables_now = {fetch["params"]["tables"][name] for name in SOCIAL_TABLES}
    own = {name: value for name, value in components.items() if name not in SOCIAL_BY_SETTINGS}
    for manifest in recent_runs(root, limit=10_000):
        if not (manifest.get("stage") == "S3" and manifest.get("case") == case_id and manifest.get("fold") == fold
                and manifest.get("status") == "ok"):
            continue
        built = manifest["registry"]["components"]
        params = manifest.get("params") or {}
        if (set(built) == set(components) and all(built[name] == value for name, value in own.items())
                and all(params.get(key) == value for key, value in settings.items())
                and {item["path"] for item in manifest.get("inputs") or []} == tables_now):
            return manifest
    return None


@dataclass
class Draw:
    by_frame: dict[str, list[FrameWork]]  # each frame's papers
    samples: dict[str, list[FrameWork]]
    excluded: dict[str, Counter]  # frame -> year -> works that are not papers
    kinds: dict[str, str]
    undated: int


def draw_sample(case: Case, frames_rows: list[dict], works_rows: list[dict], per_year: int, seed: int,
                paper_types: frozenset[str], kinds: dict[str, str] | None = None) -> Draw:
    works = {w["work_id"]: w for w in works_rows}
    by_frame: dict[str, list[FrameWork]] = defaultdict(list)
    excluded: dict[str, Counter] = defaultdict(Counter)
    undated = 0
    for row in frames_rows:
        if row["kind"] == BEARING:
            continue
        if row["year"] is None:
            undated += 1
            continue
        work = works.get(row["work_id"]) or {}
        if work.get("type") not in paper_types:
            excluded[row["frame_id"]][int(row["year"])] += 1
            continue
        by_frame[row["frame_id"]].append(FrameWork(row["work_id"], int(row["year"]), work.get("doi")))
    samples = {fid: sample_frame(case.case_id, fid, papers, per_year, seed) for fid, papers in by_frame.items()}
    return Draw(dict(by_frame), samples, dict(excluded),
                kinds if kinds is not None else {f.frame_id: f.kind for f in case.frames}, undated)


def _fetch_inputs(root: Path, case: Case, fold: str) -> tuple[dict, list[dict], list[dict]]:
    components = require_frozen(root, [case.component], fold)
    fetch = latest_run(root, "S1", case.case_id, fold, components)
    if fetch is None:
        raise CaseError(f"no successful S1 run for {case.case_id} in fold {fold} with the current registry; "
                        "run `viveka corpus fetch` first")
    return (fetch, tables.read(root / fetch["params"]["tables"]["frames"]),
            tables.read(root / fetch["params"]["tables"]["works"]))


def _listing(root: Path, fetch: dict) -> dict[str, dict]:
    """The ingested venues' listed papers from an S1 run, by work id (empty when no venue was ingested)."""
    path = fetch["params"]["tables"].get("ingested")
    return {row["work_id"]: row for row in tables.read(root / path)} if path else {}


def _catalogue(config: CorpusConfig, listing: dict[str, dict], works_rows: list[dict]) -> list[CatalogueEntry]:
    papers = {w["work_id"]: w for w in works_rows if w.get("type") in config.census.paper_types}
    return [CatalogueEntry(config.venue(row["venue"]).aliases, papers[work_id]["year"], row["volume"],
                           row["first_page"], row["first_author"])
            for work_id, row in sorted(listing.items()) if work_id in papers]


def _audit(root: Path, audit: Path | None, sampled: set[str]) -> AuditResult | None:
    if audit is None:
        return None
    resolved = audit.resolve()
    if not resolved.is_relative_to((root / AUDIT_DIR).resolve()):
        raise AuditError(f"audit sheets must be placed under {AUDIT_DIR}/")
    return read_audit(resolved, sampled)


def audit_sheets(root: Path, subject_id: str, fold: str, *, field: bool = False, out: Out = print) -> Path:
    """Write the audit sheets for the latest census of a subject's ingested venues (no network)."""
    case, _ = load_subject(root, subject_id, field)
    config = load_corpus_config(root)
    if config.ingestion is None:
        raise CaseError("corpus.yaml registers no ingestion settings")
    components = require_frozen(root, [case.component], fold)
    census = latest_run(root, "S2", subject_id, fold, components)
    if census is None:
        raise CaseError(f"no successful census of {subject_id} in fold {fold} with the current registry")
    fetch = next((m for m in recent_runs(root, limit=10_000) if m["run_id"] == census["params"]["fetch_run"]), None)
    listing = _listing(root, fetch) if fetch else {}
    sample = tables.read(root / census["params"]["tables"]["census_sample"])
    works = sorted({r["work_id"] for r in sample if r["reference_source"] == "ingested"})
    if not works:
        raise CaseError(f"census {census['run_id']} measured no paper from an ingested venue")
    references = {}
    with make_fetcher(root, config, offline=True) as fetcher:
        for work_id in works:
            refs = ingest.references(fetcher, listing[work_id]["venue"], listing[work_id]["document_url"])
            if refs is not None:
                references[work_id] = refs
    chosen = draw(census["run_id"], references, config.ingestion.audit_references, config.census.seed)
    reference_sheet, work_sheet = sheets(chosen, references, {w: listing[w]["document_url"] for w in works})
    path = root / AUDIT_DIR / f"{subject_id}-{census['run_id']}-references.csv"
    write_sheet(works_sheet(path), work_sheet)
    write_sheet(path, reference_sheet)
    out(f"audit sheets for census {census['run_id']}: {len(chosen)} references from "
        f"{len({w for w, _ in chosen})} papers in {rel_posix(path, root)} and {works_sheet(path).name}; fill in "
        f"verdict and document_count, then run the census again with --audit {rel_posix(path, root)}")
    return path


def _manual_refs(root: Path, manual: Path | None) -> dict[str, References]:
    if manual is None:
        return {}
    resolved = manual.resolve()
    if not resolved.is_relative_to((root / MANUAL_DIR).resolve()):
        raise ManualImportError(f"manual reference lists must be placed under {MANUAL_DIR}/")
    return load_manual(resolved)


def match_references(fetcher: Fetcher, case_id: str, work_id: str, references: References,
                     settings: CensusSettings, catalogue: Sequence[CatalogueEntry] = ()
                     ) -> tuple[dict[int, bool | None], dict[int, str]]:
    """Match a work's sampled DOI-less paper references: first against the ingested venues' listings, then in
    OpenAlex by year, volume and page.

    Returns each sampled reference's result (None: no readable volume and page) and, for those not matched,
    the DOI a Crossref bibliographic query recovered, still to be confirmed as a paper in OpenAlex.
    """
    found: dict[int, bool | None] = {}
    rescued: dict[int, str] = {}
    pool = paper_doiless(references)
    for index in doiless_sample(case_id, work_id, pool, settings.doiless_sample_per_work, settings.seed):
        entry = references.entries[index]
        if catalogue and catalogue_match(entry, catalogue, settings.match_year_tolerance):
            found[index] = True
            continue
        biblio = biblio_of(entry)
        if biblio is None:
            found[index] = None
        else:
            response = fetcher.get(openalex.biblio_request(biblio.year, biblio.volume, biblio.first_page,
                                                           settings.match_year_tolerance))
            results = ((response.body or {}).get("results") or []) if response.status == 200 else []
            found[index] = match_found(biblio, [openalex.source_name(r) for r in results]) if results else False
        query = rescue_query(entry) if found[index] is not True else None
        if query is None:
            continue
        response = fetcher.get(crossref.bibliographic_request(query))
        if response.status == 200:
            doi = rescue_match(entry, crossref.candidates_of(response.body), settings.rescue_min_score,
                               settings.rescue_title_share, settings.match_year_tolerance)
            if doi:
                rescued[index] = doi
    return found, rescued


def census_case(root: Path, case_id: str, fold: str, *, field: bool = False, manual: Path | None = None,
                audit: Path | None = None, transport: httpx.BaseTransport | None = None, out: Out = print) -> str:
    case, _ = load_subject(root, case_id, field)
    config = load_corpus_config(root)
    settings = config.census
    fetch, frames_rows, works_rows = _fetch_inputs(root, case, fold)
    draw = draw_sample(case, frames_rows, works_rows, settings.works_per_year, settings.seed, settings.paper_types)
    samples = draw.samples
    manual_refs = _manual_refs(root, manual)
    audit_result = _audit(root, audit, {w.work_id for sample in samples.values() for w in sample})
    listing = _listing(root, fetch)
    catalogue = _catalogue(config, listing, works_rows)
    extra = {"ingestion": {"text_extraction": config.ingestion.text_extraction,
                           "reference_extraction": config.ingestion.reference_extraction,
                           "catalogue_match": config.ingestion.catalogue_match}} if listing and config.ingestion else {}
    with RunContext(root, "S2", case_id, fold, [case.component], seed=settings.seed,
                    params={**extra, "fetch_run": fetch["run_id"], "works_per_year": settings.works_per_year,
                            "max_unmeasured_share": settings.max_unmeasured_share,
                            "resolution": settings.resolution,
                            "doiless_sample_per_work": settings.doiless_sample_per_work,
                            "match_year_tolerance": settings.match_year_tolerance,
                            "paper_types": sorted(settings.paper_types),
                            "reference_classification": settings.reference_classification}) as ctx:
        ctx.record_input(root / fetch["params"]["tables"]["frames"])
        ctx.record_input(root / fetch["params"]["tables"]["works"])
        if listing:
            ctx.record_input(root / fetch["params"]["tables"]["ingested"])
        if audit is not None:
            ctx.record_input(audit.resolve())
            ctx.record_input(works_sheet(audit.resolve()))
        if manual is not None:
            ctx.record_input(manual.resolve())
        references, refused, doi_types, matches, rescued = _measure(
            ctx, root, config, settings, case_id, samples, manual_refs, listing, catalogue, transport)
        coverage, sample_rows = _census_rows(case_id, draw, samples, references, doi_types, matches, rescued,
                                             settings)
        written = {}
        for name, rows in (("coverage", coverage), ("census_sample", sample_rows)):
            written[name] = rel_posix(ctx.store(tables.to_parquet(name, rows), "parquet", rows=len(rows)), root)
        report = census_report(case, ctx.run_id, fetch["run_id"], config, coverage, draw.undated, bool(listing),
                               audit_result, rel_posix(audit.resolve(), root) if audit is not None else None,
                               refused)
        written["report"] = rel_posix(ctx.store(report.encode("utf-8"), "md"), root)
        ctx.params["tables"] = written
    out(report)
    out(_usage_line(ctx.usage))
    return ctx.run_id


def _measure(ctx: RunContext, root: Path, config: CorpusConfig, settings: CensusSettings, case_id: str,
             samples: dict[str, list[FrameWork]], manual_refs: dict[str, References], listing: dict[str, dict],
             catalogue: Sequence[CatalogueEntry], transport: httpx.BaseTransport | None
             ) -> tuple[dict[str, References | None], dict[str, int], dict[str, str | None],
                        dict[str, dict[int, bool | None]], dict[str, dict[int, str]]]:
    """Every sampled paper's reference list, and which of its sampled DOI-less references the corpus holds."""
    with make_fetcher(root, config, need=("openalex", "crossref"), transport=transport,
                      run_id=ctx.run_id) as fetcher:
        try:
            references: dict[str, References | None] = {}
            refused: dict[str, int] = {}
            for work in (w for sample in samples.values() for w in sample):
                if work.work_id in references:
                    continue
                if work.work_id in manual_refs:
                    references[work.work_id] = manual_refs[work.work_id]
                elif ingest.is_ingested(work.work_id):
                    row = listing.get(work.work_id) or {}
                    venue = row.get("venue") or ""
                    references[work.work_id], status = ingest.document_references(fetcher, venue,
                                                                                  row.get("document_url"))
                    if status in REFUSED_STATUSES:
                        refused[venue] = refused.get(venue, 0) + 1
                elif work.doi:
                    response = fetcher.get(crossref.work_request(work.doi))
                    references[work.work_id] = (crossref.references_of(response.body)
                                                if response.status == 200 else None)
                else:
                    references[work.work_id] = None
            reference_dois = [d for r in references.values() if r for d in r.dois if d]
            found = openalex.lookup_dois(fetcher, reference_dois, int(config.openalex["doi_batch"]),
                                         fields=(*openalex.ID_FIELDS, "type"))
            doi_types = {doi: obj.get("type") for doi, obj in found.items()}
            matches: dict[str, dict[int, bool | None]] = {}
            rescued: dict[str, dict[int, str]] = {}
            for work_id, refs in sorted(references.items()):
                if refs is not None:
                    matches[work_id], rescued[work_id] = match_references(fetcher, case_id, work_id, refs,
                                                                          settings, catalogue)
            rescued_dois = sorted({doi for by_index in rescued.values() for doi in by_index.values()})
            confirmed = openalex.lookup_dois(fetcher, rescued_dois, int(config.openalex["doi_batch"]),
                                             fields=(*openalex.ID_FIELDS, "type"))
            for work_id, by_index in rescued.items():
                for index, doi in by_index.items():
                    if (confirmed.get(doi) or {}).get("type") in settings.paper_types:
                        matches[work_id][index] = True
        finally:
            _finish(ctx, fetcher)
    return references, refused, doi_types, matches, rescued


def _census_rows(case_id: str, draw: Draw, samples: dict[str, list[FrameWork]],
                 references: dict[str, References | None], doi_types: dict[str, str | None],
                 matches: dict[str, dict[int, bool | None]], rescued: dict[str, dict[int, str]],
                 settings: CensusSettings) -> tuple[list[dict], list[dict]]:
    """The coverage rows (per frame and year) and the sampled-work rows of a census."""
    coverage, sample_rows = [], []
    for frame_id in sorted(set(draw.by_frame) | set(draw.excluded)):
        outcomes = [outcome(w, references[w.work_id], doi_types, settings.paper_types, matches.get(w.work_id),
                            rescued.get(w.work_id, {}))
                    for w in samples.get(frame_id, [])]
        coverage += coverage_rows(case_id, frame_id, draw.kinds[frame_id], draw.by_frame.get(frame_id, []),
                                  outcomes, draw.excluded.get(frame_id))
        sample_rows += [{"case_id": case_id, "frame_id": frame_id, "year": o.work.year, "work_id": o.work.work_id,
                         "status": o.status,
                         "reference_source": o.references.source if o.references else "none",
                         "refs": o.refs, "resolved": o.resolved, "refs_excluded": o.refs_excluded,
                         "refs_unclassifiable": o.refs_unclassifiable,
                         "doiless": o.doiless, "doiless_sampled": o.doiless_sampled,
                         "doiless_matched": o.doiless_matched, "doiless_rescued": o.doiless_rescued,
                         "doiless_unparseable": o.doiless_unparseable}
                        for o in outcomes]
    return coverage, sample_rows


# ---------------------------------------------------------------- S2C: the census with cluster frames


def _eligibility_runs(root: Path, fold: str, s3_run: str) -> dict[str, dict]:
    """The newest successful S4 run per commitment from one social-layer run."""
    found: dict[str, dict] = {}
    for manifest in recent_runs(root, limit=10_000):
        params = manifest.get("params") or {}
        if (manifest.get("stage") == "S4" and manifest.get("status") == "ok" and manifest.get("fold") == fold
                and params.get("s3_run") == s3_run):
            found.setdefault(params.get("commitment") or manifest["case"], manifest)
    return found


def _cluster_inputs(root: Path, s3: dict, fetch: dict, resolution: float, rule: str
                    ) -> tuple[dict[tuple[str, int], frozenset[str]], dict[str, list[str]], dict[str, int | None]]:
    """Each lineage-window's cluster members, every author's works, and publication years, as S4 reads them
    under the registered `lineage_works` rule."""
    from viveka.social.eligibility import lineage_works
    from viveka.social.graph import node_keys

    read = {name: tables.read(root / fetch["params"]["tables"][name])
            for name in ("works", "authors", "authorships", "frames")}
    own = {row["work_id"] for row in read["frames"] if row["kind"] != BEARING}
    keys = node_keys(read["authors"], s3["params"]["nodes"] == "name")
    years, authors = lineage_works(rule, ((row["work_id"], row["year"]) for row in read["works"]),
                                   ((row["work_id"], row["author_id"]) for row in read["authorships"]), keys, own)
    works_by_author: dict[str, list[str]] = defaultdict(list)
    for work, team in authors.items():
        for key in team:
            works_by_author[key].append(work)
    in_cluster: dict[tuple[int, int], set[str]] = defaultdict(set)
    for row in tables.read(root / s3["params"]["tables"]["clusters"]):
        if abs(row["resolution"] - resolution) < 1e-9:
            in_cluster[(row["window_start"], row["cluster"])].add(row["author"])
    members = {(row["lineage_id"], row["window_start"]):
               frozenset(in_cluster.get((row["window_start"], row["cluster"]), set()))
               for row in tables.read(root / s3["params"]["tables"]["lineages"])
               if abs(row["resolution"] - resolution) < 1e-9}
    return members, dict(works_by_author), years


@dataclass
class ClusterDraw:
    case: Case
    fetch: dict
    s3: dict
    draw: Draw
    frames: list[dict]
    resolution: float
    per_commitment: dict[str, int]
    s4_runs: dict[str, str]


def cluster_draw(root: Path, subject_id: str, fold: str, *, field: bool = False,
                 resolution: float | None = None) -> ClusterDraw:
    """The cluster frames of a subject and the sample drawn from them; no network, nothing written."""
    case, _ = load_subject(root, subject_id, field)
    config = load_corpus_config(root)
    settings = config.census
    if config.social is None:
        raise CaseError("corpus.yaml registers no social settings")
    chosen = float(config.social.primary_resolution if resolution is None else resolution)
    fetch, _, works_rows = _fetch_inputs(root, case, fold)
    s3 = reusable_social_run(root, subject_id, fold, require_frozen(root, [case.component, "thresholds"], fold),
                             fetch, social_settings(config, load_thresholds(root)))
    if s3 is None:
        raise CaseError(f"no successful S3 run for {subject_id} in fold {fold} that the current registry and "
                        "fetch would reproduce; run `viveka social build` first")
    eligibility = _eligibility_runs(root, fold, s3["run_id"])
    if not eligibility:
        raise CaseError(f"no successful S4 run from social-layer run {s3['run_id']}; "
                        "run `viveka eligibility` first: the cluster frames are the windows it passes")
    rule = config.social.lineage_works
    stale = sorted(name for name, manifest in eligibility.items()
                   if manifest["params"].get("lineage_works", "own_frames_v1") != rule)
    if stale:
        raise CaseError(f"the latest S4 run of {', '.join(stale)} counted a lineage's papers under another "
                        f"lineage_works rule than the registered {rule}; rerun `viveka eligibility` first")
    ends: dict[tuple[str, int], int] = {}
    per_commitment: dict[str, int] = {}
    for name, manifest in sorted(eligibility.items()):
        windows = needed_windows(tables.read(root / manifest["params"]["tables"]["eligibility"]), chosen)
        per_commitment[name] = len(windows)
        for lineage_id, start, end in windows:
            ends[(lineage_id, start)] = end
    needed = sorted((lineage_id, start, end) for (lineage_id, start), end in ends.items())
    if not needed:
        raise CaseError(f"no lineage-window of {subject_id} meets m and v at resolution {chosen:g}; coverage can "
                        "withhold eligibility but never grant it, so there is nothing to census")
    members, works_by_author, years = _cluster_inputs(root, s3, fetch, chosen, rule)
    frames = cluster_frames(subject_id, needed, members, works_by_author, years)
    draw = draw_sample(case, frames, works_rows, settings.works_per_year, settings.seed, settings.paper_types,
                       {row["frame_id"]: CLUSTER_KIND for row in frames})
    return ClusterDraw(case, fetch, s3, draw, frames, chosen, per_commitment,
                       {name: m["run_id"] for name, m in sorted(eligibility.items())})


def census_clusters(root: Path, subject_id: str, fold: str, *, field: bool = False, resolution: float | None = None,
                    transport: httpx.BaseTransport | None = None, out: Out = print) -> str:
    """Stage S2C: the coverage census again, with cluster frames (spec §7; framework "Coverage census").

    The framework takes the census per cluster, and gate 1 reads a lineage-window's coverage from its own
    cluster's papers. Only the windows that already meet m and v are framed, because coverage can withhold
    eligibility and never grant it; inside a frame the sample is the registered seeded draw, unchanged.
    """
    config = load_corpus_config(root)
    settings = config.census
    scoped = cluster_draw(root, subject_id, fold, field=field, resolution=resolution)
    case, fetch, draw = scoped.case, scoped.fetch, scoped.draw
    samples = draw.samples
    listing = _listing(root, fetch)
    catalogue = _catalogue(config, listing, tables.read(root / fetch["params"]["tables"]["works"]))
    params = {"fetch_run": fetch["run_id"], "s3_run": scoped.s3["run_id"], "s4_runs": scoped.s4_runs,
              "cluster_resolution": scoped.resolution, "cluster_frames": len(draw.by_frame),
              "frames_scope": "lineage-windows meeting m and v at the resolution, not closed",
              "lineage_works": config.social.lineage_works,
              "works_per_year": settings.works_per_year, "max_unmeasured_share": settings.max_unmeasured_share,
              "resolution": settings.resolution, "doiless_sample_per_work": settings.doiless_sample_per_work,
              "match_year_tolerance": settings.match_year_tolerance, "paper_types": sorted(settings.paper_types),
              "reference_classification": settings.reference_classification}
    with RunContext(root, "S2C", subject_id, fold, [case.component, "thresholds"], seed=settings.seed,
                    params=params) as ctx:
        for name in ("frames", "works", "authors", "authorships"):
            ctx.record_input(root / fetch["params"]["tables"][name])
        for name in ("clusters", "lineages"):
            ctx.record_input(root / scoped.s3["params"]["tables"][name])
        for run_id in scoped.s4_runs.values():
            ctx.record_input(root / load_manifest(root, run_id)["params"]["tables"]["eligibility"])
        references, refused, doi_types, matches, rescued = _measure(
            ctx, root, config, settings, subject_id, samples, {}, listing, catalogue, transport)
        coverage, sample_rows = _census_rows(subject_id, draw, samples, references, doi_types, matches, rescued,
                                             settings)
        written = {}
        for name, rows in (("coverage", coverage), ("census_sample", sample_rows)):
            written[name] = rel_posix(ctx.store(tables.to_parquet(name, rows), "parquet", rows=len(rows)), root)
        report = cluster_census_report(case, ctx.run_id, config, coverage, params, scoped, refused)
        written["report"] = rel_posix(ctx.store(report.encode("utf-8"), "md"), root)
        ctx.params["tables"] = written
    out(report)
    out(_usage_line(ctx.usage))
    return ctx.run_id


def cluster_census_report(case: Case, run_id: str, config: CorpusConfig, coverage: list[dict], params: dict,
                          scoped: ClusterDraw, refused: dict[str, int] | None = None) -> str:
    settings = config.census
    summaries = summarize(coverage, settings.max_unmeasured_share)
    measurable = [s for s in summaries if s.measurable]
    values = sorted(s.coverage for s in measurable if s.coverage is not None)
    lines = [
        f"# Coverage census with cluster frames: {case.case_id}",
        "",
        f"Run `{run_id}` from social-layer run `{scoped.s3['run_id']}` and corpus run `{scoped.fetch['run_id']}`. "
        f"The framework takes the census per cluster: one frame is one lineage's cluster in one sub-window, "
        f"holding the papers that cluster's members published in it. Frames are drawn for the "
        f"{params['cluster_frames']} lineage-window(s) that meet m and v at resolution "
        f"{params['cluster_resolution']:g} and are not closed, since coverage can withhold eligibility but never "
        f"grant it. Up to {settings.works_per_year} papers are sampled per frame and year (seed {settings.seed}), "
        f"and every reference is resolved exactly as in the frame census.",
        "",
        "Coverage is not compared with *r* here: gate 1 applies *r* per sub-window at S4.",
        "",
        "| commitment | lineage-windows framed | S4 run |",
        "|---|---:|---|",
        *(f"| {name} | {count} | `{scoped.s4_runs.get(name, '-')}` |"
          for name, count in sorted(scoped.per_commitment.items())),
        "",
        "| cluster frames | papers | sampled | measurable | coverage min | median | max |",
        "|---:|---:|---:|---:|---:|---:|---:|",
        f"| {len(summaries)} | {sum(s.frame_works for s in summaries)} | {sum(s.sampled for s in summaries)} | "
        f"{len(measurable)} | {_pct(values[0] if values else None)} | "
        f"{_pct(values[len(values) // 2] if values else None)} | {_pct(values[-1] if values else None)} |",
    ]
    if refused:
        lines += ["", "Documents the publisher refused (the paper is unmeasured): "
                  + ", ".join(f"{v} {n}" for v, n in sorted(refused.items())) + "."]
    if summaries:
        lowest = sorted(summaries, key=lambda s: (s.coverage is None, s.coverage or 0.0))[:10]
        lines += ["", "The ten lowest coverages, as a check on which literatures are thin (gate 1 judges, not this "
                      "report):", "",
                  "| cluster frame | papers | sampled | unmeasured | coverage (est.) | measurable |",
                  "|---|---:|---:|---:|---:|---|",
                  *(f"| {s.frame_id} | {s.frame_works} | {s.sampled} | {_pct(s.unmeasured_share)} | "
                    f"{_pct(s.coverage)} | {'yes' if s.measurable else 'no'} |" for s in lowest)]
    return "\n".join(lines) + "\n"


def project_census(fetcher: Fetcher, config: CorpusConfig, samples: dict[str, list[FrameWork]],
                   manual_refs: dict[str, References], listing: dict[str, dict] | None = None) -> Projection:
    projection = Projection()
    reference_dois: list[str] = []
    unarchived_works = 0
    per_work = config.census.doiless_sample_per_work
    match_calls = sum(min(per_work, len(paper_doiless(r))) for r in manual_refs.values())
    seen: set[str] = set()
    listing = listing or {}
    for work in (w for sample in samples.values() for w in sample):
        if work.work_id not in seen and work.work_id not in manual_refs and work.work_id in listing:
            seen.add(work.work_id)
            row = listing[work.work_id]
            if not row["document_url"]:
                continue
            if not fetcher.document_archived(ingest.document_request(row["venue"], row["document_url"])):
                projection.calls[(row["venue"], "document")] += 1
                match_calls += per_work
                continue
            refs = ingest.references(fetcher, row["venue"], row["document_url"])
            match_calls += min(per_work, len(paper_doiless(refs))) if refs else 0
            continue
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
            match_calls += min(per_work, len(paper_doiless(refs))) if refs else 0
    reference_dois += [d for r in manual_refs.values() for d in r.dois if d]
    batch = int(config.openalex["doi_batch"])
    known_calls = math.ceil(len(set(reference_dois)) / batch)
    assumed_calls = math.ceil(unarchived_works * ASSUMED_REFS_PER_WORK / batch)
    projection.calls[("openalex", "list")] += known_calls + assumed_calls + match_calls  # matches: an upper bound
    if unarchived_works:
        projection.unknown.append(f"{unarchived_works} reference list(s) not archived yet; assumed "
                                  f"{ASSUMED_REFS_PER_WORK} references each (an estimate, not a bound)")
    if match_calls:
        projection.unknown.append(f"up to {match_calls} free Crossref bibliographic queries, one per DOI-less "
                                  "reference that volume and page do not match")
    return projection


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


# ---------------------------------------------------------------- calibration selection: author overlap


def _subjects(root: Path) -> list[tuple[str, bool]]:
    return [(p.stem, kind == "fields") for kind in ("cases", "fields")
            for p in sorted((root / REGISTRY / kind).glob("*.yaml"))]


def field_overlap(root: Path, fold: str, *, out: Out = print) -> str:
    """Author overlap between calibration fields, and between fields and cases, from their latest fetches."""
    config = load_corpus_config(root)
    if config.calibration_selection is None:
        raise CaseError("corpus.yaml registers no calibration_selection rule")
    measure, limit, core_min_works = config.calibration_selection
    authors = {}
    fields, missing, fetches, components = set(), [], {}, []
    for subject_id, is_field in _subjects(root):
        case, _ = load_subject(root, subject_id, is_field)
        components.append(case.component)
        if is_field:
            fields.add(subject_id)
        fetch = latest_run(root, "S1", subject_id, fold, require_frozen(root, [case.component], fold))
        if fetch is None:
            missing.append(subject_id)
            continue
        fetches[subject_id] = fetch
        read = {name: tables.read(root / fetch["params"]["tables"][name])
                for name in ("frames", "authorships", "authors")}
        authors[subject_id] = community_authors(read["frames"], read["authorships"], read["authors"],
                                                core_min_works)
    pairs = overlaps(authors, fields)
    with RunContext(root, "S1-overlap", "calibration", fold, components,
                    params={"measure": measure, "max_overlap": limit, "core_min_works": core_min_works,
                            "fetch_runs": {s: f["run_id"] for s, f in sorted(fetches.items())},
                            "without_fetch": missing}) as ctx:
        for fetch in fetches.values():
            for name in ("frames", "authorships", "authors"):
                ctx.record_input(root / fetch["params"]["tables"][name])
        rows = [{"subject_a": p.a, "subject_b": p.b, "basis": p.basis, "authors_a": p.authors_a,
                 "authors_b": p.authors_b,
                 "shared": p.shared, "coefficient": p.coefficient,
                 "exceeds": p.coefficient is not None and p.coefficient > limit} for p in pairs]
        table_path = ctx.store(tables.to_parquet("overlap", rows), "parquet", rows=len(rows))
        lines = [f"# Author overlap: calibration fields ({fold} fold)", "",
                 f"Run `{ctx.run_id}`. Rule `{measure}` (decision D-10): core authors (at least {core_min_works} "
                 "works in a subject's community frames) shared, over the smaller subject's core authors; compared "
                 "by OpenAlex author id when both subjects' works are all from OpenAlex, otherwise by family name and "
                 f"all initials. Above {limit:g} the smaller field is dropped. Pairs of two cases are not shown.", "",
                 "| subject | subject | basis | core authors | core authors | shared | overlap | above limit |",
                 "|---|---|---|---:|---:|---:|---:|---|"]
        for p, row in zip(pairs, rows, strict=True):
            lines.append(f"| {p.a} | {p.b} | {p.basis} | {p.authors_a} | {p.authors_b} | {p.shared} | "
                         f"{_pct(p.coefficient)} | "
                         f"{'yes: ' + p.smaller if row['exceeds'] else 'no'} |")
        if missing:
            lines += ["", f"Without a successful fetch in this fold, so not measured: {', '.join(missing)}."]
        report = "\n".join(lines) + "\n"
        ctx.params["tables"] = {"overlap": rel_posix(table_path, root),
                                "report": rel_posix(ctx.store(report.encode("utf-8"), "md"), root)}
    out(report)
    return ctx.run_id


def census_report(case: Case, run_id: str, fetch_run: str, config: CorpusConfig, coverage: list[dict],
                  undated: int, ingested: bool = False, audit: AuditResult | None = None,
                  audit_sheet: str | None = None, refused: dict[str, int] | None = None) -> str:
    settings = config.census
    ingestion_note = []
    if ingested and config.ingestion is not None:
        venues = ", ".join(sorted({v for f in case.frames for v in f.ingest}))
        ingestion_note = [
            f"Venues ingested from their own archives ({venues}): references are extracted from each sampled paper's "
            f"document (`{config.ingestion.text_extraction}`, `{config.ingestion.reference_extraction}`), and "
            "DOI-less references are first matched against the ingested venues' listings "
            f"(`{config.ingestion.catalogue_match}`). A paper whose document has no readable reference list is "
            "unmeasured." + ("" if audit is not None else " The extraction is not yet audited against the documents "
                                                          "(decision D-1)."),
            "",
            *([f"Documents the publisher refused (HTTP {'/'.join(map(str, sorted(REFUSED_STATUSES)))}; the paper "
               "is unmeasured, and the refusal is archived so the run replays): "
               + ", ".join(f"{v} {n}" for v, n in sorted(refused.items())) + ".", ""] if refused else []),
            *(report_lines(audit, audit_sheet or "") if audit is not None else []),
        ]
    whole = {s.frame_id: s for s in summarize(coverage, settings.max_unmeasured_share)}
    lines = [
        f"# Coverage census: {case.case_id}",
        "",
        f"Run `{run_id}` from corpus run `{fetch_run}`. Window {case.start}–{case.end}. Only research papers count "
        f"(OpenAlex types {', '.join(sorted(settings.paper_types))}; references classified by "
        f"`{settings.reference_classification}`, proceedings kept): other works and references are excluded and "
        f"counted. Up to {settings.works_per_year} papers sampled per frame and year (seed {settings.seed}). A "
        f"reference with a DOI resolves when the DOI is in OpenAlex; up to {settings.doiless_sample_per_work} paper "
        f"references without a DOI per work are matched by year (±{settings.match_year_tolerance}), volume and "
        f"first page, or failing that by a Crossref bibliographic query (score at least "
        f"{settings.rescue_min_score:g}, checked against year, volume, page, journal or title; shown in brackets), "
        f"and each frame-year's matched share estimates the rest. A frame or year with more than "
        f"{settings.max_unmeasured_share:.0%} unmeasured papers is not measurable.",
        "",
        "Coverage is not compared with *r* here: gate 1 applies *r* per sub-window at S4.",
        "",
        *ingestion_note,
        "| frame | kind | papers | excluded works | sampled | unmeasured | paper refs | excluded refs "
        "(non-paper/unclassifiable) | no DOI | DOI-less matched | no volume/page | coverage (est.) | measurable |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for frame in case.frames:
        s: Summary | None = whole.get(frame.frame_id)
        if s is None:
            lines.append(f"| {frame.frame_id} | {frame.kind} | 0 | 0 | 0 | – | 0 | – | – | – | – | n/a | "
                         "no (no works) |")
            continue
        lines.append(f"| {s.frame_id} | {s.kind} | {s.frame_works} | {s.frame_works_excluded} | {s.sampled} | "
                     f"{_pct(s.unmeasured_share)} | {s.refs} | {s.refs_excluded}/{s.refs_unclassifiable} | "
                     f"{_pct(s.doiless / s.refs if s.refs else None)} | "
                     f"{s.doiless_matched}/{s.doiless_sampled} ({s.doiless_rescued}) | "
                     f"{s.doiless_unparseable}/{s.doiless_sampled} | "
                     f"{_pct(s.coverage)} | {'yes' if s.measurable else 'no'} |")
    if not case.frames:
        lines += ["", "No frames: none of this field's venues is in the corpus source, so nothing was sampled."]
    if undated:
        lines += ["", f"{undated} frame work(s) without a publication year were not sampled."]
    if case.absent_venues:
        lines += ["", "Core venues not in the corpus source, so outside every frame until ingested (decision D-8):", ""]
        lines += [f"- {venue}" for venue in case.absent_venues]
    for frame in case.frames:
        rows = [r for r in coverage if r["frame_id"] == frame.frame_id]
        if not rows:
            continue
        lines += ["", f"## {frame.frame_id} by year", "",
                  "| year | papers | excluded works | sampled | unmeasured | paper refs | excluded refs | no DOI | "
                  "DOI-less matched | coverage (est.) | measurable |",
                  "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
        for row in rows:
            (s,) = summarize([row], settings.max_unmeasured_share)
            lines.append(f"| {row['year']} | {row['frame_works']} | {row['frame_works_excluded']} | {row['sampled']} | "
                         f"{_pct(s.unmeasured_share)} | {row['refs']} | "
                         f"{row['refs_excluded']}/{row['refs_unclassifiable']} | "
                         f"{_pct(s.doiless / s.refs if s.refs else None)} | "
                         f"{s.doiless_matched}/{s.doiless_sampled} ({s.doiless_rescued}) | {_pct(s.coverage)} | "
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


ACCESS_FIELDS = ("id", "doi", "publication_year", "open_access", "ids", "best_oa_location")


def access_lookup(root: Path, field_id: str, commitment: str, fold: str, *,
                  transport: httpx.BaseTransport | None = None, out: Out = print) -> int:
    """How much of the literature citing a commitment's results has open full text (decision D-9).

    A lookup, not a run: nothing is stored beyond the archived responses, and spend counts toward the daily cap.
    The papers are the fetched works that cite at least one result bearing on p; for each, OpenAlex says whether
    an open copy exists, whether its best open copy is in PubMed Central (full text as structured XML) and whether
    a PDF address is known. Nothing is downloaded.
    """
    from urllib.parse import urlsplit

    from viveka.social.eligibility import bearing_results

    case, claim = load_commitment(root, field_id, commitment)
    config = load_corpus_config(root)
    fetch = latest_run(root, "S1", field_id, fold, require_frozen(root, [case.component], fold))
    if fetch is None:
        raise CaseError(f"no successful S1 run for {field_id} in fold {fold} with the current registry; "
                        "run `viveka corpus fetch` first")
    read = {name: tables.read(root / fetch["params"]["tables"][name]) for name in ("works", "citations", "frames")}
    citations = [(row["citing_work"], row["cited_work"]) for row in read["citations"]]
    anchors = {ref.openalex for ref in bearing_set(case, claim) if ref.openalex}
    frame_works = {row["work_id"] for row in read["frames"]
                   if row["kind"] == BEARING and row["frame_id"] == f"{BEARING}-{commitment}"}
    bearing = bearing_results(anchors | frame_works, citations)
    own = {row["work_id"] for row in read["frames"] if row["kind"] != BEARING}
    known = {row["work_id"] for row in read["works"]}
    citing = sorted({a for a, b in citations if b in bearing and a != b and a in known and not ingest.is_ingested(a)})
    found: dict[str, dict] = {}
    with make_fetcher(root, config, need=("openalex",), transport=transport) as fetcher:
        for chunk in chunks(citing, openalex.OR_LIMIT):
            response = fetcher.get(openalex.id_batch_request(chunk, ACCESS_FIELDS))
            if response.status != 200 or response.body is None:
                raise FetchError(f"openalex access lookup: HTTP {response.status}")
            for obj in response.body.get("results") or []:
                found[short_id(obj["id"])] = obj
    rows: dict[str, Counter] = defaultdict(Counter)
    hosts: Counter = Counter()
    for work_id in citing:
        obj = found.get(work_id)
        if obj is None:
            rows["not returned"]["papers"] += 1
            continue
        year = obj.get("publication_year")
        group = f"{int(year) // 10 * 10}s" if isinstance(year, int) else "undated"
        access = obj.get("open_access") or {}
        best = obj.get("best_oa_location") or {}
        pdf = best.get("pdf_url")
        # OpenAlex no longer lists a PubMed Central id among a work's ids; its best open copy says where it is
        pmc = ("PubMed Central" in ((best.get("source") or {}).get("display_name") or "")
               or "ncbi.nlm.nih.gov/pmc" in (best.get("landing_page_url") or ""))
        for key in (group, "all", *(("own venues",) if work_id in own else ())):
            rows[key]["papers"] += 1
            rows[key]["open"] += bool(access.get("is_oa"))
            rows[key]["pmc"] += bool(pmc)
            rows[key]["pdf"] += bool(pdf)
            rows[key]["either"] += bool(pmc or pdf)
        if pdf:
            hosts[urlsplit(pdf).netloc.removeprefix("www.")] += 1
    out(f"open full text among the {len(citing)} fetched papers citing a result bearing on {field_id} "
        f"{commitment} (run {fetch['run_id']}); nothing downloaded")
    out("| papers | n | open copy | best copy in PubMed Central | PDF address | either |")
    out("|---|---:|---:|---:|---:|---:|")
    for key in (*sorted(k for k in rows if k.endswith("s") and k[:1].isdigit()), "undated", "not returned",
                "own venues", "all"):
        r = rows.get(key)
        if r:
            n = r["papers"]
            out(f"| {key} | {n} | " + " | ".join(f"{r[c]} ({r[c] / n:.0%})" for c in ("open", "pmc", "pdf", "either"))
                + " |")
    out("PDF hosts: " + ", ".join(f"{host} {n}" for host, n in hosts.most_common(12)))
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
        _subject_arguments(p)
        p.add_argument("--fold", required=True, choices=FOLDS)
        p.add_argument("--dry-run", action="store_true", help="Project live calls from the archive; no network")
        if action == "fetch":
            p.add_argument("--probe", action="store_true",
                           help="Live: resolve registered works and first pages only, then project")
        else:
            p.add_argument("--commitment", help="A calibration field's commitment (fields format 2)")

    p = csub.add_parser("member-contexts", parents=[common],
                        help="S1: contexts of lineage members' citations of results bearing on a claim (D-28)")
    p.add_argument("--field", required=True)
    p.add_argument("--commitment", required=True)
    p.add_argument("--fold", required=True, choices=FOLDS)
    p.add_argument("--dry-run", action="store_true", help="Show the scope and the requests; no network")

    p = csub.add_parser("abstracts", parents=[common],
                        help="S1: OpenAlex abstracts of the bearing results with a member context (D-28)")
    p.add_argument("--field", required=True)
    p.add_argument("--commitment", required=True)
    p.add_argument("--fold", required=True, choices=FOLDS)

    p = csub.add_parser("access", parents=[common],
                        help="Lookup: how much of the literature citing a commitment's results has open full text")
    p.add_argument("--field", required=True)
    p.add_argument("--commitment", required=True)
    p.add_argument("--fold", required=True, choices=FOLDS)

    p = csub.add_parser("audit", parents=[common],
                        help="Write ingestion audit sheets for the latest census of ingested venues (no network)")
    _subject_arguments(p)
    p.add_argument("--fold", required=True, choices=FOLDS)

    case = sub.add_parser("case", help="Case definitions")
    casesub = case.add_subparsers(dest="action", required=True)
    p = casesub.add_parser("validate", parents=[common], help="Validate a case, its claim and the corpus settings")
    p.add_argument("case")

    field = sub.add_parser("field", help="Calibration field definitions")
    fieldsub = field.add_subparsers(dest="action", required=True)
    p = fieldsub.add_parser("validate", parents=[common], help="Validate a calibration field and the corpus settings")
    p.add_argument("field")
    p = fieldsub.add_parser("overlap", parents=[common],
                            help="Author overlap between calibration fields and with cases (decision D-10)")
    p.add_argument("--fold", required=True, choices=FOLDS)

    p = sub.add_parser("census", parents=[common], help="S2: coverage census for a case or calibration field")
    _subject_arguments(p)
    p.add_argument("--fold", required=True, choices=FOLDS)
    p.add_argument("--clusters", action="store_true",
                   help="S2C: census the clusters S3 found, for the lineage-windows S4 passes on m and v")
    p.add_argument("--resolution", type=float,
                   help="With --clusters: the sweep resolution to census (default: the registered primary)")
    p.add_argument("--dry-run", action="store_true", help="Project live calls from the archive; no network")
    p.add_argument("--manual", type=Path, help=f"CSV of hand-entered reference lists under {MANUAL_DIR}/")
    p.add_argument("--audit", type=Path, help=f"A completed ingestion audit (<name>-references.csv under {AUDIT_DIR}/)")


def _subject_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--case", help="A pilot or reserve case (registry/cases/<case>.yaml)")
    group.add_argument("--field", help="A calibration field (registry/fields/<field>.yaml)")


def _subject(args: argparse.Namespace) -> tuple[str, bool]:
    return (args.field, True) if getattr(args, "field", None) else (args.case, False)


def _dry_run(root: Path, args: argparse.Namespace, out: Out) -> int:
    subject_id, is_field = _subject(args)
    case, claim = load_subject(root, subject_id, is_field)
    config = load_corpus_config(root)
    with make_fetcher(root, config, offline=True) as fetcher:
        if args.command == "census":
            if getattr(args, "clusters", False):
                scoped = cluster_draw(root, subject_id, args.fold, field=is_field, resolution=args.resolution)
                samples = scoped.draw.samples
                projection = project_census(fetcher, config, samples, {}, _listing(root, scoped.fetch))
                out(f"cluster census dry run for {subject_id}: {len(scoped.draw.by_frame)} cluster frame(s) at "
                    f"resolution {scoped.resolution:g}, {sum(len(s) for s in samples.values())} sampled works "
                    f"({len({w.work_id for s in samples.values() for w in s})} distinct)")
                out("\n".join(projection.lines(config)))
                return 0
            fetch, frames_rows, works_rows = _fetch_inputs(root, case, args.fold)
            samples = draw_sample(case, frames_rows, works_rows, config.census.works_per_year, config.census.seed,
                                  config.census.paper_types).samples
            projection = project_census(fetcher, config, samples, _manual_refs(root, args.manual),
                                        _listing(root, fetch))
            out(f"census dry run for {subject_id}: {sum(len(s) for s in samples.values())} sampled works")
        else:
            commitments = tuple((c.commitment_id, _anchors(root, case, c)) for c in case.commitments)
            projection = project_fetch(fetcher, config, case, claim, commitments)
            if args.action == "contexts":
                projection.unknown.append("Semantic Scholar pages: one per 1000 citations of each bearing work")
            out(f"{args.action} dry run for {subject_id}:")
    out("\n".join(projection.lines(config)))
    return 0


def run(args: argparse.Namespace, root: Path, *, transport: httpx.BaseTransport | None = None,
        out: Out = print) -> int:
    try:
        if args.command == "case":
            case, claim = load_subject(root, args.case, False)
            out(f"case {case.case_id} valid: claim {claim.claim_id} ({len(claim.events)} events), "
                f"{len(case.seeds)} seeds, frames {', '.join(f'{f.frame_id} ({f.kind})' for f in case.frames)}, "
                f"window {case.start}–{case.end}")
            return 0
        if args.command == "field" and args.action == "overlap":
            field_overlap(root, args.fold, out=out)
            return 0
        if args.command == "field":
            case, _ = load_subject(root, args.field, True)
            sources = sum(len(f.sources) for f in case.frames)
            ingested = sorted({v for f in case.frames for v in f.ingest})
            out(f"field {case.case_id} valid: {case.pair}, {len(case.frames)} frame(s) over {sources} source(s)"
                + (f" and ingested venue(s) {', '.join(ingested)}" if ingested else "") + ", "
                f"window {case.start}–{case.end}, {len(case.absent_venues)} absent venue(s)"
                + (", commitments " + ", ".join(c.commitment_id for c in case.commitments)
                   if case.commitments else ", no commitments"))
            return 0
        if args.command == "corpus" and args.action == "resolve":
            return resolve_lookup(root, doi=args.doi, openalex_id=args.openalex_id, title=args.title,
                                  source_name=args.source_name, transport=transport, out=out)
        if args.command == "corpus" and args.action == "member-contexts":
            if args.dry_run:
                _, _, windows, scope = coding_scope(root, args.field, args.commitment, args.fold)
                citing = {r["citing_work"] for r in scope}
                out(f"member-contexts dry run for {args.field}-{args.commitment}: {len(windows)} lineage-window(s), "
                    f"{len({(r['citing_work'], r['cited_work']) for r in scope})} citations of "
                    f"{len({r['cited_work'] for r in scope})} bearing results from {len(citing)} citing papers")
                out(f"  semanticscholar free: about {len(citing)} reference request(s), one per citing paper "
                    "(archived ones replay)")
                return 0
            fetch_member_contexts(root, args.field, args.commitment, args.fold, transport=transport, out=out)
            return 0
        if args.command == "corpus" and args.action == "abstracts":
            fetch_abstracts(root, args.field, args.commitment, args.fold, transport=transport, out=out)
            return 0
        if args.command == "corpus" and args.action == "access":
            return access_lookup(root, args.field, args.commitment, args.fold, transport=transport, out=out)
        subject_id, is_field = _subject(args)
        if args.command == "corpus" and args.action == "audit":
            audit_sheets(root, subject_id, args.fold, field=is_field, out=out)
            return 0
        if getattr(args, "probe", False):
            case, claim = load_subject(root, subject_id, is_field)
            config = load_corpus_config(root)
            with make_fetcher(root, config, need=("openalex",), transport=transport) as fetcher:
                probe(fetcher, config, case, claim)
            out(_usage_line(fetcher.usage.as_manifest()))
            return _dry_run(root, args, out)
        if args.dry_run:
            return _dry_run(root, args, out)
        if args.command == "census" and args.clusters:
            census_clusters(root, subject_id, args.fold, field=is_field, resolution=args.resolution,
                            transport=transport, out=out)
        elif args.command == "census":
            census_case(root, subject_id, args.fold, field=is_field, manual=args.manual, audit=args.audit,
                        transport=transport, out=out)
        elif args.action == "fetch":
            fetch_case(root, subject_id, args.fold, field=is_field, transport=transport, out=out)
        else:
            fetch_contexts(root, subject_id, args.fold, field=is_field, commitment=args.commitment,
                           transport=transport, out=out)
        return 0
    except (CaseError, FetchError, env.MissingCredential, ManualImportError, AuditError) as exc:
        out(f"viveka: {exc}")
        return 1
