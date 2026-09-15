"""The coverage census (framework "Coverage census"; spec stage S2), as pure functions.

A frame's works are stratified by publication year and sampled with a generator seeded from the
registry. A sampled work is *measured* when its full reference list is known, from Crossref or a
manual import, and *unmeasured* otherwise; a reference *resolves* when its DOI is in the corpus
index. Coverage is resolved references over all references of measured works. Every frame,
community or mainstream, goes through the same code, and the census never compares coverage with
r: gate 1 does that at S4, per sub-window (spec §7).
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class FrameWork:
    work_id: str
    year: int
    doi: str | None


@dataclass(frozen=True)
class References:
    dois: tuple[str | None, ...]  # one entry per reference; None where the reference has no DOI
    source: str  # crossref or manual

    @property
    def total(self) -> int:
        return len(self.dois)


@dataclass(frozen=True)
class SampleOutcome:
    work: FrameWork
    references: References | None
    resolved: int

    @property
    def status(self) -> str:
        return "unmeasured" if self.references is None else "measured"


def stable_key(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:4], "big")


def sample_frame(case_id: str, frame_id: str, works: Iterable[FrameWork], per_year: int, seed: int) -> list[FrameWork]:
    """Up to ``per_year`` works per publication year, reproducible from the seed alone."""
    by_year: dict[int, list[FrameWork]] = defaultdict(list)
    for work in works:
        by_year[work.year].append(work)
    chosen: list[FrameWork] = []
    for year in sorted(by_year):
        pool = sorted(by_year[year], key=lambda w: w.work_id)
        if len(pool) <= per_year:
            chosen.extend(pool)
            continue
        rng = np.random.default_rng(np.random.SeedSequence(
            entropy=seed, spawn_key=(stable_key(case_id), stable_key(frame_id), year)))
        chosen.extend(pool[i] for i in sorted(rng.choice(len(pool), size=per_year, replace=False).tolist()))
    return chosen


def outcome(work: FrameWork, references: References | None, known_dois: set[str]) -> SampleOutcome:
    resolved = 0 if references is None else sum(1 for d in references.dois if d is not None and d in known_dois)
    return SampleOutcome(work, references, resolved)


def coverage_rows(case_id: str, frame_id: str, kind: str, works: Sequence[FrameWork],
                  outcomes: Sequence[SampleOutcome]) -> list[dict]:
    """One row per publication year of the frame."""
    frame_counts = Counter(w.year for w in works)
    per_year: dict[int, list[SampleOutcome]] = defaultdict(list)
    for o in outcomes:
        per_year[o.work.year].append(o)
    rows = []
    for year in sorted(frame_counts):
        sampled = per_year.get(year, [])
        measured = [o for o in sampled if o.references is not None]
        rows.append({
            "case_id": case_id, "frame_id": frame_id, "kind": kind, "year": year,
            "frame_works": frame_counts[year], "sampled": len(sampled), "measured": len(measured),
            "unmeasured": len(sampled) - len(measured),
            "refs": sum(o.references.total for o in measured if o.references is not None),
            "resolved": sum(o.resolved for o in measured),
        })
    return rows


@dataclass(frozen=True)
class Summary:
    case_id: str
    frame_id: str
    kind: str
    frame_works: int
    sampled: int
    measured: int
    unmeasured: int
    refs: int
    resolved: int
    coverage: float | None
    unmeasured_share: float | None
    measurable: bool


def summarize(rows: Iterable[dict], max_unmeasured_share: float) -> list[Summary]:
    """Coverage per frame over the given rows (pass one frame-year's row for a per-year reading)."""
    totals: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
    for row in rows:
        totals[(row["case_id"], row["frame_id"], row["kind"])].update(
            {k: row[k] for k in ("frame_works", "sampled", "measured", "unmeasured", "refs", "resolved")})
    summaries = []
    for (case_id, frame_id, kind), t in sorted(totals.items()):
        coverage = t["resolved"] / t["refs"] if t["refs"] else None
        share = t["unmeasured"] / t["sampled"] if t["sampled"] else None
        measurable = coverage is not None and share is not None and share <= max_unmeasured_share
        summaries.append(Summary(case_id, frame_id, kind, t["frame_works"], t["sampled"], t["measured"],
                                 t["unmeasured"], t["refs"], t["resolved"], coverage, share, measurable))
    return summaries
