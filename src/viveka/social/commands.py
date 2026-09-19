"""Stage S3: the social layer of a case, from its latest fetch in the same fold.

For every sub-window of w years stepped yearly across the case's window, the author graph
(``coauthor_citation_v1``) is clustered by Leiden at every sweep resolution, and each resolution's clusters are
linked into lineages. The block model is the sweep's second method; without a graph-tool runtime it is
recorded as unavailable, and the run is provisional (decision D-1). No stance, claim or prediction is read.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from viveka.cases import CaseError, load_subject
from viveka.corpus import ingest, tables
from viveka.corpus.commands import latest_run
from viveka.corpus.config import load_corpus_config
from viveka.paths import rel_posix
from viveka.provenance import RunContext
from viveka.registry.thresholds import load_thresholds
from viveka.registry.verify import require_frozen
from viveka.social.graph import authors_by_work, build_graph, node_keys, windows
from viveka.social.leiden import METHOD, leiden
from viveka.social.lineage import link

Out = Callable[[str], None]
UNAVAILABLE = ("hsbm",)  # graph-tool has no Windows build (decision D-1, 19 Sep 2026)


def social_build(root: Path, case_id: str, fold: str, *, out: Out = print) -> str:
    case, _ = load_subject(root, case_id, False)
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
            for name in ("works", "authors", "authorships", "citations")}
    by_name = any(ingest.is_ingested(r["work_id"]) for r in read["works"])
    keys = node_keys(read["authors"], by_name)
    years = {r["work_id"]: r["year"] for r in read["works"]}
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
        for name in ("works", "authors", "authorships", "citations"):
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


def social_dry_run(root: Path, case_id: str, fold: str, *, out: Out = print) -> int:
    """What S3 would read and run, without writing anything."""
    case, _ = load_subject(root, case_id, False)
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
    p = ssub.add_parser("build", parents=[common], help="Cluster a case's authors per sub-window and link lineages")
    p.add_argument("--case", required=True)
    p.add_argument("--fold", required=True)
    p.add_argument("--dry-run", action="store_true")


def run(args, root: Path, *, out: Out = print) -> int:
    from viveka.registry.errors import RegistryError

    try:
        if args.dry_run:
            return social_dry_run(root, args.case, args.fold, out=out)
        social_build(root, args.case, args.fold, out=out)
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
