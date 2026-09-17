"""Case definitions, calibration fields and claims from the registry.

``cases/<case>`` names a claim (``events/<claim>``), seed works and frames. ``fields/<field>`` (M4b) names only
the venues of a calibration field; its commitments are registered later, so a field has no claim and no seeds.
Both load as a ``Case`` so the corpus and census stages treat them alike.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from viveka.corpus.ids import normalize_doi
from viveka.paths import REGISTRY
from viveka.registry.validate import validate


class CaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkRef:
    openalex: str | None
    doi: str | None
    note: str | None = None

    @property
    def key(self) -> str:
        return self.openalex or self.doi or ""


@dataclass(frozen=True)
class Frame:
    frame_id: str
    kind: str  # community or mainstream
    cites_seeds: bool
    sources: tuple[str, ...]
    ingest: tuple[str, ...] = ()  # community venues ingested from their own archives


@dataclass(frozen=True)
class Event:
    event_id: str
    date: str
    kind: str
    works: tuple[WorkRef, ...]
    note: str
    source: str


@dataclass(frozen=True)
class Claim:
    claim_id: str
    wording: str
    events: tuple[Event, ...]


@dataclass(frozen=True)
class Case:
    case_id: str
    claim: str | None  # None for a calibration field
    role: str  # pilot, reserve or calibration
    pair: str  # the case's pair; a field's side (science or pseudoscience)
    start: int
    end: int
    seeds: tuple[WorkRef, ...]
    frames: tuple[Frame, ...]
    is_field: bool = False
    absent_venues: tuple[str, ...] = ()  # a field's core venues that are not in the corpus source

    @property
    def component(self) -> str:
        return f"{'fields' if self.is_field else 'cases'}/{self.case_id}"


def _ref(entry: dict) -> WorkRef:
    return WorkRef(entry.get("openalex"), normalize_doi(entry.get("doi")), entry.get("note"))


def _load(root: Path, component: str) -> dict:
    path = root / REGISTRY / f"{component}.yaml"
    if not path.is_file():
        raise CaseError(f"no {REGISTRY}/{component}.yaml")
    problems = validate(root, [component])
    if problems:
        raise CaseError("; ".join(problems))
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_claim(root: Path, claim_id: str) -> Claim:
    data = _load(root, f"events/{claim_id}")
    events = tuple(Event(e["id"], str(e["date"]), e["kind"], tuple(_ref(w) for w in e["works"]), e["note"],
                         e["source"]) for e in data["events"])
    return Claim(data["claim"], data["wording"], events)


def load_case(root: Path, case_id: str) -> tuple[Case, Claim]:
    data = _load(root, f"cases/{case_id}")
    problems = validate(root, ["corpus"])
    if problems:
        raise CaseError("; ".join(problems))
    frames = tuple(Frame(f["id"], f["kind"], f.get("cites") == "seeds", tuple(f.get("sources") or ()),
                         tuple(f.get("ingest") or ())) for f in data["frames"])
    case = Case(data["case"], data["claim"], data["role"], data["pair"], int(data["window"]["start"]),
                int(data["window"]["end"]), tuple(_ref(s) for s in data["seeds"]), frames)
    return case, load_claim(root, case.claim)


def load_field(root: Path, field_id: str) -> Case:
    data = _load(root, f"fields/{field_id}")
    problems = validate(root, ["corpus"])
    if problems:
        raise CaseError("; ".join(problems))
    frames = tuple(Frame(f["id"], f["kind"], False, tuple(f.get("sources") or ()), tuple(f.get("ingest") or ()))
                   for f in data["frames"])
    absent = tuple(f"{v['name']}" + (f" (ISSN-L {v['issn_l']})" if v.get("issn_l") else "") + f": {v['note']}"
                   for v in data["absent_venues"])
    return Case(data["field"], None, data["role"], data["side"], int(data["window"]["start"]),
                int(data["window"]["end"]), (), frames, is_field=True, absent_venues=absent)


def load_subject(root: Path, subject_id: str, is_field: bool) -> tuple[Case, Claim | None]:
    """A case with its claim, or a calibration field (no claim)."""
    return (load_field(root, subject_id), None) if is_field else load_case(root, subject_id)


def bearing_set(case: Case, claim: Claim | None) -> tuple[WorkRef, ...]:
    """The seeds and every event's works, first occurrence kept: the works citations bearing on p point to."""
    seen: set[str] = set()
    refs = []
    events = claim.events if claim is not None else ()
    for ref in (*case.seeds, *(w for e in events for w in e.works)):
        if ref.key not in seen:
            seen.add(ref.key)
            refs.append(ref)
    return tuple(refs)
