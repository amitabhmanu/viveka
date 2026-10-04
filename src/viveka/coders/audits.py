"""Coder audits (stage S7; framework, "Coders are instruments"; spec section 8, Audits).

* Test-retest: every coder codes the anchor set twice, in different batches (base.batches shuffles by
  repetition), and the share of items whose label differs is its own inconsistency. Recorded, not gated.
* Symmetry: the same passages are coded twice, once headed by the citing paper's true research area and once by
  an area from the other side of the science/pseudoscience line. A coder whose labels change on a share of pairs
  greater than its test-retest share by more than s is removed before coding. The coders can name the field
  from the text alone (D-25), so this is the audit that guards against field-based bias: it asks whether being
  told that a passage comes from a pseudoscience, or from a science, changes how it is coded.
* Agreement: Cohen's kappa on "discounted" (x) against every other label, for every pair of coders, on the
  anchor set's first repetition. With no human labels (D-3) it is measured between models only (D-21).

Every function here is pure; ``run_audits`` is the stage.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from itertools import combinations

from viveka.coders.base import Item, Label

AREAS = {"homeopathy": "homeopathy", "chiropractic": "chiropractic", "plate-tectonics": "plate tectonics",
         "molecular-genetics": "molecular genetics", "thermodynamics": "thermodynamics"}
HEADER = "Research area of the citing paper: {area}.\n"


def exchanged_pairs(drawn: Sequence[tuple[str, Item]], sides: Mapping[str, str], seed: int
                    ) -> tuple[list[Item], dict[str, dict]]:
    """Two items per drawn passage, headed by its true area and by an area of the other side, chosen by a seeded
    draw; returns the items and, by pair id, the subject, the area each version names, and the side swapped to."""
    items, pairs = [], {}
    rng = random.Random(f"pairs:{seed}")
    for subject, item in drawn:
        other = sorted(s for s in sides if sides[s] != sides[subject])
        swapped = rng.choice(other)
        for version, area in (("true", subject), ("swapped", swapped)):
            items.append(Item(f"{item.item_id}#{version}", HEADER.format(area=AREAS[area]) + item.text))
        pairs[item.item_id] = {"subject": subject, "side": sides[subject], "swapped_to": swapped}
    return items, pairs


def label_of(result) -> str | None:
    return result.value["label"] if isinstance(result, Label) else None


def retest_share(first: Sequence, second: Sequence) -> dict[str, dict]:
    """Per coder: items labelled both times, and the share whose label differs."""
    by: dict[tuple[str, str], list] = defaultdict(lambda: [None, None])
    for index, results in enumerate((first, second)):
        for r in results:
            by[(r.coder_id, r.item_id)][index] = label_of(r)
    out: dict[str, dict] = defaultdict(lambda: {"pairs": 0, "changed": 0})
    for (coder, _), (a, b) in by.items():
        if a is not None and b is not None:
            out[coder]["pairs"] += 1
            out[coder]["changed"] += a != b
    return {c: {**v, "share": v["changed"] / v["pairs"] if v["pairs"] else None} for c, v in sorted(out.items())}


def symmetry(results: Sequence, pairs: Mapping[str, dict], retest: Mapping[str, dict], s: float) -> dict[str, dict]:
    """Per coder: share of pairs whose label changed with the stated area, the excess over its test-retest share,
    whether it passes, and which way discounts moved when a passage was presented as from a pseudoscience."""
    labels: dict[tuple[str, str], dict] = defaultdict(dict)
    for r in results:
        base, _, version = r.item_id.partition("#")
        labels[(r.coder_id, base)][version] = label_of(r)
    out: dict[str, dict] = defaultdict(lambda: {"pairs": 0, "changed": 0, "more_x_as_pseudoscience": 0,
                                                "fewer_x_as_pseudoscience": 0})
    for (coder, base), v in labels.items():
        a, b = v.get("true"), v.get("swapped")
        if a is None or b is None:
            continue
        o = out[coder]
        o["pairs"] += 1
        o["changed"] += a != b
        # Label under the pseudoscience header against the label under the science header.
        as_pseudo, as_science = (a, b) if pairs[base]["side"] == "pseudoscience" else (b, a)
        if as_pseudo == "x" and as_science != "x":
            o["more_x_as_pseudoscience"] += 1
        elif as_science == "x" and as_pseudo != "x":
            o["fewer_x_as_pseudoscience"] += 1
    report = {}
    for coder, o in sorted(out.items()):
        share = o["changed"] / o["pairs"] if o["pairs"] else None
        base_share = (retest.get(coder) or {}).get("share")
        excess = None if share is None or base_share is None else share - base_share
        report[coder] = {**o, "share": share, "retest_share": base_share, "excess": excess,
                         "passes": excess is not None and excess <= s}
    return report


def kappa(a: Sequence[bool], b: Sequence[bool]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pa, pb = sum(a) / n, sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def discount_agreement(results: Sequence) -> dict[str, dict]:
    """Cohen's kappa on 'x' against all other labels, for each pair of coders, over items both labelled."""
    by: dict[str, dict[str, str]] = defaultdict(dict)
    for r in results:
        if label_of(r) is not None:
            by[r.coder_id][r.item_id] = label_of(r)
    out = {}
    for c1, c2 in combinations(sorted(by), 2):
        common = sorted(set(by[c1]) & set(by[c2]))
        out[f"{c1} | {c2}"] = {"items": len(common),
                               "kappa": kappa([by[c1][i] == "x" for i in common], [by[c2][i] == "x" for i in common]),
                               "x_shares": [sum(by[c][i] == "x" for i in common) / len(common) if common else None
                                            for c in (c1, c2)]}
    return out


