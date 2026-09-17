"""Author overlap between calibration fields and cases (decision D-10; rule ``overlap_coefficient_names_v1``).

Folds are whole fields, so calibration fields must be distinct communities. Each subject's authors are
the authors of the works in its community frames, compared by name: folded family name (the last word
of the name) and first initial. Two subjects' overlap is the number of names they share divided by the
smaller subject's number of names. Namesakes can only raise it, never hide it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import combinations

from viveka.census import fold


def name_key(display_name: str | None) -> str | None:
    words = [w for w in (display_name or "").replace(",", " ").split() if w.strip(".")]
    if not words:
        return None
    family = fold(words[-1])
    if not family:
        return None
    initial = fold(words[0])[:1] if len(words) > 1 else ""
    return f"{family}:{initial}"


def community_authors(frames_rows: Iterable[dict], authorships_rows: Iterable[dict],
                      authors_rows: Iterable[dict]) -> set[str]:
    """Name keys of the authors of the works in a subject's community frames."""
    works = {r["work_id"] for r in frames_rows if r["kind"] == "community"}
    names = {r["author_id"]: r["display_name"] for r in authors_rows}
    keys = {name_key(names.get(r["author_id"])) for r in authorships_rows if r["work_id"] in works}
    keys.discard(None)
    return keys  # type: ignore[return-value]


@dataclass(frozen=True)
class Overlap:
    a: str
    b: str
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


def overlaps(authors: Mapping[str, set[str]], fields: set[str]) -> list[Overlap]:
    """Every pair of subjects that includes at least one calibration field, in name order."""
    return [Overlap(a, b, len(authors[a]), len(authors[b]), len(authors[a] & authors[b]))
            for a, b in combinations(sorted(authors), 2) if a in fields or b in fields]
