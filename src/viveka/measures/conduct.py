"""Measures of conduct toward people and networks: τ (tie retention), H (honoured rate), χ (engagement)."""

from __future__ import annotations

from collections.abc import Sequence

from viveka.measures.types import TieEvent


def retention(events: Sequence[TieEvent]) -> float | None:
    before = sum(e.ties_before for e in events)
    if before == 0:
        return None
    return sum(e.ties_kept for e in events) / before


def tau(qualifying_breaks: Sequence[TieEvent], baseline_changes: Sequence[TieEvent]) -> float | None:
    """Retention after qualifying breaks relative to retention after other changes of position. Near 1 is healthy."""
    after_breaks = retention(qualifying_breaks)
    baseline = retention(baseline_changes)
    if after_breaks is None or baseline is None or baseline == 0:
        return None
    return after_breaks / baseline


def honoured_share(conditions_honoured: Sequence[bool]) -> float | None:
    if not conditions_honoured:
        return None
    return sum(conditions_honoured) / len(conditions_honoured)


def chi(citations_out: int, citations_total: int, coverage: float, r: float) -> float | None:
    """Share of the cluster's citations that leave it; not measurable below coverage r (a missing
    literature looks exactly like detachment). Describes the network, never enters the gates."""
    if coverage < r or citations_total <= 0:
        return None
    return citations_out / citations_total
