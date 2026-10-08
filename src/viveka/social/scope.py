"""What the first calibration coding covers (decision D-28): which lineage-windows, and which citations in them.

* ``windows_v1``: every eligible lineage-window (S4, primary resolution, eligible pending n) of a pseudoscience
  commitment; for a science commitment, and for a contested case (decision D-31), ``per_science`` of them drawn
  by ``random.Random(f"{seed}:{subject}").sample`` over the sorted eligible windows. Each window is coded whole.
* the citations of a window: every citation from a paper credited to the window's members (the ``lineage_works``
  rule, published within the window) to a result bearing on the claim, the quantity S4 counts toward v.

Pure functions over table rows; the stage that fetches contexts for these citations is in viveka.corpus.commands.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping, Sequence

WINDOWS_RULE = "windows_v1"

Window = tuple[str, int, int]  # (lineage id, first year, last year)


def eligible_windows(eligibility_rows: Iterable[Mapping], resolution: float) -> list[Window]:
    """The lineage-windows S4 found eligible pending n at the given resolution, sorted."""
    return sorted({(r["lineage_id"], r["window_start"], r["window_end"]) for r in eligibility_rows
                   if r["resolution"] == resolution and r["meets_m"] and r["meets_v"] and r["meets_r"] is True
                   and not r["closed"]})


def coding_windows(eligible: Sequence[Window], side: str, subject: str, *, per_science: int,
                   seed: int) -> list[Window]:
    """``windows_v1``: all of a pseudoscience commitment's eligible windows, a seeded sample of a science one's."""
    ordered = sorted(eligible)
    if side == "pseudoscience":
        return ordered
    if side not in ("science", "contested"):
        raise ValueError(f"unknown side {side!r}")
    return sorted(random.Random(f"{seed}:{subject}").sample(ordered, min(per_science, len(ordered))))


def window_citations(windows: Sequence[Window], lineage_rows: Iterable[Mapping],
                     cluster_members: Mapping[tuple[float, int, int], set[str]], resolution: float,
                     years: Mapping[str, int | None], authors: Mapping[str, Sequence[str]],
                     citations: Iterable[tuple[str, str]], bearing: set[str]) -> list[dict]:
    """Scope rows (lineage, window, citing work, cited result): citations from the window's members' papers
    published in the window to results bearing on the claim. A paper citing itself does not count."""
    wanted = set(windows)
    members_of: dict[Window, set[str]] = {}
    for r in lineage_rows:
        key = (r["lineage_id"], r["window_start"], r["window_end"])
        if r["resolution"] == resolution and key in wanted:
            members_of[key] = cluster_members[(r["resolution"], r["window_start"], r["cluster"])]
    cites: dict[str, set[str]] = {}
    for citing, cited in citations:
        if cited in bearing and citing != cited:
            cites.setdefault(citing, set()).add(cited)
    rows = []
    for (lineage, start, end), members in sorted(members_of.items()):
        for work in sorted(cites):
            year = years.get(work)
            if year is None or not start <= year <= end or not set(authors.get(work, ())) & members:
                continue
            rows += [{"lineage_id": lineage, "window_start": start, "window_end": end, "citing_work": work,
                      "cited_work": cited} for cited in sorted(cites[work])]
    return rows
