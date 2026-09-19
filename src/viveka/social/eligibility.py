"""Gate 1 before coding (stage S4): what each lineage has in each sub-window, with no stance coded.

Framework, pilot step 3: using only the social layer, the registered events and the census, confirm that a
case has a lineage meeting m, n, v and r in the sub-windows its predictions need. Per lineage and sub-window:

* members: the size of the lineage's cluster;
* citations bearing on p: citations from works published in the sub-window with at least one member among
  their authors to the case's bearing set (seeds and event works), each work-to-work citation counted once;
* disconfirmations: registered disconfirmation events dated at least lag years before the sub-window's end
  (the n check waits for n, fitted at M8; decision D-11);
* coverage: supplied by the caller, from a census of the lineage's papers (None when not measured).

A lineage that has met v in some sub-window and stays below v in every later one is closed after its last
sub-window at or above v; later sub-windows are not scored, and are not indeterminate either.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from viveka.social.lineage import LineageStep


@dataclass(frozen=True)
class WindowCheck:
    lineage_id: str
    window_start: int
    window_end: int
    members: int
    citations_on_claim: int
    disconfirmations: int
    coverage: float | None
    closed: bool  # after the lineage's trajectory on p closed
    meets_m: bool
    meets_v: bool
    meets_r: bool | None  # None when coverage was not measured

    @property
    def eligible_pending_n(self) -> bool:
        """Every check that can be made before n is fitted passes."""
        return not self.closed and self.meets_m and self.meets_v and self.meets_r is True


def decimal_year(iso: str) -> float:
    """A registered event date as a decimal year. A partial date ("1990" or "1990-03") is read at the end of its
    period, so an event never counts as old enough before it certainly is."""
    import calendar

    parts = [int(p) for p in iso.split("-")]
    year = parts[0]
    month = parts[1] if len(parts) > 1 else 12
    day = parts[2] if len(parts) > 2 else calendar.monthrange(year, month)[1]
    return year + (date(year, month, day).timetuple().tm_yday - 1) / 365.25


def check(steps: Sequence[LineageStep], years: Mapping[str, int | None], authors: Mapping[str, tuple[str, ...]],
          citations: Iterable[tuple[str, str]], bearing: set[str], disconfirmation_dates: Sequence[str],
          m: int, v: int, r: float, lag: float,
          coverage: Mapping[tuple[str, int], float | None] | None = None) -> list[WindowCheck]:
    cites_bearing: dict[str, int] = {}
    for citing, cited in citations:
        if cited in bearing and citing != cited:
            cites_bearing[citing] = cites_bearing.get(citing, 0) + 1
    works_by_author: dict[str, list[str]] = {}
    for work, team in authors.items():
        for author in team:
            works_by_author.setdefault(author, []).append(work)
    dates = sorted(decimal_year(d) for d in disconfirmation_dates)

    raw = []
    for step in steps:
        window = step.window
        works = {w for a in step.members for w in works_by_author.get(a, ())
                 if years.get(w) is not None and window.start <= years[w] <= window.end}
        on_claim = sum(cites_bearing.get(w, 0) for w in works)
        old_enough = sum(1 for d in dates if d + lag <= window.end + 1)
        raw.append((step, on_claim, old_enough))

    last_engaged: dict[str, int] = {}
    for step, on_claim, _ in raw:
        if on_claim >= v:
            last_engaged[step.lineage_id] = max(last_engaged.get(step.lineage_id, step.window.start),
                                                step.window.start)
    out = []
    for step, on_claim, old_enough in raw:
        closed = step.lineage_id in last_engaged and step.window.start > last_engaged[step.lineage_id]
        cov = (coverage or {}).get((step.lineage_id, step.window.start))
        out.append(WindowCheck(step.lineage_id, step.window.start, step.window.end, len(step.members), on_claim,
                               old_enough, cov, closed, len(step.members) >= m, on_claim >= v,
                               None if cov is None else cov >= r))
    return out
