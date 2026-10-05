"""Coding items from citation contexts (stage S6, before the leakage test).

Four mechanical steps, each a pure function here and each recorded by rule name in the run that uses it:

* ``prose_v1``: a context that is not a passage of prose (a table row, a reference list, a formula) is not an
  item. It is dropped and counted, never repaired.
* ``citations_v1``: every citation marker becomes ``[REF]``, numbered ones ("[12]", "[3-5, 9]") and author-year
  ones ("(Smith et al., 1997; Jones and Lee, 2001)", "Smith et al. (1997)"), so no cited author's name survives.
  The marker that matches the cited work (its first author's family name and its year) becomes ``[CITED]``, and
  so does a context's only marker, since the context was extracted as a citation of that work. A numbered
  marker among several cannot be matched to a work, so such an item is marked unresolved.
* the registered dictionaries (``coders.redaction``), applied after the markers;
* exact duplicates (the same redacted text for the same cited work) are coded once.

Two drop rules follow (owner, 4 Oct 2026, D-24), each counted and never repaired: ``english_v2`` drops a
context not written in English, since its language points to the venues of one field; ``resolved_v1`` drops
an item in which the cited work's marker could not be identified, since a stance is coded toward one result.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

PROSE_RULE = "prose_v1"
CITATION_RULE = "citations_v1"
LANGUAGE_RULE = "english_v2"
RESOLVED_RULE = "resolved_v1"
_ENGLISH = frozenset("""the of and to in a is that for are with as was be by this on not or from which were
these an it has have been their than its we our they but also at can may such between both however
other more there when where this""".split())
# Function words of the other languages the corpora contain (German, French, Spanish, Portuguese, Italian),
# none of them also an English word.
_FOREIGN = frozenset("""der die das und ist sind wird werden nicht mit von für auf dem den des eine einer
eines zur zum im bei auch als sich les une est sont dans pour sur avec qui ces aux par pas plus été
el los las del una por para con que se lo como más fue han ser son sobre entre também não uma pelo pela
são foram dos il della degli delle che sono stato""".split())
MIN_WORDS = 8
MIN_WORD_SHARE = 0.6

_YEAR = r"(?:19|20)\d\d[a-z]?"
_NAME = r"[A-Z][\w'’\-]+(?:\s+(?:van|von|de|der|den|du|la|le|da|dos|di)\s+[A-Z][\w'’\-]+)*"
_AUTHORS = rf"{_NAME}(?:\s+et\s+al\.?|\s+(?:and|&)\s+{_NAME}|(?:,\s*{_NAME})+,?\s+(?:and|&)\s+{_NAME})?"
_UNIT = re.compile(rf"(?:e\.g\.,?\s*|see\s+|cf\.\s*)?({_AUTHORS})\s*,?\s*\(?({_YEAR}(?:\s*,\s*{_YEAR})*)\)?")
_NARRATIVE = re.compile(rf"\b({_AUTHORS})\s+\(({_YEAR}(?:\s*,\s*{_YEAR})*)\)")
_GROUP = re.compile(rf"[\(\[]([^()\[\]]*?{_YEAR}[^()\[\]]*?)[\)\]]")
_NUMBERED = re.compile(r"\[\s*\d+(?:\s*[-–,]\s*\d+)*\s*\]")
_NUMBERED_V2 = re.compile(r"\[\s*\d+(?:\s*[-–,]\s*\d+)*\s*\]|\(\s*\d{1,3}(?:\s*[-–,]\s*\d{1,3})*\s*\)")
CITATION_RULE_V2 = "citations_v2"
_WORD = re.compile(r"[^\W\d_]{2,}")


@dataclass(frozen=True)
class CitedWork:
    work_id: str
    family_name: str | None
    year: int | None


@dataclass(frozen=True)
class ContextItem:
    item_id: str  # hash of the cited work and the redacted text: opaque, and equal for exact duplicates
    cited_work: str
    text: str
    cited_marked: bool
    sources: tuple[str, ...]  # the citing papers whose context this is
    rule: str = CITATION_RULE  # the citation rule that placed [CITED]


@dataclass(frozen=True)
class CitedNumbers:
    """Where the cited work stands in the citing paper's reference list (1-based), and the list's length."""

    positions: frozenset[int]
    list_length: int


def _fold(name: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c)).casefold()


def is_prose(text: str) -> bool:
    """``prose_v1``: at least MIN_WORDS tokens, and at least MIN_WORD_SHARE of them alphabetic words."""
    tokens = text.split()
    if len(tokens) < MIN_WORDS:
        return False
    words = sum(1 for t in tokens if _WORD.search(t) and not any(ch.isdigit() for ch in t))
    return words / len(tokens) >= MIN_WORD_SHARE


def is_english(text: str) -> bool:
    """``english_v2``: there are English function words, and no more function words of another language.
    (``english_v1`` asked for 15% English function words and also dropped terse English sentences.)"""
    words = [w.lower() for w in _WORD.findall(text)]
    english = sum(w in _ENGLISH for w in words)
    return english > 0 and english >= sum(w in _FOREIGN for w in words)


def _matches(authors: str, years: str, cited: CitedWork | None) -> bool:
    if cited is None or not cited.family_name or cited.year is None:
        return False
    first = authors.split(",")[0].split(" et ")[0].split(" and ")[0].split(" & ")[0].strip()
    surname = first.split()[-1] if first else ""
    return _fold(surname) == _fold(cited.family_name.split()[-1]) and str(cited.year) in years


def mask_citations(text: str, cited: CitedWork | None) -> tuple[str, bool]:
    """``citations_v1``: citation markers to [REF], the cited work's to [CITED]; whether [CITED] was placed."""
    placed = False

    def unit(match: re.Match) -> str:
        nonlocal placed
        if _matches(match.group(1), match.group(2), cited):
            placed = True
            return "[CITED]"
        return "[REF]"

    def group(match: re.Match) -> str:
        inner = match.group(1)
        replaced = _UNIT.sub(unit, inner)
        if replaced == inner:
            return match.group(0)  # a bracket with a year in it that is not a citation, e.g. "(in 1998)"
        return match.group(0)[0] + replaced + match.group(0)[-1]

    text = _GROUP.sub(group, text)
    text = _NARRATIVE.sub(unit, text)
    text = _NUMBERED.sub("[REF]", text)
    if not placed and text.count("[REF]") == 1:
        # The context was extracted as a citation of the cited work, so its only marker is that work's.
        text, placed = text.replace("[REF]", "[CITED]"), True
    return text, placed


