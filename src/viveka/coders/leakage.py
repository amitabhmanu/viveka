"""The leakage test (stage S6; framework, "Blinding by redaction, then tested").

Before any coding, every coder is asked to name the field from redacted items. A coder whose accuracy exceeds
chance by more than g percentage points shows that the redaction does not blind; the dictionaries are then
extended and the test repeated, and a subject that cannot be blinded is withdrawn before it is coded.

Items are drawn evenly from each subject by a seeded draw over that subject's items, so chance is one over the
number of subjects. An answer of cannot_tell is counted as not identifying the field.
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from viveka.coders.base import CoderSpec, Item, Label
from viveka.coders.items import CITATION_RULE, LANGUAGE_RULE, PROSE_RULE, RESOLVED_RULE, CitedWork, build_items
from viveka.coders.redaction import build, load_dictionaries
from viveka.corpus import tables
from viveka.provenance import recent_runs

RULES = (PROSE_RULE, LANGUAGE_RULE, CITATION_RULE, RESOLVED_RULE)


@dataclass(frozen=True)
class SubjectItems:
    subject: str
    items: list  # ContextItem
    dropped: Counter
    context_runs: list[str]


def subject_items(root: Path, field: str, fold: str, redact) -> SubjectItems:
    """Items from the newest successful context run of each of a field's commitments, cited works resolved
    from the field's newest successful fetch."""
    runs = [m for m in recent_runs(root, limit=10_000) if m.get("status") == "ok" and m.get("fold") == fold]
    fetch = next((m for m in runs if m["stage"] == "S1" and m["case"] == field), None)
    if fetch is None:
        raise ValueError(f"no successful fetch of {field} in fold {fold}")
    t = fetch["params"]["tables"]
    works = {r["work_id"]: r for r in tables.read(root / t["works"])}
    names = {r["author_id"]: r["display_name"] for r in tables.read(root / t["authors"])}
    first = {r["work_id"]: names.get(r["author_id"]) for r in tables.read(root / t["authorships"])
             if r["position"] == "first"}
    latest: dict[str, dict] = {}
    for m in runs:
        if m["stage"] == "S1-contexts" and m["case"].startswith(f"{field}-") and m["params"].get("commitment"):
            latest.setdefault(m["params"]["commitment"], m)
    rows = []
    for m in latest.values():
        rows += tables.read(root / m["params"]["tables"]["contexts"])

    def cited(work_id: str) -> CitedWork:
        name = first.get(work_id)
        return CitedWork(work_id, name.split()[-1] if name else None, (works.get(work_id) or {}).get("year"))

    items, dropped = build_items(rows, {w: cited(w) for w in {r["cited_work"] for r in rows}}, redact)
    return SubjectItems(field, items, dropped, sorted(m["run_id"] for m in latest.values()))


def draw(by_subject: Mapping[str, SubjectItems], per_subject: int, seed: int) -> list[tuple[str, Item]]:
    """(subject, item) pairs: per_subject items from each subject, by a seeded draw."""
    out = []
    for subject in sorted(by_subject):
        pool = sorted(by_subject[subject].items, key=lambda i: i.item_id)
        chosen = random.Random(f"{seed}:{subject}").sample(pool, min(per_subject, len(pool)))
        out += [(subject, Item(i.item_id, i.text)) for i in chosen]
    return out


def score(truth: Mapping[str, str], results: Sequence, subjects: Sequence[str], g_pp: float) -> dict:
    """Accuracy per coder against chance, with the confusion of true and guessed subject."""
    chance = 1 / len(subjects)
    by_coder: dict[str, dict] = defaultdict(lambda: {"n": 0, "correct": 0, "missing": 0, "confusion": Counter(),
                                                     "by_subject": defaultdict(lambda: [0, 0])})
    for r in results:
        c = by_coder[r.coder_id]
        if not isinstance(r, Label):
            c["missing"] += 1
            continue
        actual = truth[r.item_id]
        guess = r.value["guess"]
        c["n"] += 1
        hit = guess.replace("_", "-") == actual
        c["correct"] += hit
        c["confusion"][(actual, guess)] += 1
        c["by_subject"][actual][0] += hit
        c["by_subject"][actual][1] += 1
    report = {"chance": chance, "g_pp": g_pp, "coders": {}}
    for coder, c in sorted(by_coder.items()):
        accuracy = c["correct"] / c["n"] if c["n"] else None
        above = None if accuracy is None else round(100 * (accuracy - chance), 1)
        report["coders"][coder] = {
            "answered": c["n"], "missing": c["missing"], "accuracy": accuracy, "above_chance_pp": above,
            "passes": above is not None and above <= g_pp,
            "by_subject": {s: {"correct": v[0], "n": v[1]} for s, v in sorted(c["by_subject"].items())},
            "confusion": {f"{a}->{g}": n for (a, g), n in sorted(c["confusion"].items())}}
    return report


