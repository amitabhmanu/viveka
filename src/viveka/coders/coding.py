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


def run_coding(root: Path, task_id: str, field_id: str, commitment: str | None, fold: str, *,
               max_live_calls: int | None = None, dry_run: bool = False, directed_only: bool = False,
               out=print) -> str | None:
    from viveka.cases import load_coded
    from viveka.coders.claude_cli import ClaudeCliCoder
    from viveka.coders.items import CITATION_RULE, CITATION_RULE_V2, CitedNumbers, CitedWork, build_items
    from viveka.coders.leakage import RULES, load_coders
    from viveka.coders.redaction import build, load_dictionaries
    from viveka.coders.tasks import load_task
    from viveka.corpus import tables
    from viveka.corpus.commands import latest_member_contexts, latest_run
    from viveka.paths import rel_posix
    from viveka.provenance import RunContext, load_manifest, recent_runs
    from viveka.registry.verify import require_frozen

    if task_id not in TASKS:
        raise CodingRefused(f"unknown task {task_id}")
    if directed_only and task_id != "T1":
        raise CodingRefused("--directed-only applies to stance (T1) only")
    case, claim, subject = load_coded(root, field_id, commitment)
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
        rule_of: dict[str, str] = {}
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
        positions_run = latest_run(root, "S1-reference-positions", subject, fold,
                                   require_frozen(root, [case.component, "thresholds"], fold))
        if positions_run is None or positions_run["params"]["member_contexts_run"] != contexts_run["run_id"]:
            raise CodingRefused(f"no reference-positions run for {subject} from member-contexts run "
                                f"{contexts_run['run_id']}; run `viveka corpus reference-positions` first")
        inputs.append(positions_run["params"]["tables"]["reference_positions"])
        found: dict[tuple[str, str], tuple[set[int], int]] = {}
        for r in tables.read(root / inputs[-1]):
            found.setdefault((r["citing_work"], r["cited_work"]), (set(), r["list_length"]))[0].add(r["position"])
        numbers = {pair: CitedNumbers(frozenset(p), n) for pair, (p, n) in found.items()}
        built, dropped = build_items(contexts, cited, build(load_dictionaries(root, [field_id])),
                                     rule=CITATION_RULE_V2, numbers=numbers)
        rules = [CITATION_RULE_V2 if r == CITATION_RULE else r for r in RULES]
        extra = {"rules": rules, "dropped": dict(dropped), "contexts": len(contexts),
                 "reference_positions_run": positions_run["run_id"]}
        if directed_only:  # D-29: stance only on contexts citing a result some coder gave a direction
            direction_run = next((m for m in recent_runs(root, limit=10_000)
                                  if m.get("stage") == "S8" and m.get("case") == subject and m.get("fold") == fold
                                  and m.get("status") == "ok" and m["params"]["task"] == "T7"
                                  and m["params"]["member_contexts_run"] == contexts_run["run_id"]), None)
            if direction_run is None:
                raise CodingRefused(f"--directed-only needs a T7 run for {subject} on member contexts "
                                    f"{contexts_run['run_id']}")
            inputs.append(direction_run["params"]["tables"]["labels"])
            directed = {r["work_id"] for r in tables.read(root / inputs[-1]) if r["label"] in ("for", "against")}
            extra.update(directed_only=True, direction_run=direction_run["run_id"], items_before_direction=len(built))
            built = [i for i in built if i.cited_work in directed]
        items = [Item(i.item_id, i.text) for i in built]
        work_of = {i.item_id: i.cited_work for i in built}
        rule_of = {i.item_id: i.rule for i in built}
        extra["items_by_rule"] = dict(Counter(rule_of.values()))
    # D-30: the items citations_v1 resolves are coded in a pass of their own, so calls made before v2 replay.
    passes = [[i for i in items if rule_of.get(i.item_id, CITATION_RULE) == rule]
              for rule in (CITATION_RULE, CITATION_RULE_V2)]
    passes = [p for p in passes if p]
    calls = sum(-(-len(p) // task.batch_size) for p in passes)
    out(f"{task_id} {subject}: {len(items)} items, {calls} call(s) per coder, coders "
        f"{', '.join(c.coder_id for c in coders)}"
        + (f"; results without an abstract {extra['results_without_abstract']}" if task_id == "T7" else
           f"; by rule {extra['items_by_rule']}; dropped {dict(extra['dropped'])}"
           + (f"; on directed results only, of {extra['items_before_direction']}" if directed_only else "")))
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
            for batch_items in passes:
                rows += label_rows(task_id, subject, coder.code(task, batch_items, seed=SEED, rep=0), work_of)
            usage[spec.coder_id] = {"live_calls": coder.live_calls, "replayed": coder.replayed,
                                    "cli_version": coder.cli_version}
        counts = Counter((r["coder_id"], r["label"] or f"missing:{r['missing']}") for r in rows)
        item_rows = [{"item_id": i.item_id, "work_id": work_of[i.item_id], "text": i.text,
                      "rule": rule_of.get(i.item_id)} for i in items]
        ctx.params.update(coder_usage=usage, label_counts={f"{c} {lab}": n for (c, lab), n in sorted(counts.items())},
                          tables={"labels": rel_posix(ctx.store(tables.to_parquet("labels", rows), "parquet",
                                                                rows=len(rows)), root),
                                  "items": rel_posix(ctx.store(tables.to_parquet("items", item_rows), "parquet",
                                                               rows=len(item_rows)), root)})
    for (coder_id, lab), n in sorted(counts.items()):
        out(f"  {coder_id}: {lab} {n}")
    out(f"run {ctx.run_id}")
    return ctx.run_id


PILOT_SEED = 20261009  # decision D-29
PILOT_DRAWS = 2000
PILOT_MIN_ITEMS = 30


def _interval(i) -> str:
    return "–" if i is None else f"{i.point:+.2f} [{i.lower:+.2f}, {i.upper:+.2f}]"


def run_pilot(root: Path, fold: str, *, out=print) -> str:
    """Stage S9-pilot (decision D-29): the descriptive pilot for every commitment with both a T7 and a T1 run on
    the same member contexts. Not a measure of the framework and never a verdict."""
    from viveka.corpus import tables
    from viveka.measures.pilot import STANCES, StanceRow, pilot
    from viveka.paths import rel_posix
    from viveka.provenance import RunContext, recent_runs

    latest: dict[tuple[str, str], dict] = {}
    for m in recent_runs(root, limit=10_000):
        if m.get("stage") == "S8" and m.get("fold") == fold and m.get("status") == "ok":
            latest.setdefault((m["case"], m["params"]["task"]), m)
    subjects = sorted(s for s, t in latest if t == "T1" and (s, "T7") in latest
                      and latest[(s, "T7")]["params"]["member_contexts_run"]
                      == latest[(s, "T1")]["params"]["member_contexts_run"])
    if not subjects:
        raise CodingRefused(f"no commitment in fold {fold} has T7 and T1 runs on the same member contexts")
    params = {"seed": PILOT_SEED, "draws": PILOT_DRAWS, "min_items": PILOT_MIN_ITEMS, "level": 0.95,
              "runs": {s: {t: latest[(s, t)]["run_id"] for t in ("T7", "T1")} for s in subjects},
              "sides": {s: latest[(s, "T1")]["params"]["side"] for s in subjects}, "result": {}}
    with RunContext(root, "S9-pilot", "calibration-fields", fold, ["prompts", "instrument", "thresholds"],
                    seed=PILOT_SEED, params=params) as ctx:
        rows = []
        lines = [f"# Pilot (D-29), {fold} fold: run `{ctx.run_id}`", "",
                 "Descriptive only: not the framework's Δ or Ω, and not a verdict. Per commitment, pooled over its "
                 "coded lineage-windows. D0 = discounted share on results against the claim minus on results for "
                 "it; A0 = accepted share on results for minus against; positive = kinder to evidence in the claim's "
                 "favour. 95% intervals resample cited results and coders.", "",
                 "| commitment | side | coder | contexts on for / against | + for / against | x for / against | "
                 "D0 [95%] | A0 [95%] |", "|---|---|---|---|---|---|---|---|"]
        for subject in subjects:
            labels = {}
            for t in ("T7", "T1"):
                path = root / latest[(subject, t)]["params"]["tables"]["labels"]
                ctx.record_input(path)
                labels[t] = tables.read(path)
            direction = {(r["coder_id"], r["work_id"]): r["label"] for r in labels["T7"] if r["label"]}
            stance = [StanceRow(r["item_id"], r["work_id"], r["coder_id"], r["label"]) for r in labels["T1"]
                      if r["label"]]
            result = pilot(stance, direction, draws=PILOT_DRAWS, seed=PILOT_SEED)
            side = params["sides"][subject]
            small = min((sum(n.values()) for n in result.items.values()), default=0) < PILOT_MIN_ITEMS
            for coder in result.coders:
                sh, n = result.shares[coder], result.items[coder]

                def pct(d, s, sh=sh):
                    return "–" if sh[d][s] is None else f"{sh[d][s]:.0%}"

                pooled = (f"{_interval(result.d0)} | {_interval(result.a0)} |" if coder == result.coders[0]
                          else " | |")
                lines.append(f"| {subject} | {side} | {coder.split(':')[-1]} | {n['for']} / {n['against']} | "
                             f"{pct('for', '+')} / {pct('against', '+')} | {pct('for', 'x')} / {pct('against', 'x')} "
                             f"| {pooled}")
                rows += [{"subject": subject, "side": side, "coder_id": coder, "direction": d, "stance": s,
                          "share": sh[d][s], "items": n[d]} for d in ("for", "against") for s in STANCES]
            for name, interval in (("D0", result.d0), ("A0", result.a0)):
                rows.append({"subject": subject, "side": side, "coder_id": "pooled", "direction": name,
                             "stance": None, "share": None if interval is None else interval.point, "items": None})
            ctx.params["result"][subject] = {
                "d0": None if result.d0 is None else [result.d0.point, result.d0.lower, result.d0.upper],
                "a0": None if result.a0 is None else [result.a0.point, result.a0.lower, result.a0.upper],
                "items": result.items, "too_small": small}
            if small:
                lines.append(f"| {subject} | | | fewer than {PILOT_MIN_ITEMS} contexts on directed results: too "
                             "small to read | | | | |")
        text = "\n".join(lines) + "\n"
        ctx.params["tables"] = {
            "pilot": rel_posix(ctx.store(tables.to_parquet("pilot", rows), "parquet", rows=len(rows)), root),
            "report": rel_posix(ctx.store(text.encode("utf-8"), "md"), root)}
    out(text)
    return ctx.run_id
