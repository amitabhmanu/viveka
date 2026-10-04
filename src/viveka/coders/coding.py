"""Stage S8, coding (decision D-28): direction of each bearing result (T7) and stance of each member context (T1).

Both tasks run per commitment, once per qualified coder (one repetition: test-retest was measured at S7), on the
items of the newest member-contexts run and its abstracts:

* T7 items are the bearing results that have at least one member context and an abstract: the claim's wording
  and the unredacted abstract (the claim names the topic, D-25). A result without an abstract is unmeasured.
* T1 items are the member contexts, built by the D-24 rules and redacted as at S6-S7.

S8 codes only with the pool the newest S7 audit qualified under the current instrument and thresholds, with the
T1 task version that audit used (spec: "No coding before audits"). Labels are kept per coder and never
reconciled; intervals resample over coders (D-21, D-28).
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

from viveka.coders.base import Item, Label

TASKS = {"T7": "T7-direction", "T1": "T1-stance"}
SEED = 20261008


class CodingRefused(RuntimeError):
    pass


def direction_items(claim_id: str, wording: str, abstracts: Mapping[str, str | None]
                    ) -> tuple[list[Item], dict[str, str], int]:
    """(items, item id -> work id, results without an abstract). An item id hashes the claim and the work, so
    it says nothing about either."""
    items, work_of, missing = [], {}, 0
    for work in sorted(abstracts):
        text = abstracts[work]
        if not text:
            missing += 1
            continue
        item_id = hashlib.sha256(f"T7\n{claim_id}\n{work}".encode()).hexdigest()[:20]
        items.append(Item(item_id, f"Claim: {wording}\n\nAbstract: {' '.join(text.split())}"))
        work_of[item_id] = work
    return items, work_of, missing


def qualified_pool(root: Path, fold: str, current: Mapping[str, str], t1_version: str) -> dict:
    """The newest S7 audit in the fold whose instrument and thresholds are the current ones and whose pool
    qualifies; refuses when there is none."""
    from viveka.provenance import recent_runs

    for m in recent_runs(root, limit=10_000):
        if m.get("stage") != "S7-audits" or m.get("fold") != fold or m.get("status") != "ok":
            continue
        components = m["registry"]["components"]
        if any(components.get(name) != current.get(name) for name in ("instrument", "thresholds")):
            continue
        if m["params"].get("task_version") != t1_version:
            continue
        if not m["params"]["result"]["pool_qualifies"]:
            raise CodingRefused(f"the newest audit under the current instrument ({m['run_id']}) does not qualify the "
                                "pool")
        return m
    raise CodingRefused(f"no S7 audit in fold {fold} under the current instrument, thresholds and T1 version")


def label_rows(task_id: str, subject: str, results: Sequence, work_of: Mapping[str, str]) -> list[dict]:
    rows = []
    for r in results:
        value = r.value if isinstance(r, Label) else {}
        rows.append({"task": task_id, "subject": subject, "item_id": r.item_id, "work_id": work_of.get(r.item_id),
                     "coder_id": r.coder_id, "rep": r.rep, "label": value.get("label"),
                     "span": value.get("basis_span") if task_id == "T7" else value.get("reason_span"),
                     "missing": None if isinstance(r, Label) else r.reason})
    return rows


def run_coding(root: Path, task_id: str, field_id: str, commitment: str, fold: str, *,
               max_live_calls: int | None = None, dry_run: bool = False, out=print) -> str | None:
    from viveka.cases import load_commitment
    from viveka.coders.claude_cli import ClaudeCliCoder
    from viveka.coders.items import CitedWork, build_items
    from viveka.coders.leakage import RULES, load_coders
    from viveka.coders.redaction import build, load_dictionaries
    from viveka.coders.tasks import load_task
    from viveka.corpus import tables
    from viveka.corpus.commands import latest_member_contexts, latest_run
    from viveka.paths import rel_posix
    from viveka.provenance import RunContext, load_manifest
    from viveka.registry.verify import require_frozen

    if task_id not in TASKS:
        raise CodingRefused(f"unknown task {task_id}")
    case, claim = load_commitment(root, field_id, commitment)
    subject = f"{field_id}-{commitment}"
    task = load_task(root, TASKS[task_id])
    components = ["prompts", "instrument", "thresholds", case.component, *(
        [f"redaction/{field_id}"] if task_id == "T1" else [])]
    current = require_frozen(root, components, fold)
    audit = qualified_pool(root, fold, current, load_task(root, TASKS["T1"]).version)
    qualified = set(audit["params"]["result"]["qualified"])
    coders = [c for c in load_coders(root) if c.coder_id in qualified]
    contexts_run = latest_member_contexts(root, field_id, commitment, fold)
    contexts = tables.read(root / contexts_run["params"]["tables"]["member_contexts"])
    inputs = [contexts_run["params"]["tables"]["member_contexts"]]
    extra: dict = {}
    if task_id == "T7":
        abstracts_run = latest_run(root, "S1-abstracts", subject, fold,
                                   require_frozen(root, [case.component, "thresholds"], fold))
        if abstracts_run is None or abstracts_run["params"]["member_contexts_run"] != contexts_run["run_id"]:
            raise CodingRefused(f"no abstracts run for {subject} from member-contexts run {contexts_run['run_id']}; "
                                "run `viveka corpus abstracts` first")
        inputs.append(abstracts_run["params"]["tables"]["abstracts"])
        abstracts = {r["work_id"]: r["abstract"] for r in tables.read(root / inputs[-1])}
        items, work_of, missing = direction_items(claim.claim_id, claim.wording, abstracts)
        extra = {"abstracts_run": abstracts_run["run_id"], "results_without_abstract": missing}
    else:
        fetch = load_manifest(root, contexts_run["params"]["fetch_run"])
        t = fetch["params"]["tables"]
        works = {r["work_id"]: r for r in tables.read(root / t["works"])}
        names = {r["author_id"]: r["display_name"] for r in tables.read(root / t["authors"])}
        first = {r["work_id"]: names.get(r["author_id"]) for r in tables.read(root / t["authorships"])
                 if r["position"] == "first"}
        cited = {w: CitedWork(w, first[w].split()[-1] if first.get(w) else None, (works.get(w) or {}).get("year"))
                 for w in {r["cited_work"] for r in contexts}}
        built, dropped = build_items(contexts, cited, build(load_dictionaries(root, [field_id])))
        items = [Item(i.item_id, i.text) for i in built]
        work_of = {i.item_id: i.cited_work for i in built}
        extra = {"rules": list(RULES), "dropped": dict(dropped), "contexts": len(contexts)}
    calls = -(-len(items) // task.batch_size)
    out(f"{task_id} {subject}: {len(items)} items, {calls} call(s) per coder, coders "
        f"{', '.join(c.coder_id for c in coders)}"
        + (f"; results without an abstract {extra['results_without_abstract']}" if task_id == "T7" else
           f"; dropped {dict(extra['dropped'])}"))
    if dry_run:
        return None
    params = {"task": task_id, "task_version": task.version, "batch_size": task.batch_size, "seed": SEED,
              "commitment": commitment, "claim": claim.claim_id, "side": case.pair,
              "member_contexts_run": contexts_run["run_id"], "audit_run": audit["run_id"],
              "coders": [c.coder_id for c in coders], "items": len(items), **extra}
    with RunContext(root, "S8", subject, fold, components, seed=SEED, params=params) as ctx:
        for path in inputs:
            ctx.record_input(root / path)
        rows, usage = [], {}
        for spec in coders:
            coder = ClaudeCliCoder(spec, root / "data" / "raw" / "coders" / spec.family, max_live_calls=max_live_calls)
            rows += label_rows(task_id, subject, coder.code(task, items, seed=SEED, rep=0), work_of)
            usage[spec.coder_id] = {"live_calls": coder.live_calls, "replayed": coder.replayed,
                                    "cli_version": coder.cli_version}
        counts = Counter((r["coder_id"], r["label"] or f"missing:{r['missing']}") for r in rows)
        item_rows = [{"item_id": i.item_id, "work_id": work_of[i.item_id], "text": i.text} for i in items]
        ctx.params.update(coder_usage=usage, label_counts={f"{c} {lab}": n for (c, lab), n in sorted(counts.items())},
                          tables={"labels": rel_posix(ctx.store(tables.to_parquet("labels", rows), "parquet",
                                                                rows=len(rows)), root),
                                  "items": rel_posix(ctx.store(tables.to_parquet("items", item_rows), "parquet",
                                                               rows=len(item_rows)), root)})
    for (coder_id, lab), n in sorted(counts.items()):
        out(f"  {coder_id}: {lab} {n}")
    out(f"run {ctx.run_id}")
    return ctx.run_id
