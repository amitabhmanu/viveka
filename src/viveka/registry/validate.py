"""Registry validation, and the extra preconditions a freeze requires.

``validate`` checks structure: syntax, JSON Schemas, orphan files, and
cross-references. ``freeze_problems`` adds what freezing needs on top: no
unset values, provenance for fitted and simulated values, non-empty
components, content that differs from what is already frozen, and frozen
upstream components.

Events and cases have registered formats from M4a. Formats for filters, predictions
and redaction arrive with their milestones (M5-M7); until then a file there only has
to be a YAML mapping with a ``format`` key (and filters a ``claim`` naming an events
component).
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml

from viveka.paths import REGISTRY, RUNS
from viveka.registry import components as comp
from viveka.registry.errors import UnknownComponent
from viveka.registry.thresholds import FITTED_PARAMETERS, THRESHOLD_PARAMETERS

SCHEMA_DIR = "registry/schemas"


def validate(root: Path, names: list[str] | None = None) -> list[str]:
    """Problems found; an empty list means the checked components are valid."""
    problems = [f"{rel}: belongs to no registry component" for rel in comp.orphans(root)]
    discovered = comp.discover(root)

    if names is None:
        targets = sorted(set(discovered) | set(comp.SINGLE_FILES))
    else:
        targets = []
        for name in names:
            try:
                comp.validate_name(name)
            except UnknownComponent as exc:
                problems.append(str(exc))
                continue
            targets.append(name)

    for name in targets:
        files = discovered.get(name, [])
        if name in comp.SINGLE_FILES and not files:
            problems.append(f"{comp.SINGLE_FILES[name]}: required file is missing")
            continue
        kind = name.split("/")[0]
        checker = _CHECKERS.get(kind)
        for rel in files:
            problems.extend(checker(root, rel) if checker else [])
    return problems


def freeze_problems(root: Path, names: list[str], manifest: dict) -> list[str]:
    """Why these components cannot be frozen now; empty means they can."""
    problems = validate(root, names)
    frozen = manifest["components"]
    for name in names:
        try:
            comp.validate_name(name)
        except UnknownComponent:
            continue  # already reported by validate
        current = comp.component_hash(root, name)
        if current is None:
            problems.append(f"{name}: component has no files to freeze")
            continue
        if name in frozen and frozen[name]["sha256"] == current:
            problems.append(f"{name}: already frozen with identical content (version {frozen[name]['frozen_in']})")
        for upstream in comp.with_upstream(root, [name]):
            if upstream != name and upstream not in frozen and upstream not in names:
                problems.append(f"{name}: upstream component {upstream} is not frozen")
        if name == "thresholds":
            problems.extend(_parameters_complete(root, "thresholds", THRESHOLD_PARAMETERS))
        if name == "fitted":
            problems.extend(_parameters_complete(root, "fitted", FITTED_PARAMETERS))
    return problems


# ---------------------------------------------------------------- per-kind checks


def _load_yaml(root: Path, rel: str) -> tuple[object, list[str]]:
    try:
        return yaml.safe_load((root / rel).read_text(encoding="utf-8")), []
    except (OSError, yaml.YAMLError) as exc:
        return None, [f"{rel}: not readable as YAML ({exc})"]


def _schema(root: Path, name: str) -> dict | None:
    path = root / SCHEMA_DIR / f"{name}.schema.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _against_schema(root: Path, rel: str, data: object, schema_name: str) -> list[str]:
    schema = _schema(root, schema_name)
    if schema is None:
        return [f"{rel}: schema {SCHEMA_DIR}/{schema_name}.schema.json is missing"]
    validator = jsonschema.Draft202012Validator(schema)
    return [f"{rel}: {'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
            for e in sorted(validator.iter_errors(data), key=str)]


def _check_thresholds(root: Path, rel: str) -> list[str]:
    return _check_parameters(root, rel, "thresholds", THRESHOLD_PARAMETERS)


def _check_fitted(root: Path, rel: str) -> list[str]:
    return _check_parameters(root, rel, "fitted", FITTED_PARAMETERS)


def _check_parameters(root: Path, rel: str, schema_name: str, names: tuple[str, ...]) -> list[str]:
    data, problems = _load_yaml(root, rel)
    if problems:
        return problems
    problems = _against_schema(root, rel, data, schema_name)
    schema = _schema(root, schema_name)
    if schema is not None:
        required = schema.get("properties", {}).get("parameters", {}).get("required", [])
        if list(required) != list(names):
            problems.append(f"{rel}: schema's required parameters differ from the code's parameter list")
    params = data.get("parameters", {}) if isinstance(data, dict) else {}
    for pname, entry in (params or {}).items():
        run = entry.get("source_run") if isinstance(entry, dict) else None
        if run and not (root / RUNS / str(run) / "manifest.json").is_file():
            problems.append(f"{rel}: {pname}.source_run {run!r} has no manifest in {RUNS}/")
    return problems


def _check_instrument(root: Path, rel: str) -> list[str]:
    data, problems = _load_yaml(root, rel)
    return problems or _against_schema(root, rel, data, "instrument")


def _check_simulation(root: Path, rel: str) -> list[str]:
    data, problems = _load_yaml(root, rel)
    if problems:
        return problems
    problems = _against_schema(root, rel, data, "simulation")
    if not problems:
        for name, profile in data["profiles"].items():
            for mix in ("ledger", "rounds"):
                total = sum(profile[mix].values())
                if abs(total - 1.0) > 1e-9:
                    problems.append(f"{rel}: profiles.{name}.{mix} probabilities sum to {total}, not 1")
    return problems


def _check_corpus(root: Path, rel: str) -> list[str]:
    data, problems = _load_yaml(root, rel)
    return problems or _against_schema(root, rel, data, "corpus")


def _duplicates(values: list[str]) -> list[str]:
    return sorted({v for v in values if values.count(v) > 1})


def _unknown_venues(root: Path, rel: str, frames: list[dict]) -> list[str]:
    """Frames may only ingest venues that the corpus settings register."""
    wanted = sorted({v for f in frames for v in f.get("ingest") or ()})
    if not wanted:
        return []
    try:
        corpus = yaml.safe_load((root / comp.SINGLE_FILES["corpus"]).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return [f"{rel}: ingested venues need a readable {comp.SINGLE_FILES['corpus']}"]
    known = set((corpus.get("ingestion") or {}).get("venues") or {})
    return [f"{rel}: ingested venue {v!r} is not registered in {comp.SINGLE_FILES['corpus']}"
            for v in wanted if v not in known]


def _check_events(root: Path, rel: str) -> list[str]:
    data, problems = _load_yaml(root, rel)
    if problems:
        return problems
    problems = _against_schema(root, rel, data, "events")
    if problems:
        return problems
    stem = Path(rel).stem
    if data["claim"] != stem:
        problems.append(f"{rel}: claim {data['claim']!r} must match the file name {stem!r}")
    dupes = _duplicates([e["id"] for e in data["events"]])
    if dupes:
        problems.append(f"{rel}: duplicate event ids: {', '.join(dupes)}")
    return problems


def _check_cases(root: Path, rel: str) -> list[str]:
    data, problems = _load_yaml(root, rel)
    if problems:
        return problems
    problems = _against_schema(root, rel, data, "cases")
    if problems:
        return problems
    stem = Path(rel).stem
    if data["case"] != stem:
        problems.append(f"{rel}: case {data['case']!r} must match the file name {stem!r}")
    if data["window"]["start"] > data["window"]["end"]:
        problems.append(f"{rel}: window starts after it ends")
    if not (root / REGISTRY / "events" / f"{data['claim']}.yaml").is_file():
        problems.append(f"{rel}: claim {data['claim']!r} has no registry/events/{data['claim']}.yaml")
    dupes = _duplicates([f["id"] for f in data["frames"]])
    if dupes:
        problems.append(f"{rel}: duplicate frame ids: {', '.join(dupes)}")
    problems += _unknown_venues(root, rel, data["frames"])
    return problems


def _check_fields(root: Path, rel: str) -> list[str]:
    data, problems = _load_yaml(root, rel)
    if problems:
        return problems
    problems = _against_schema(root, rel, data, "fields")
    if problems:
        return problems
    stem = Path(rel).stem
    if data["field"] != stem:
        problems.append(f"{rel}: field {data['field']!r} must match the file name {stem!r}")
    if not data["frames"] and not data["absent_venues"]:
        problems.append(f"{rel}: a field with no frames must list its absent venues")
    if data["window"]["start"] > data["window"]["end"]:
        problems.append(f"{rel}: window starts after it ends")
    dupes = _duplicates([f["id"] for f in data["frames"]])
    if dupes:
        problems.append(f"{rel}: duplicate frame ids: {', '.join(dupes)}")
    problems += _unknown_venues(root, rel, data["frames"])
    commitments = data.get("commitments") or []
    dupes = _duplicates([c["id"] for c in commitments])
    if dupes:
        problems.append(f"{rel}: duplicate commitment ids: {', '.join(dupes)}")
    for c in commitments:
        if not (root / REGISTRY / "events" / f"{c['claim']}.yaml").is_file():
            problems.append(f"{rel}: commitment {c['id']}: claim {c['claim']!r} has no "
                            f"{REGISTRY}/events/{c['claim']}.yaml")
    return problems


def _check_schema_file(root: Path, rel: str) -> list[str]:
    if not rel.endswith(".schema.json"):
        return [f"{rel}: files in {SCHEMA_DIR}/ must be named <name>.schema.json"]
    try:
        schema = json.loads((root / rel).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
    except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
        return [f"{rel}: not a valid JSON Schema ({exc})"]
    return []


def _check_codebook(root: Path, rel: str) -> list[str]:
    if rel.endswith((".yaml", ".yml")):
        return _load_yaml(root, rel)[1]
    return []


PROMPT_DIR = "registry/prompts"


def _check_prompt(root: Path, rel: str) -> list[str]:
    # A coding task's label schema lives beside its prompt (decision D-23): schemas/ is upstream of every
    # registry component, so a task schema there would make every corpus and census run stale.
    if rel.endswith(".schema.json"):
        try:
            schema = json.loads((root / rel).read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator.check_schema(schema)
        except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
            return [f"{rel}: not a valid JSON Schema ({exc})"]
        return []
    text = (root / rel).read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---" not in text[4:]:
        return [f"{rel}: prompt must begin with YAML front matter naming its schema"]
    front = text[4 : 4 + text[4:].index("\n---")]
    try:
        meta = yaml.safe_load(front) or {}
    except yaml.YAMLError as exc:
        return [f"{rel}: front matter is not valid YAML ({exc})"]
    schema_name = meta.get("schema") if isinstance(meta, dict) else None
    if not schema_name:
        return [f"{rel}: front matter has no 'schema'"]
    if not (root / PROMPT_DIR / f"{schema_name}.schema.json").is_file():
        return [f"{rel}: names schema {schema_name!r}, but {PROMPT_DIR}/{schema_name}.schema.json does not exist"]
    return []


def _check_per_file(root: Path, rel: str) -> list[str]:
    data, problems = _load_yaml(root, rel)
    if problems:
        return problems
    if not isinstance(data, dict) or "format" not in data:
        return [f"{rel}: must be a YAML mapping with a 'format' key"]
    if rel.startswith(f"{REGISTRY}/filters/"):
        claim = data.get("claim")
        if not claim:
            return [f"{rel}: filter list must name its 'claim'"]
        if not (root / REGISTRY / "events" / f"{claim}.yaml").is_file():
            return [f"{rel}: claim {claim!r} has no registry/events/{claim}.yaml"]
    return []


_CHECKERS = {
    "thresholds": _check_thresholds,
    "fitted": _check_fitted,
    "instrument": _check_instrument,
    "simulation": _check_simulation,
    "corpus": _check_corpus,
    "schemas": _check_schema_file,
    "codebook": _check_codebook,
    "prompts": _check_prompt,
    "events": _check_events,
    "cases": _check_cases,
    "fields": _check_fields,
    "filters": _check_per_file,
    "predictions": _check_per_file,
    "redaction": _check_per_file,
}


def _parameters_complete(root: Path, component: str, names: tuple[str, ...]) -> list[str]:
    from viveka.registry.thresholds import load_thresholds

    try:
        thresholds = load_thresholds(root)
    except Exception as exc:  # noqa: BLE001 - reported as a freeze problem
        return [f"{component}: {exc}"]
    problems = [f"{component}: {name} has no value" for name in thresholds.unset() if name in names]
    for name in names:
        p = thresholds.parameter(name)
        if p.status in ("fitted", "simulated") and not p.source_run:
            problems.append(f"{component}: {name} is {p.status} but has no source_run")
    return problems
