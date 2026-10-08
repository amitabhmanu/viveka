"""Cluster frames for the census (stage S2C).

The framework takes the coverage census per cluster: "for every candidate field and every cluster in it, a
random sample of the community's papers is drawn from its own venues". Clusters arrive only at S3, so until
M5 the census unit was a registered frame; at M5 the same census code runs again with cluster frames, and
S4 aggregates each frame's years into its sub-window (spec §7).

A cluster frame is one lineage's cluster in one sub-window, holding the papers published in that sub-window
by the cluster's members. Only the lineage-windows gate 1 still needs are framed: those meeting m and v and
not closed, since coverage can withhold eligibility but never grant it, and S4 reports every other window as
ineligible without reading coverage at all. The sample inside a frame is the registered seeded draw, so the
scoping changes which literatures are measured, never how one is measured.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping, Sequence

KIND = "cluster"
SEPARATOR = "@"


def frame_id(lineage_id: str, window_start: int) -> str:
    return f"{lineage_id}{SEPARATOR}{window_start}"


def split_frame(frame: str) -> tuple[str, int]:
    """The lineage and sub-window start a cluster frame stands for."""
    lineage_id, _, start = frame.rpartition(SEPARATOR)
    return lineage_id, int(start)


def needed_windows(eligibility_rows: Iterable[Mapping], resolution: float) -> list[tuple[str, int, int]]:
    """(lineage, window start, window end) for the rows meeting m and v at the resolution and not closed."""
    ends: dict[tuple[str, int], int] = {}
    for row in eligibility_rows:
        if (abs(float(row["resolution"]) - resolution) < 1e-9 and row["meets_m"] and row["meets_v"]
                and not row["closed"]):
            ends[(row["lineage_id"], int(row["window_start"]))] = int(row["window_end"])
    return sorted((lineage, start, end) for (lineage, start), end in ends.items())


def first_windows(needed: Sequence[tuple[str, int, int]], subject: str, seed: int,
                  count: int) -> list[tuple[str, int, int]]:
    """Decision D-31: the first ``count`` windows of a seeded order over the needed ones, sorted. The order is a
    property of the subject and the seed alone, so asking for one more window adds one and keeps the rest: a
    window that fails coverage is replaced by the next in the order."""
    if count < 1:
        raise ValueError("at least one window")
    ordered = sorted(needed)
    return sorted(random.Random(f"{seed}:{subject}").sample(ordered, len(ordered))[:count])


def cluster_frames(case_id: str, needed: Sequence[tuple[str, int, int]],
                   members: Mapping[tuple[str, int], frozenset[str]],
                   works_by_author: Mapping[str, Sequence[str]],
                   years: Mapping[str, int | None]) -> list[dict]:
    """Frame rows (the shape S1 writes) for each needed lineage-window: the cluster's papers in that window."""
    rows: list[dict] = []
    for lineage_id, start, end in needed:
        works = {work for author in members.get((lineage_id, start), frozenset())
                 for work in works_by_author.get(author, ())
                 if years.get(work) is not None and start <= years[work] <= end}
        frame = frame_id(lineage_id, start)
        rows += [{"case_id": case_id, "frame_id": frame, "work_id": work, "kind": KIND, "year": years[work]}
                 for work in sorted(works)]
    return rows


def coverage_by_window(summaries: Iterable) -> dict[tuple[str, int], float | None]:
    """Each lineage-window's coverage from its cluster frame's census summary (None when not measurable)."""
    return {split_frame(s.frame_id): (s.coverage if s.measurable else None) for s in summaries}