def run_audits(root, fields: Sequence[str], fold: str, *, anchor_per_subject: int, pairs_per_subject: int,
               seed: int, max_live_calls: int | None = None, out=print) -> str:
    """Stage S7: test-retest and agreement on an anchor set, and the symmetry audit on exchanged pairs, for every
    registered coder, with stance task T1."""
    import yaml

    from viveka.coders.claude_cli import ClaudeCliCoder
    from viveka.coders.leakage import RULES, SubjectItems, draw, load_coders, subject_items
    from viveka.coders.redaction import build, load_dictionaries
    from viveka.coders.tasks import load_task
    from viveka.corpus import tables
    from viveka.paths import rel_posix
    from viveka.provenance import RunContext
    from viveka.registry.thresholds import load_thresholds

    thresholds = load_thresholds(root)
    s, kappa_min, q = (float(thresholds["s_max_label_change_share"]), float(thresholds["kappa_min"]),
                       int(thresholds["q_min_coders"]))
    task = load_task(root, "T1-stance")
    sides = {f: yaml.safe_load((root / "registry" / "fields" / f"{f}.yaml").read_text(encoding="utf-8"))["side"]
             for f in fields}
    redact = build(load_dictionaries(root, fields))
    by_subject = {f: subject_items(root, f, fold, redact) for f in fields}
    anchor = draw(by_subject, anchor_per_subject, seed)
    anchored = {item.item_id for _, item in anchor}
    rest = {f: SubjectItems(v.subject, [i for i in v.items if i.item_id not in anchored], v.dropped,
                            v.context_runs) for f, v in by_subject.items()}
    pair_items, pairs = exchanged_pairs(draw(rest, pairs_per_subject, seed + 1), sides, seed)
    coders = load_coders(root)
    params = {"fields": list(fields), "sides": sides, "rules": list(RULES), "task": task.task_id,
              "task_version": task.version, "batch_size": task.batch_size,
              "anchor_per_subject": anchor_per_subject, "pairs_per_subject": pairs_per_subject,
              "s": s, "kappa_min": kappa_min, "q": q, "coders": [c.coder_id for c in coders],
              "context_runs": {f: v.context_runs for f, v in by_subject.items()},
              "items_available": {f: len(v.items) for f, v in by_subject.items()},
              "dropped": {f: dict(v.dropped) for f, v in by_subject.items()}}
    components = ["prompts", "instrument", "thresholds", *(f"redaction/{f}" for f in fields),
                  *(f"fields/{f}" for f in fields)]
    subject_of = {item.item_id: subject for subject, item in anchor}
    with RunContext(root, "S7-audits", "calibration-fields", fold, components, seed=seed, params=params) as ctx:
        first, second, swapped, usage = [], [], [], {}
        for spec in coders:
            coder = ClaudeCliCoder(spec, root / "data" / "raw" / "coders" / spec.family,
                                   max_live_calls=max_live_calls)
            anchor_items = [item for _, item in anchor]
            first += coder.code(task, anchor_items, seed=seed, rep=0)
            second += coder.code(task, anchor_items, seed=seed, rep=1)
            swapped += coder.code(task, pair_items, seed=seed, rep=0)
            usage[spec.coder_id] = {"live_calls": coder.live_calls, "replayed": coder.replayed,
                                    "cli_version": coder.cli_version}
        retest = retest_share(first, second)
        sym = symmetry(swapped, pairs, retest, s)
        agreement = discount_agreement(first)
        qualified = sorted(c for c, r in sym.items() if r["passes"])
        pool_kappa = [v["kappa"] for k, v in agreement.items()
                      if all(c in qualified for c in k.split(" | ")) and v["kappa"] is not None]
        result = {"retest": retest, "symmetry": sym, "agreement": agreement, "qualified": qualified,
                  "pool_qualifies": len(qualified) >= q and bool(pool_kappa) and min(pool_kappa) >= kappa_min}
        rows = []
        for kind, results in (("anchor_rep0", first), ("anchor_rep1", second), ("pairs", swapped)):
            for r in results:
                base = r.item_id.partition("#")[0]
                rows.append({"kind": kind, "item_id": r.item_id, "coder_id": r.coder_id, "rep": r.rep,
                             "subject": subject_of.get(base) or pairs.get(base, {}).get("subject"),
                             "label": label_of(r),
                             "reason_span": r.value.get("reason_span") if isinstance(r, Label) else None,
                             "missing": None if isinstance(r, Label) else r.reason})
        path = ctx.store(tables.to_parquet("audits", rows), "parquet", rows=len(rows))
        text = audit_markdown(ctx.run_id, result, s, kappa_min, q)
        ctx.params.update(coder_usage=usage, result=result,
                          tables={"audits": rel_posix(path, root),
                                  "report": rel_posix(ctx.store(text.encode("utf-8"), "md"), root)})
    out(text)
    return ctx.run_id


