"""Gate 4: a verdict stands only if identical across every partition, overlap and window variant."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from viveka.verdict.reasons import Reason, Verdict, VerdictResult


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def match_lineages(reference: Mapping[str, frozenset[str]],
                   variant: Mapping[str, frozenset[str]]) -> dict[str, str | None]:
    """Greedy maximum-overlap matching of reference lineages to a variant's lineages.
    Lineages sharing no member stay unmatched (None)."""
    pairs = sorted(
        ((jaccard(ref_members, var_members), ref_id, var_id)
         for ref_id, ref_members in reference.items()
         for var_id, var_members in variant.items()),
        key=lambda t: (-t[0], t[1], t[2]),
    )
    matched: dict[str, str | None] = dict.fromkeys(reference)
    used: set[str] = set()
    for overlap, ref_id, var_id in pairs:
        if overlap <= 0:
            break
        if matched[ref_id] is None and var_id not in used:
            matched[ref_id] = var_id
            used.add(var_id)
    return matched


def stable_verdict(results_by_variant: Sequence[VerdictResult | None]) -> VerdictResult:
    """The verdict if (verdict, reason) agrees in every variant; otherwise indeterminate · unstable.
    A None entry is a variant in which the lineage could not be matched."""
    if not results_by_variant:
        raise ValueError("at least one variant is required")
    if any(r is None for r in results_by_variant):
        return VerdictResult(Verdict.INDETERMINATE, Reason.UNSTABLE, "lineage unmatched in at least one variant")
    outcomes = {(r.verdict, r.reason) for r in results_by_variant}
    if len(outcomes) == 1:
        return results_by_variant[0]
    described = sorted(f"{v.value}" + (f" · {reason.value}" if reason else "") for v, reason in outcomes)
    return VerdictResult(Verdict.INDETERMINATE, Reason.UNSTABLE, "differs across variants: " + ", ".join(described))