def report_markdown(run_id: str, report: dict, counts: Mapping[str, Mapping]) -> str:
    lines = [f"# Leakage test (S6): run `{run_id}`", "",
             f"Chance is {report['chance']:.0%}; a coder passes when its accuracy is at most "
             f"{report['g_pp']:g} points above it. cannot_tell counts as not identifying the field.", "",
             "| coder | answered | missing | accuracy | above chance | passes |", "|---|---:|---:|---:|---:|---|"]
    for coder, r in report["coders"].items():
        acc = "–" if r["accuracy"] is None else f"{r['accuracy']:.0%}"
        lines.append(f"| {coder} | {r['answered']} | {r['missing']} | {acc} | {r['above_chance_pp']} pp | "
                     f"{'yes' if r['passes'] else 'no'} |")
    lines += ["", "Correct per field:", ""]
    for coder, r in report["coders"].items():
        lines.append(f"- {coder}: " + ", ".join(f"{s} {v['correct']}/{v['n']}" for s, v in r["by_subject"].items()))
    lines += ["", "Items per field and drops:", ""]
    lines += [f"- {s}: {json.dumps(dict(c))}" for s, c in sorted(counts.items())]
    return "\n".join(lines) + "\n"


def load_coders(root: Path) -> list[CoderSpec]:
    data = yaml.safe_load((root / "registry" / "instrument.yaml").read_text(encoding="utf-8")) or {}
    return [CoderSpec(c["coder_id"], c["family"], c["model_id"], c["effort"]) for c in data.get("coders") or []
            if c.get("kind") == "automated"]


def run_leakage(root: Path, fields: Sequence[str], fold: str, *, per_subject: int, seed: int,
                max_live_calls: int | None = None, out=print) -> str:
    """Stage S6, leakage: draw items evenly from the fields, ask every registered coder to name the field."""
    from viveka.coders.claude_cli import ClaudeCliCoder
    from viveka.coders.tasks import load_task
    from viveka.paths import rel_posix
    from viveka.provenance import RunContext
    from viveka.registry.thresholds import load_thresholds

    g_pp = float(load_thresholds(root)["g_max_leakage_pp"])
    task = load_task(root, "T6-leakage")
    redact = build(load_dictionaries(root, fields))
    by_subject = {f: subject_items(root, f, fold, redact) for f in fields}
    drawn = draw(by_subject, per_subject, seed)
    truth = {item.item_id: subject for subject, item in drawn}
    coders = load_coders(root)
    params = {"fields": list(fields), "per_subject": per_subject, "rules": list(RULES), "task": task.task_id,
              "task_version": task.version, "batch_size": task.batch_size, "g_pp": g_pp,
              "coders": [c.coder_id for c in coders],
              "context_runs": {f: s.context_runs for f, s in by_subject.items()},
              "items_available": {f: len(s.items) for f, s in by_subject.items()},
              "dropped": {f: dict(s.dropped) for f, s in by_subject.items()}}
    components = ["prompts", "instrument", "thresholds", *(f"redaction/{f}" for f in fields)]
    with RunContext(root, "S6-leakage", "calibration-fields", fold, components, seed=seed, params=params) as ctx:
        results, usage = [], {}
        for spec in coders:
            coder = ClaudeCliCoder(spec, root / "data" / "raw" / "coders" / spec.family,
                                   max_live_calls=max_live_calls)
            results += coder.code(task, [item for _, item in drawn], seed=seed)
            usage[spec.coder_id] = {"live_calls": coder.live_calls, "replayed": coder.replayed,
                                    "cli_version": coder.cli_version}
        report = score(truth, results, [f.replace("_", "-") for f in fields], g_pp)
        rows = [{"item_id": r.item_id, "subject": truth[r.item_id], "coder_id": r.coder_id,
                 "request_id": r.request_id, "guess": r.value["guess"] if isinstance(r, Label) else None,
                 "confidence": float(r.value["confidence"]) if isinstance(r, Label) else None,
                 "missing": None if isinstance(r, Label) else r.reason} for r in results]
        path = ctx.store(tables.to_parquet("leakage", rows), "parquet", rows=len(rows))
        text = report_markdown(ctx.run_id, report, {f: {"items": len(s.items), **s.dropped}
                                                    for f, s in by_subject.items()})
        ctx.params.update(coder_usage=usage, result=report,
                          tables={"leakage": rel_posix(path, root),
                                  "report": rel_posix(ctx.store(text.encode("utf-8"), "md"), root)})
    out(text)
    return ctx.run_id