def marker_numbers(marker: str) -> set[int]:
    """The reference numbers a numbered marker names: "[3-5, 9]" is {3, 4, 5, 9}. An absurd range is empty."""
    numbers: set[int] = set()
    for part in re.split(r"\s*,\s*", marker.strip("[]() ")):
        ends = [int(n) for n in re.findall(r"\d+", part)]
        if len(ends) == 2 and 0 <= ends[1] - ends[0] <= 50:
            numbers.update(range(ends[0], ends[1] + 1))
        elif len(ends) == 1:
            numbers.add(ends[0])
        else:
            return set()
    return numbers


def mask_citations_v2(text: str, numbers: CitedNumbers | None = None) -> tuple[str, bool]:
    """``citations_v2``, for a context ``citations_v1`` leaves unresolved (decision D-30): numbered markers in
    parentheses, "(12)" and "(3-5, 9)", are markers too, and a numbered marker naming the cited work's number in
    the citing paper's reference list becomes ``[CITED]``. The numbers are used only when no marker names a
    number beyond the list's length (the list would then not be the one the paper numbers by). As in v1, a
    context's only marker is the cited work's."""
    placed = False

    def unit(match: re.Match) -> str:
        return "[REF]"  # v1 found no author-year marker matching the cited work

    def group(match: re.Match) -> str:
        inner = match.group(1)
        replaced = _UNIT.sub(unit, inner)
        return match.group(0) if replaced == inner else match.group(0)[0] + replaced + match.group(0)[-1]

    text = _GROUP.sub(group, text)
    text = _NARRATIVE.sub(unit, text)
    named = [marker_numbers(m.group(0)) for m in _NUMBERED_V2.finditer(text)]
    usable = (numbers is not None and numbers.positions
              and all(n <= numbers.list_length for names in named for n in names))

    def numbered(match: re.Match) -> str:
        nonlocal placed
        if usable and marker_numbers(match.group(0)) & numbers.positions:
            placed = True
            return "[CITED]"
        return "[REF]"

    text = _NUMBERED_V2.sub(numbered, text)
    if not placed and text.count("[REF]") == 1:
        text, placed = text.replace("[REF]", "[CITED]"), True
    return text, placed


def build_items(contexts: Iterable[Mapping], cited_works: Mapping[str, CitedWork],
                redact: Callable[[str], str], *, rule: str = CITATION_RULE,
                numbers: Mapping[tuple[str, str], CitedNumbers] | None = None
                ) -> tuple[list[ContextItem], Counter]:
    """Items from context rows (cited_work, citing id, text), and counts of what was dropped and why.

    Under ``citations_v2`` a context v1 leaves unresolved is tried again with :func:`mask_citations_v2`;
    ``numbers`` maps (citing work, cited work) to the cited work's reference numbers. Items v1 resolves are the
    same under either rule."""
    if rule not in (CITATION_RULE, CITATION_RULE_V2):
        raise ValueError(f"unknown citation rule {rule!r}")
    dropped: Counter = Counter()
    merged: dict[str, dict] = {}
    for row in contexts:
        text = " ".join(str(row.get("text") or "").split())
        if not is_prose(text):
            dropped["not_prose"] += 1
            continue
        if not is_english(text):
            dropped["not_english"] += 1
            continue
        cited = cited_works.get(row["cited_work"])
        masked, placed = mask_citations(text, cited)
        by = CITATION_RULE
        if not placed and rule == CITATION_RULE_V2:
            known = (numbers or {}).get((row.get("citing_work"), row["cited_work"]))
            masked, placed = mask_citations_v2(text, known)
            by = CITATION_RULE_V2
        if not placed:
            dropped["unresolved"] += 1
            continue
        redacted = redact(masked)
        key = hashlib.sha256(f"{row['cited_work']}\n{redacted}".encode()).hexdigest()[:20]
        source = str(row.get("citing_doi") or row.get("citing_s2_id") or "")
        if key in merged:
            dropped["duplicate"] += 1
            merged[key]["sources"].add(source)
            if by == CITATION_RULE:
                merged[key]["rule"] = by  # an item v1 resolves anywhere is a v1 item
            continue
        merged[key] = {"cited_work": row["cited_work"], "text": redacted, "placed": placed, "sources": {source},
                       "rule": by}
    items = [ContextItem(key, v["cited_work"], v["text"], v["placed"], tuple(sorted(v["sources"])), v["rule"])
             for key, v in sorted(merged.items())]
    return items, dropped
