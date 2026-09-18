"""Author overlap between calibration fields and cases (decision D-10; rule ``overlap_coefficient_core_v2``).

Folds are whole fields, so calibration fields must be distinct communities. A subject's authors are its
*core* authors: those with at least ``core_min_works`` works in its community frames. Two subjects whose
community works all come from OpenAlex are compared by OpenAlex author id, which OpenAlex has already
disambiguated; when either includes works ingested from a venue's own archive, whose authors are known
only by name, both are compared by name: folded family name and the initials of every given name. The
overlap is the number of core authors two subjects share divided by the smaller subject's number.

Rule v1 compared every author by family name and first initial; against the largest fields (immunology,
about 156,000 names) a third of any small field's names matched namesakes by chance (dev fold, 18 Sep 2026),
so v2 compares identities and core authors only.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import combinations

from viveka.census import fold

INGESTED_PREFIX = "X:"


def name_key(display_name: str | None) -> str | None:
    """Family name and the initials of every given name: "Jerry R. Bergman" and "J. R. Bergman" -> bergman:jr."""
    words = [w for w in (display_name or "").replace(",", " ").split() if w.strip(".")]
    if not words:
        return None
    family = fold(words[-1])
    if not family:
        return None
    initials = "".join(fold(part)[:1] for w in words[:-1] for part in w.replace(".", " ").split())
    return f"{family}:{initials}"


@dataclass(frozen=True)
class SubjectAuthors:
    ids: frozenset[str]  # core authors by OpenAlex id (empty when the subject has ingested works)
    names: frozenset[str]  # core authors by name key
    all_openalex: bool


def community_authors(frames_rows: Iterable[dict], authorships_rows: Iterable[dict], authors_rows: Iterable[dict],
                      core_min_works: int) -> SubjectAuthors:
    """Core authors of the works in a subject's community frames."""
    works = {r["work_id"] for r in frames_rows if r["kind"] == "community"}
    all_openalex = not any(w.startswith(INGESTED_PREFIX) for w in works)
    names = {r["author_id"]: r["display_name"] for r in authors_rows}
    by_id: Counter = Counter()
    by_name: Counter = Counter()
    seen: set[tuple[str, str]] = set()
    for r in authorships_rows:
        if r["work_id"] not in works or (r["work_id"], r["author_id"]) in seen:
            continue
        seen.add((r["work_id"], r["author_id"]))
        by_id[r["author_id"]] += 1
        key = name_key(names.get(r["author_id"]))
        if key:
            by_name[key] += 1
    return SubjectAuthors(
        ids=frozenset(a for a, n in by_id.items() if n >= core_min_works) if all_openalex else frozenset(),
        names=frozenset(k for k, n in by_name.items() if n >= core_min_works), all_openalex=all_openalex)


@dataclass(frozen=True)
class Overlap:
    a: str
    b: str
    basis: str  # openalex_id or name
    authors_a: int
    authors_b: int
    shared: int

    @property
    def coefficient(self) -> float | None:
        smaller = min(self.authors_a, self.authors_b)
        return self.shared / smaller if smaller else None

    @property
    def smaller(self) -> str:
        return self.a if self.authors_a <= self.authors_b else self.b


def overlaps(authors: Mapping[str, SubjectAuthors], fields: set[str]) -> list[Overlap]:
    """Every pair of subjects that includes at least one calibration field, in name order."""
    out = []
    for a, b in combinations(sorted(authors), 2):
        if a not in fields and b not in fields:
            continue
        x, y = authors[a], authors[b]
        if x.all_openalex and y.all_openalex:
            out.append(Overlap(a, b, "openalex_id", len(x.ids), len(y.ids), len(x.ids & y.ids)))
        else:
            out.append(Overlap(a, b, "name", len(x.names), len(y.names), len(x.names & y.names)))
    return out
