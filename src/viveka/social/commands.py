"""Stage S3: the social layer of a case, from its latest fetch in the same fold.

For every sub-window of w years stepped yearly across the case's window, the author graph
(``coauthor_citation_v1``) is clustered by Leiden at every sweep resolution, and each resolution's clusters are
linked into lineages. The block model is the sweep's second method; without a graph-tool runtime it is
recorded as unavailable, and the run is provisional (decision D-1). No stance, claim or prediction is read.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from viveka.cases import CaseError, bearing_set, load_commitment, load_subject
from viveka.corpus import ingest, tables
from viveka.corpus.commands import BEARING, latest_run
from viveka.corpus.config import load_corpus_config
from viveka.paths import rel_posix
from viveka.provenance import RunContext
from viveka.registry.thresholds import load_thresholds
from viveka.registry.verify import require_frozen
from viveka.social.graph import Window, authors_by_work, build_graph, node_keys, windows
from viveka.social.leiden import METHOD, leiden
from viveka.social.lineage import link

Out = Callable[[str], None]


def _own_works(frames_rows: list[dict]) -> set[str]:
    """The subject's own works: every frame but a commitment's bearing frame, which is the literature on p."""
    return {row["work_id"] for row in frames_rows if row["kind"] != BEARING}
UNAVAILABLE = ("hsbm",)  # graph-tool has no Windows build (decision D-1, 19 Sep 2026)


def social_build(root: Path, case_id: str, fold: str, *, field: bool = False, out: Out = print) -> str:
    case, _ = load_subject(root, case_id, field)
    config = load_corpus_config(root)
    if config.social is None:
        raise CaseError("corpus.yaml registers no social settings")
    settings = config.social
    thresholds = load_thresholds(root)
    w = int(thresholds["w_window_years"])
    o = float(thresholds["o_min_overlap"])
    sweep = thresholds["sweep"]
    resolutions = [float(r) for r in sweep["resolutions"]]
    if settings.primary_resolution not in resolutions:
        raise CaseError(f"primary_resolution {settings.primary_resolution} is not a sweep resolution")
    fetch = latest_run(root, "S1", case_id, fold, require_frozen(root, [case.component], fold))
    if fetch is None:
        raise CaseError(f"no successful S1 run for {case_id} in fold {fold} with the current registry; "
                        "run `viveka corpus fetch` first")
    read = {name: tables.read(root / fetch["params"]["tables"][name])
            for name in ("works", "authors", "authorships", "citations", "frames")}
    own = _own_works(read["frames"])
    by_name = any(ingest.is_ingested(r["work_id"]) for r in read["works"])
    keys = node_keys(read["authors"], by_name)
    years = {r["work_id"]: r["year"] for r in read["works"] if not own or r["work_id"] in own}
    authors = authors_by_work((r["work_id"], keys[r["author_id"]]) for r in read["authorships"]
                              if r["author_id"] in keys)
    citations = [(r["citing_work"], r["cited_work"]) for r in read["citations"]]
    spans = windows(case.start, case.end, w)

    params = {"fetch_run": fetch["run_id"], "graph": settings.graph, "nodes": "name" if by_name else "openalex_id",
              "w": w, "o": o, "resolutions": resolutions, "methods_run": [METHOD],
              "methods_unavailable": list(UNAVAILABLE), "provisional": bool(UNAVAILABLE),
              "leiden_seed": settings.leiden_seed, "lineage_min_members": settings.lineage_min_members}
    with RunContext(root, "S3", case_id, fold, [case.component, "thresholds"], seed=settings.leiden_seed,
                    params=params) as ctx:
        for name in ("works", "authors", "authorships", "citations", "frames"):
            ctx.record_input(root / fetch["params"]["tables"][name])
        graphs = [build_graph(span, years, authors, citations) for span in spans]
        cluster_rows, lineage_rows, summary = [], [], []
        for resolution in resolutions:
            partitions = [(g.window, leiden(g, resolution, settings.leiden_seed)) for g in graphs]
            for window, partition in partitions:
                for index, members in enumerate(partition.clusters):
                    cluster_rows += [{"method": METHOD, "resolution": resolution, "window_start": window.start,
                                      "window_end": window.end, "cluster": index, "author": a} for a in members]
            steps = link(partitions, o, settings.lineage_min_members)
            lineage_rows += [{"method": METHOD, "resolution": resolution, "lineage_id": s.lineage_id,
                              "window_start": s.window.start, "window_end": s.window.end, "cluster": s.cluster,
                              "members": len(s.members), "parent": s.parent, "overlap": s.overlap} for s in steps]
            largest = max((len(p.clusters[0]) for _, p in partitions if p.clusters), default=0)
            summary.append((resolution, len({s.lineage_id for s in steps}), largest))
        written = {name: rel_posix(ctx.store(tables.to_parquet(name, rows), "parquet", rows=len(rows)), root)
                   for name, rows in (("clusters", cluster_rows), ("lineages", lineage_rows))}
        report = _report(case_id, ctx.run_id, fetch["run_id"], fold, params, graphs, summary)
        written["report"] = rel_posix(ctx.store(report.encode("utf-8"), "md"), root)
        ctx.params["tables"] = written
    out(report)
    return ctx.run_id


def eligibility_run(root: Path, case_id: str, fold: str, *, field: bool = False, commitment: str | None = None,
                    out: Out = print) -> str:
    """Stage S4: gate 1 before coding, per lineage and sub-window, from the case's latest S3 run.

    Coverage per lineage is measured only for lineage-windows that pass m and v, since no other can be eligible;
    a census with cluster frames is not built yet, so such a window's coverage is reported as not measured and
    it cannot be declared eligible. The pilot power check needs at least one eligible lineage and is not run
    otherwise. n is pending until M8 (decision D-11). Predictions are never read: whether a case's predicted
    field summary needs one lineage or two is checked when predictions are frozen.
    """
    from viveka.social.eligibility import bearing_results, check
    from viveka.social.lineage import LineageStep

    if field:
        if not commitment:
            raise CaseError(f"field {case_id} is scored per commitment; name one with --commitment")
        case, claim = load_commitment(root, case_id, commitment)
    else:
        case, claim = load_subject(root, case_id, False)
    if claim is None:
        raise CaseError(f"{case_id} has no claim; eligibility needs one")
    subject = f"{case_id}-{commitment}" if commitment else case_id
    thresholds = load_thresholds(root)
    m, v = int(thresholds["m_min_members"]), int(thresholds["v_min_citations"])
    r, lag = float(thresholds["r_min_coverage"]), float(thresholds["l_lag_years"])
    s3 = latest_run(root, "S3", case_id, fold, require_frozen(root, [case.component, "thresholds"], fold))
    if s3 is None:
        raise CaseError(f"no successful S3 run for {case_id} in fold {fold} with the current registry; "
                        "run `viveka social build` first")
    fetch = latest_run(root, "S1", case_id, fold, require_frozen(root, [case.component], fold))
    if fetch is None or fetch["run_id"] != s3["params"]["fetch_run"]:
        raise CaseError(f"the latest S1 run for {case_id} is not the one S3 used; rerun `viveka social build`")
    read = {name: tables.read(root / fetch["params"]["tables"][name])
            for name in ("works", "authors", "authorships", "citations", "frames")}
    own = _own_works(read["frames"])
    keys = node_keys(read["authors"], s3["params"]["nodes"] == "name")
    years = {row["work_id"]: row["year"] for row in read["works"] if not own or row["work_id"] in own}
    authors = authors_by_work((row["work_id"], keys[row["author_id"]]) for row in read["authorships"]
                              if row["author_id"] in keys)
    citations = [(row["citing_work"], row["cited_work"]) for row in read["citations"]]
    social = load_corpus_config(root).social
    if social is None or social.bearing_results != "bearing_results_v2":
        raise CaseError("corpus.yaml social settings register no known bearing_results rule")
    anchors = {ref.openalex for ref in bearing_set(case, claim) if ref.openalex}
    frame_works = {row["work_id"] for row in read["frames"]
                   if row["kind"] == BEARING and (not commitment or row["frame_id"] == f"{BEARING}-{commitment}")}
    bearing = bearing_results(anchors | frame_works, citations)
    dates = [e.date for e in claim.events if e.kind == "disconfirmation"]
    members: dict[tuple[float, int, int], set[str]] = {}
    for row in tables.read(root / s3["params"]["tables"]["clusters"]):
        members.setdefault((row["resolution"], row["window_start"], row["cluster"]), set()).add(row["author"])
    lineage_rows = tables.read(root / s3["params"]["tables"]["lineages"])
    primary = float(social.primary_resolution)

    params = {"s3_run": s3["run_id"], "fetch_run": fetch["run_id"], "m": m, "v": v, "r": r, "lag": lag,
              "n": "pending (fitted at M8, decision D-11)", "primary_resolution": primary,
              "provisional": bool(s3["params"].get("provisional")), "bearing_rule": social.bearing_results,
              "commitment": commitment, "claim": claim.claim_id,
              "bearing_anchors": len(anchors), "bearing_works": len(bearing),
              "disconfirmation_events": len(dates)}
    with RunContext(root, "S4", subject, fold, [case.component, "thresholds"], params=params) as ctx:
        for name in ("works", "authors", "authorships", "citations", "frames"):
            ctx.record_input(root / fetch["params"]["tables"][name])
        for name in ("clusters", "lineages"):
            ctx.record_input(root / s3["params"]["tables"][name])
        rows, by_resolution = [], {}
        for resolution in sorted({row["resolution"] for row in lineage_rows}):
            steps = [LineageStep(row["lineage_id"], Window(row["window_start"], row["window_end"]), row["cluster"],
                                 frozenset(members[(resolution, row["window_start"], row["cluster"])]),
                                 row["parent"], row["overlap"])
                     for row in lineage_rows if row["resolution"] == resolution]
            checks = check(steps, years, authors, citations, bearing, dates, m, v, r, lag)
            by_resolution[resolution] = checks
            rows += [{"resolution": resolution, "lineage_id": c.lineage_id, "window_start": c.window_start,
                      "window_end": c.window_end, "members": c.members, "citations_on_claim": c.citations_on_claim,
                      "disconfirmations": c.disconfirmations, "coverage": c.coverage, "closed": c.closed,
                      "meets_m": c.meets_m, "meets_v": c.meets_v, "meets_r": c.meets_r} for c in checks]
        chosen = by_resolution.get(primary, [])
        need_coverage = [c for c in chosen if c.meets_m and c.meets_v and not c.closed]
        eligible = sorted({c.lineage_id for c in chosen if c.eligible_pending_n})
        decision = "go (pending n)" if eligible else "replace"
        ctx.params.update(decision=decision, eligible_lineages=eligible,
                          windows_needing_coverage=len(need_coverage), power_check="not run: no eligible lineage"
                          if not eligible else "pending")
        path = ctx.store(tables.to_parquet("eligibility", rows), "parquet", rows=len(rows))
        report = _eligibility_report(subject, ctx.run_id, s3["run_id"], fold, params, by_resolution, primary,
                                     decision, len(need_coverage))
        ctx.params["tables"] = {"eligibility": rel_posix(path, root),
                                "report": rel_posix(ctx.store(report.encode("utf-8"), "md"), root)}
    out(report)
    return ctx.run_id


def _eligibility_report(case_id, run_id, s3_run, fold, params, by_resolution, primary, decision, need) -> str:
    lines = [
        f"# Eligibility (gate 1 before coding): {case_id} ({fold} fold)", "",
        f"Run `{run_id}` from social-layer run `{s3_run}`. A lineage's sub-window is eligible when its cluster has "
        f"at least m = {params['m']} members, cites at least v = {params['v']} distinct results bearing on the "
        f"claim (`{params['bearing_rule']}`: {params['bearing_anchors']} seed and event works and the corpus works "
        f"citing them, {params['bearing_works']} in all), and its literature's coverage is at least "
        f"r = {params['r']:g}. n is pending until it is fitted at M8 (decision D-11); the report counts the "
        f"{params['disconfirmation_events']} registered disconfirmations at least {params['lag']:g} years old by each "
        "sub-window's end. A lineage below v after its last sub-window at or above v is closed.", "",
        "**Provisional:** clusters come from Leiden alone (decision D-1)." if params["provisional"] else "", "",
        "| resolution | lineage-windows | largest cluster | most citations on the claim | meet m | meet v | "
        "meet m and v | eligible (pending n) |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for resolution, checks in sorted(by_resolution.items()):
        lines.append(
            f"| {resolution:g}{' (decides)' if resolution == primary else ''} | {len(checks)} | "
            f"{max((c.members for c in checks), default=0)} | "
            f"{max((c.citations_on_claim for c in checks), default=0)} | {sum(c.meets_m for c in checks)} | "
            f"{sum(c.meets_v for c in checks)} | {sum(c.meets_m and c.meets_v for c in checks)} | "
            f"{sum(c.eligible_pending_n for c in checks)} |")
    lines += ["", f"**Decision at resolution {primary:g}: {decision}.**" + (
        f" {need} lineage-window(s) pass m and v but their coverage is not measured yet (census with cluster "
        "frames), so none can be declared eligible." if need and decision == "replace" else
        " No lineage passes m and v, so coverage and the pilot power check are not needed." if not need else ""), ""]
    return "\n".join(lines)


def social_dry_run(root: Path, case_id: str, fold: str, *, field: bool = False, out: Out = print) -> int:
    """What S3 would read and run, without writing anything."""
    case, _ = load_subject(root, case_id, field)
    thresholds = load_thresholds(root)
    fetch = latest_run(root, "S1", case_id, fold, require_frozen(root, [case.component], fold))
    spans = windows(case.start, case.end, int(thresholds["w_window_years"]))
    resolutions = thresholds["sweep"]["resolutions"]
    out(f"S3 dry run for {case_id} ({fold}): corpus run {fetch['run_id'] if fetch else 'none (fetch first)'}; "
        f"{len(spans)} sub-windows x {len(resolutions)} resolutions of Leiden; no network, no spend")
    return 0 if fetch else 1


def add_parser(sub, common) -> None:
    social = sub.add_parser("social", help="S3: the social layer (author graphs, clusters, lineages)")
    ssub = social.add_subparsers(dest="action", required=True)
    p = ssub.add_parser("build", parents=[common],
                        help="Cluster a case's or field's authors per sub-window and link lineages")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--case")
    group.add_argument("--field")
    p.add_argument("--fold", required=True)
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("eligibility", parents=[common], help="S4: gate 1 before coding, per lineage and sub-window")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--case")
    group.add_argument("--field")
    p.add_argument("--commitment", help="A calibration field's commitment (fields format 2)")
    p.add_argument("--fold", required=True)
    p.add_argument("--dry-run", action="store_true")


def run(args, root: Path, *, out: Out = print) -> int:
    from viveka.registry.errors import RegistryError

    subject, is_field = (args.field, True) if getattr(args, "field", None) else (args.case, False)
    try:
        if args.command == "eligibility":
            if args.dry_run:
                out(f"S4 dry run for {subject} ({args.fold}): reads the latest S3 and S1 runs; local, no spend")
                return 0
            eligibility_run(root, subject, args.fold, field=is_field, commitment=args.commitment, out=out)
            return 0
        if args.dry_run:
            return social_dry_run(root, subject, args.fold, field=is_field, out=out)
        social_build(root, subject, args.fold, field=is_field, out=out)
        return 0
    except (CaseError, RegistryError) as exc:
        out(f"viveka: {exc}")
        return 1


def _report(case_id: str, run_id: str, fetch_run: str, fold: str, params: dict, graphs, summary) -> str:
    lines = [
        f"# Social layer: {case_id} ({fold} fold)", "",
        f"Run `{run_id}` from corpus run `{fetch_run}`. Graph `{params['graph']}` over "
        f"{'author names (the case has ingested venues)' if params['nodes'] == 'name' else 'OpenAlex author ids'}; "
        f"sub-windows of {params['w']} years stepped yearly; Leiden at resolutions "
        f"{', '.join(f'{r:g}' for r in params['resolutions'])} (seed {params['leiden_seed']}); lineages link clusters "
        f"of at least {params['lineage_min_members']} authors at Jaccard overlap {params['o']:g} or more.", "",
        "**Provisional:** the hierarchical block model, the sweep's second method, has no runtime here "
        "(decision D-1), so these clusters come from Leiden alone." if params["provisional"] else "", "",
        "| sub-window | authors | ties |", "|---|---:|---:|",
        *(f"| {g.window.label} | {len(g.nodes)} | {len(g.edges)} |" for g in graphs), "",
        "| resolution | lineages | largest cluster in any sub-window |", "|---:|---:|---:|",
        *(f"| {r:g} | {n} | {largest} |" for r, n, largest in summary),
    ]
    return "\n".join(lines) + "\n"