def _pct(x) -> str:
    return "–" if x is None else f"{x:.1%}"


def audit_markdown(run_id: str, result: dict, s: float, kappa_min: float, q: int) -> str:
    lines = [f"# Coder audits (S7): run `{run_id}`", "",
             "Coders could name the field from the text alone (leakage failed, D-25); the symmetry audit is the "
             "guard against field-based bias. Agreement is between models only (D-3, D-21).", "",
             f"| coder | test-retest change | symmetry change | excess | passes (s = {s:g}) | "
             "more x when called pseudoscience | fewer x |", "|---|---:|---:|---:|---|---:|---:|"]
    for coder, r in result["symmetry"].items():
        lines.append(f"| {coder} | {_pct(r['retest_share'])} | {_pct(r['share'])} ({r['changed']}/{r['pairs']}) | "
                     f"{_pct(r['excess'])} | {'yes' if r['passes'] else 'no'} | {r['more_x_as_pseudoscience']} | "
                     f"{r['fewer_x_as_pseudoscience']} |")
    lines += ["", f"| coder pair | items | kappa on discounts (min {kappa_min:g}) | discount shares |",
              "|---|---:|---:|---|"]
    for pair, v in result["agreement"].items():
        k = "–" if v["kappa"] is None else f"{v['kappa']:.2f}"
        lines.append(f"| {pair} | {v['items']} | {k} | {', '.join(_pct(x) for x in v['x_shares'])} |")
    verdict = ("qualifies" if result["pool_qualifies"]
               else f"does not qualify (needs {q} coders and kappa of at least {kappa_min:g} between them)")
    lines += ["", f"Qualified coders: {', '.join(result['qualified']) or 'none'}. The pool {verdict}."]
    return "\n".join(lines) + "\n"
