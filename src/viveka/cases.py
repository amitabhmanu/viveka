"""Case definitions and claims from the registry: ``cases/<case>`` and ``events/<claim>``."""

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
    claim: str
    role: str
    pair: str
    start: int
    end: int
    seeds: tuple[WorkRef, ...]
    frames: tuple[Frame, ...]


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
    frames = tuple(Frame(f["id"], f["kind"], f.get("cites") == "seeds", tuple(f.get("sources") or ()))
                   for f in data["frames"])
    case = Case(data["case"], data["claim"], data["role"], data["pair"], int(data["window"]["start"]),
                int(data["window"]["end"]), tuple(_ref(s) for s in data["seeds"]), frames)
    return case, load_claim(root, case.claim)


def bearing_set(case: Case, claim: Claim) -> tuple[WorkRef, ...]:
    """The seeds and every event's works, first occurrence kept: the works citations bearing on p point to."""
    seen: set[str] = set()
    refs = []
    for ref in (*case.seeds, *(w for e in claim.events for w in e.works)):
        if ref.key not in seen:
            seen.add(ref.key)
            refs.append(ref)
    return tuple(refs)
