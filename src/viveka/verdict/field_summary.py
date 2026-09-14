"""Field summaries ("Fields are described, not judged").

A summary for a claim covers every lineage that engaged it and descends from the
community in which it was first tested:

* uniform      - every determinate verdict, in every lineage, is the same;
* split        - at least one lineage is healthy and a different lineage is insulated;
* shifted      - determinate verdicts disagree, but only within one lineage: its conduct
                 changed over time and no second lineage carries the difference;
* undetermined - no lineage has a determinate verdict.

Split takes precedence over shifted when both apply.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from viveka.verdict.reasons import DETERMINATE, Verdict, VerdictResult


class Summary(StrEnum):
    UNIFORM = "uniform"
    SPLIT = "split"
    SHIFTED = "shifted"
    UNDETERMINED = "undetermined"


@dataclass(frozen=True)
class LineageVerdict:
    lineage_id: str
    window: tuple[int, int]
    result: VerdictResult


@dataclass(frozen=True)
class FieldSummary:
    summary: Summary
    lineages: tuple[str, ...]
    determinate: tuple[LineageVerdict, ...]


def descendants(root: str, parents: Mapping[str, Iterable[str]]) -> set[str]:
    """The root and every lineage reachable from it through child -> parents links."""
    children: dict[str, set[str]] = {}
    for child, its_parents in parents.items():
        for parent in its_parents:
            children.setdefault(parent, set()).add(child)
    seen, queue = {root}, deque([root])
    while queue:
        for child in sorted(children.get(queue.popleft(), ())):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return seen


def summarise(root: str, parents: Mapping[str, Iterable[str]], verdicts: Sequence[LineageVerdict]) -> FieldSummary:
    in_scope = descendants(root, parents)
    relevant = [v for v in verdicts if v.lineage_id in in_scope]
    determinate = tuple(
        sorted((v for v in relevant if v.result.verdict in DETERMINATE), key=lambda v: (v.window, v.lineage_id))
    )
    lineages = tuple(sorted({v.lineage_id for v in relevant}))
    if not determinate:
        return FieldSummary(Summary.UNDETERMINED, lineages, determinate)

    healthy = {v.lineage_id for v in determinate if v.result.verdict is Verdict.HEALTHY}
    insulated = {v.lineage_id for v in determinate if v.result.verdict is Verdict.INSULATED}
    if not healthy or not insulated:
        return FieldSummary(Summary.UNIFORM, lineages, determinate)
    if any(h != i for h in healthy for i in insulated):
        return FieldSummary(Summary.SPLIT, lineages, determinate)
    return FieldSummary(Summary.SHIFTED, lineages, determinate)
