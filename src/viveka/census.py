"""The coverage census (framework "Coverage census"; spec stage S2), as pure functions.

Only research papers count: journal articles, reviews, letters and conference or proceedings papers.
A frame's works of other types (editorials, errata, book chapters, preprints, theses, front matter) are
excluded before sampling, and so are references that point to books, theses, reports, preprints, web
pages or unpublished work; references too sparse to classify are excluded and counted separately.

A frame's papers are stratified by publication year and sampled with a generator seeded from the
registry. A sampled paper is *measured* when its full reference list is known, from Crossref or a
manual import, and *unmeasured* otherwise. A reference with a DOI resolves when the DOI is in the
corpus index. References without a DOI are sampled per work and matched by year, volume and first
page, with the journal name breaking ties; each frame-year's matched share estimates how many of its
DOI-less references resolve. Coverage is estimated resolved references over all paper references of
measured works. Every frame, community or mainstream, goes through the same code, and the census never
compares coverage with r: gate 1 does that at S4, per sub-window (spec §7).
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class FrameWork:
    work_id: str
    year: int
    doi: str | None


@dataclass(frozen=True)
class Reference:
    doi: str | None
    year: int | None = None
    volume: str | None = None
    first_page: str | None = None
    journal: str | None = None
    text: str | None = None  # the unstructured citation string, when there is one
    article_title: str | None = None
    volume_title: str | None = None  # a book's or edited volume's title
    series_title: str | None = None  # a proceedings or book series


@dataclass(frozen=True)
class References:
    entries: tuple[Reference, ...]
    source: str  # crossref or manual

    @classmethod
    def from_dois(cls, dois: Iterable[str | None], source: str) -> References:
        return cls(tuple(Reference(d) for d in dois), source)

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def dois(self) -> tuple[str | None, ...]:
        return tuple(e.doi for e in self.entries)

    def doiless(self) -> list[int]:
        return [i for i, e in enumerate(self.entries) if e.doi is None]


@dataclass(frozen=True)
class Biblio:
    year: int
    volume: str
    first_page: str
    journal: str | None


@dataclass(frozen=True)
class SampleOutcome:
    work: FrameWork
    references: References | None
    resolved: int
    refs: int = 0  # paper references, the denominator
    refs_excluded: int = 0  # references to non-papers
    refs_unclassifiable: int = 0
    doiless: int = 0  # DOI-less paper references
    doiless_sampled: int = 0
    doiless_matched: int = 0
    doiless_rescued: int = 0  # of the matched, those found through a Crossref bibliographic query
    doiless_unparseable: int = 0

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


def doiless_sample(case_id: str, work_id: str, pool: Sequence[int], per_work: int, seed: int) -> list[int]:
    """Up to ``per_work`` of the given reference indices, reproducible from the seed."""
    pool = sorted(pool)
    if len(pool) <= per_work:
        return pool
    rng = np.random.default_rng(np.random.SeedSequence(entropy=seed,
                                                       spawn_key=(stable_key(case_id), stable_key(work_id))))
    return sorted(pool[i] for i in rng.choice(len(pool), size=per_work, replace=False).tolist())


# ---------------------------------------------------------------- what counts as a paper

_THESIS = re.compile(r"\b(?:thesis|dissertation|ph\.?\s?d\b|m\.?\s?sc\b|diplomarbeit)", re.I)
_UNPUBLISHED = re.compile(r"\b(?:to be published|in press|submitted|unpublished|private communication|"
                          r"personal communication|in preparation|arxiv|preprint)", re.I)
_PROCEEDINGS = re.compile(r"\b(?:proc\.|proceedings|conference|conf\.|symposium|workshop|colloquium|iccf)", re.I)
_REPORT = re.compile(r"\b(?:[A-Z]{2,}[- ]?(?:PUB|REP|TH|EP|PH|TM)[- ]?\d|CERN[- ]\d|DOE/|LA-UR\b|UCRL\b|ORNL\b|"
                     r"technical report|tech\. rep|report (?:no|number|of|to)\b|memorandum)", re.I)
_WEB = re.compile(r"https?://|www\.|available (?:at|from)\b", re.I)
_BOOK = re.compile(r"\((?:eds?|editors?)\.?\)|\beds?\.\s*\)|\b(?:university )?press\b|\bpublishers?\b|\bverlag\b|"
                   r"\bisbn\b|\b\d(?:st|nd|rd|th) ed(?:ition|\.)", re.I)
# Capitalised words, each separated by one space, then ", City, year)". Written so each word boundary can fall in
# one place only: the earlier form, (?:[A-Z][\w.&'-]*\s?)+, matched the same strings but could split a run of
# capitals in every possible way, and took hours on a reference like "(ABCDEFGHIJKLMNOPQRSTUVWXYZ...".
_PUBLISHER_CITY = re.compile(r"\((?:[A-Z][\w.&'-]*\s)*[A-Z][\w.&'-]*\s?,\s*[A-Z][\w .'-]+,\s*(?:18|19|20)\d\d\)")
_NEWS = re.compile(r"\b(?:new scientist|newspaper|magazine)\b", re.I)


def reference_kind(ref: Reference) -> str:
    """'paper', 'excluded' (a book, thesis, report, preprint, web page or unpublished work) or 'unclassifiable'.

    A reference with a DOI is a paper here; its OpenAlex type decides it in ``outcome``. Proceedings count as
    papers, because they are where many communities publish.
    """
    if ref.doi:
        return "paper"
    text = " ".join(x for x in (ref.text, ref.journal, ref.series_title, ref.volume_title, ref.article_title) if x)
    if _THESIS.search(text) or _UNPUBLISHED.search(text) or _NEWS.search(text):
        return "excluded"
    if ref.series_title or _PROCEEDINGS.search(text):
        return "paper"
    if _REPORT.search(text) or _WEB.search(text):
        return "excluded"
    if ref.volume_title and not ref.journal:
        return "excluded"
    if _BOOK.search(text) or _PUBLISHER_CITY.search(ref.text or ""):
        return "excluded"
    if ref.journal or biblio_of(ref) is not None:
        return "paper"
    return "unclassifiable"


# ---------------------------------------------------------------- bibliographic matching

# A volume may carry a section letter ("D33", "125B", "A 404"); OpenAlex stores only its number.
_VOLUME = re.compile(r"^[A-Za-z]{0,2}\s?(\d{1,4})[A-Za-z]?$")
_PAGE = re.compile(r"^([A-Za-z]?\d{1,6}[A-Za-z]?)(?:\s*(?:ff\.?|[-–]\s*[A-Za-z]?\d+))?$")
_YEAR = r"(?P<year>(?:18|19|20)\d{2})[a-z]?"
_VOL = r"(?P<volume>[A-Z]{0,2}\d{1,4}[A-Z]?)"
_PG = r"(?P<page>[A-Za-z]?\d{1,6})"
_RANGE = r"(?:\s*[-–]\s*[A-Za-z]?\d+)?"
_CITATIONS = (
    # "56, 3 (1986)" and "D33 3487 (1986)"
    re.compile(rf"\b{_VOL}\s*[,:]?\s+{_PG}{_RANGE}\s*\(\s*{_YEAR}\s*\)"),
    # "261:301-308 (1989)"
    re.compile(rf"\b{_VOL}\s*[,:]\s*{_PG}{_RANGE}\s*\(\s*{_YEAR}\s*\)"),
    # "25 (1994) 478"
    re.compile(rf"\b{_VOL}\s*\(\s*{_YEAR}\s*\)\s*,?\s*(?:p+\.\s*)?{_PG}"),
    # "1989. 261: p. 301" and "1988;333(6176):816"
    re.compile(rf"\b{_YEAR}\s*[.;,]\s*(?P<volume>\d{{1,4}})(?:\s*\(\d+\))?\s*:\s*(?:p+\.\s*)?{_PG}"),
)
_STOPWORDS = frozenset({"of", "the", "and", "for", "in", "on", "a", "an", "section", "der", "die", "und", "de", "la"})


def _volume(value: str) -> str | None:
    found = _VOLUME.match(value.strip())
    return found.group(1) if found else None


def _page(value: str) -> str | None:
    found = _PAGE.match(value.strip())
    return found.group(1) if found else None


def biblio_of(ref: Reference) -> Biblio | None:
    """Year, volume number and first page, from structured fields or a citation string.

    None means the reference has no readable volume and page.
    """
    if ref.year and ref.volume and ref.first_page:
        volume, page = _volume(ref.volume), _page(ref.first_page)
        return Biblio(ref.year, volume, page, ref.journal) if volume and page else None
    for pattern in _CITATIONS:
        found = pattern.search(ref.text or "")
        if found:
            volume, page = _volume(found["volume"]), _page(found["page"])
            if volume and page:
                return Biblio(int(found["year"]), volume, page, ref.journal)
    return None


def _journal_words(name: str) -> list[str]:
    main = name.split(":", 1)[0]
    return [w for w in re.findall(r"[a-z0-9]+", main.lower()) if w not in _STOPWORDS]


def journal_compatible(cited: str, candidate: str) -> bool:
    """'Phys. Rev. Lett.' is compatible with 'Physical Review Letters': word by word, each is a prefix."""
    a, b = _journal_words(cited), _journal_words(candidate)
    return bool(a) and len(a) == len(b) and all(y.startswith(x) for x, y in zip(a, b, strict=True))


def match_found(biblio: Biblio, candidate_journals: Sequence[str | None]) -> bool:
    """A single work at that year, volume and page is a match; among several, the journal must agree."""
    if len(candidate_journals) == 1:
        return True
    return biblio.journal is not None and any(n and journal_compatible(biblio.journal, n) for n in candidate_journals)


@dataclass(frozen=True)
class CatalogueEntry:
    """A paper listed by an ingested venue, for matching references to it (rule ingested_catalogue_v1)."""

    aliases: tuple[str, ...]
    year: int | None
    volume: str | None
    first_page: str | None
    first_author: str | None  # folded family name


def fold(text: str) -> str:
    """Letters only, lower case, accents removed: how names are compared."""
    import unicodedata

    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z]", "", plain.lower())


def catalogue_match(ref: Reference, entries: Sequence[CatalogueEntry], year_tolerance: int) -> bool:
    """Whether a DOI-less reference is to a paper an ingested venue lists.

    The reference's journal must be one of the venue's names, its volume equal and its year within the
    tolerance when both are known; then its first page must equal the listed one or, when the listing has no
    page, the listed first author's family name must open the reference.
    """
    volume = _volume(ref.volume) if ref.volume else None
    page = _page(ref.first_page) if ref.first_page else None
    if not ref.journal or volume is None:
        return False
    opening = fold((ref.text or "")[:60])
    for entry in entries:
        if entry.volume != volume or not any(journal_compatible(ref.journal, a) for a in entry.aliases):
            continue
        if ref.year is not None and entry.year is not None and abs(ref.year - entry.year) > year_tolerance:
            continue
        if entry.first_page is not None and page is not None:
            if entry.first_page == page:
                return True
        elif entry.first_author and opening.startswith(entry.first_author):
            return True
    return False


def paper_doiless(references: References) -> list[int]:
    """Indices of DOI-less references that count as papers: the pool the match sample is drawn from."""
    return [i for i, e in enumerate(references.entries) if e.doi is None and reference_kind(e) == "paper"]


# ---------------------------------------------------------------- recovery through a bibliographic query

RESCUE_TYPES = frozenset({"journal-article", "proceedings-article"})
_WORDS = re.compile(r"[a-z0-9]+")
_ANY_YEAR = re.compile(r"\b(?:18|19|20)\d{2}\b")


@dataclass(frozen=True)
class Candidate:
    """One item a bibliographic query returned."""

    doi: str | None
    score: float
    year: int | None
    volume: str | None
    first_page: str | None
    journal: str | None
    title: str | None
    kind: str | None


def rescue_query(ref: Reference) -> str | None:
    """The string to query with: the citation text, or its structured fields; None if too little to go on."""
    if ref.text:
        query = ref.text
    else:
        query = " ".join(str(p) for p in (ref.article_title, ref.journal, ref.volume, ref.first_page, ref.year) if p)
    query = query.strip()
    return query[:300] if len(query) >= 20 else None


def _content_words(text: str) -> list[str]:
    return [w for w in _WORDS.findall(text.lower()) if len(w) >= 3 and w not in _STOPWORDS]


def journal_contained(cited: str, candidate: str) -> bool:
    """Like ``journal_compatible``, but the candidate may carry extra words ('... and Interfacial Electrochemistry')."""
    a, remaining = _journal_words(cited), iter(_journal_words(candidate))
    return bool(a) and all(any(y.startswith(x) for y in remaining) for x in a)


MIN_TITLE_WORDS = 5  # shorter titles are volume or series names as often as papers
STRONG_TITLE_WORDS, STRONG_TITLE_SHARE = 7, 0.85  # a title match strong enough to outweigh contradicting numbers


def _share(words: Sequence[str], pool: set[str]) -> float:
    return sum(w in pool for w in words) / len(words) if words else 0.0


def rescue_match(ref: Reference, candidates: Sequence[Candidate], min_score: float, title_share: float,
                 year_tolerance: int) -> str | None:
    """The DOI of the first candidate that is plausibly the cited paper, or None (rule crossref_bibliographic_v2).

    A candidate must be a journal article or proceedings paper scoring at least ``min_score`` and published within
    the year tolerance when both years are known. It is rejected when the citation is to proceedings and the
    candidate is a journal article from a non-proceedings venue (a different publication of the same work), and
    when its volume and page both contradict the citation's, unless its title matches strongly. It is accepted
    when its title (at least five words) shares ``title_share`` of its words with the citation, both ways when the
    citation carries its own title, or, with both years known, when it agrees on volume, first page or journal.
    """
    biblio = biblio_of(ref)
    year = ref.year
    if year is None:
        found = _ANY_YEAR.search(ref.text or "")
        year = int(found.group()) if found else None
    citation = " ".join(p for p in (ref.text, ref.article_title, ref.journal, ref.series_title) if p)
    haystack = set(_content_words(citation))
    cited_title = _content_words(ref.article_title or "")
    cites_proceedings = bool(_PROCEEDINGS.search(citation)) or ref.series_title is not None
    for c in candidates:
        if not c.doi or c.kind not in RESCUE_TYPES or c.score < min_score:
            continue
        years_known = year is not None and c.year is not None
        if years_known and abs(c.year - year) > year_tolerance:
            continue
        if cites_proceedings and c.kind == "journal-article" and not _PROCEEDINGS.search(c.journal or ""):
            continue
        title_words = _content_words(c.title or "")
        forward = _share(title_words, haystack)
        titled = len(title_words) >= MIN_TITLE_WORDS and forward >= title_share and (
            not cited_title or _share(cited_title, set(title_words)) >= title_share)
        strong_title = titled and len(title_words) >= STRONG_TITLE_WORDS and forward >= STRONG_TITLE_SHARE
        numbers_known = {n for n in (c.volume and _volume(c.volume), c.first_page and _page(c.first_page)) if n}
        numbers = biblio is not None and bool(numbers_known & {biblio.volume, biblio.first_page})
        if biblio is not None and numbers_known and not numbers and not strong_title:
            continue  # volume and page both contradict the citation
        journal = bool(ref.journal and c.journal and journal_contained(ref.journal, c.journal))
        if titled or (years_known and (numbers or journal)):
            return c.doi
    return None


# ---------------------------------------------------------------- coverage


def outcome(work: FrameWork, references: References | None, doi_types: Mapping[str, str | None],
            paper_types: frozenset[str], matches: Mapping[int, bool | None] | None = None,
            rescued: Iterable[int] = ()) -> SampleOutcome:
    """Count a sampled work's paper references and how many resolve.

    ``doi_types`` maps each DOI found in the corpus to its work type; a DOI absent from it is unresolved but
    still counted as a paper. ``matches`` maps each sampled DOI-less paper reference to matched (True),
    unmatched (False) or no readable volume and page (None); ``rescued`` names the sampled references whose
    match came from a bibliographic query.
    """
    if references is None:
        return SampleOutcome(work, None, 0)
    matches = matches or {}
    counts = Counter()
    for entry in references.entries:
        if entry.doi is not None:
            if entry.doi not in doi_types:
                counts["refs"] += 1
            elif doi_types[entry.doi] in paper_types:
                counts.update(refs=1, resolved=1)
            else:
                counts["refs_excluded"] += 1
            continue
        kind = reference_kind(entry)
        if kind == "paper":
            counts.update(refs=1, doiless=1)
        elif kind == "excluded":
            counts["refs_excluded"] += 1
        else:
            counts["refs_unclassifiable"] += 1
    return SampleOutcome(
        work, references, resolved=counts["resolved"], refs=counts["refs"], refs_excluded=counts["refs_excluded"],
        refs_unclassifiable=counts["refs_unclassifiable"], doiless=counts["doiless"], doiless_sampled=len(matches),
        doiless_matched=sum(1 for m in matches.values() if m is True),
        doiless_rescued=sum(1 for i in set(rescued) if matches.get(i) is True),
        doiless_unparseable=sum(1 for m in matches.values() if m is None),
    )


_OUTCOME_SUMS = ("refs", "resolved", "refs_excluded", "refs_unclassifiable", "doiless", "doiless_sampled",
                 "doiless_matched", "doiless_rescued", "doiless_unparseable")


def coverage_rows(case_id: str, frame_id: str, kind: str, works: Sequence[FrameWork],
                  outcomes: Sequence[SampleOutcome], excluded_works: Mapping[int, int] | None = None) -> list[dict]:
    """One row per publication year of the frame, with the year's estimate of resolved references."""
    excluded_works = excluded_works or {}
    frame_counts = Counter(w.year for w in works)
    per_year: dict[int, list[SampleOutcome]] = defaultdict(list)
    for o in outcomes:
        per_year[o.work.year].append(o)
    rows = []
    for year in sorted(set(frame_counts) | set(excluded_works)):
        sampled = per_year.get(year, [])
        measured = [o for o in sampled if o.references is not None]
        row = {"case_id": case_id, "frame_id": frame_id, "kind": kind, "year": year,
               "frame_works": frame_counts[year], "frame_works_excluded": excluded_works.get(year, 0),
               "sampled": len(sampled), "measured": len(measured), "unmeasured": len(sampled) - len(measured)}
        row.update({name: sum(getattr(o, name) for o in measured) for name in _OUTCOME_SUMS})
        share = row["doiless_matched"] / row["doiless_sampled"] if row["doiless_sampled"] else 0.0
        row["resolved_estimated"] = round(row["resolved"] + row["doiless"] * share, 6)
        rows.append(row)
    return rows


_SUMMED = ("frame_works", "frame_works_excluded", "sampled", "measured", "unmeasured", *_OUTCOME_SUMS,
           "resolved_estimated")


@dataclass(frozen=True)
class Summary:
    case_id: str
    frame_id: str
    kind: str
    frame_works: int
    frame_works_excluded: int
    sampled: int
    measured: int
    unmeasured: int
    refs: int
    resolved: int
    refs_excluded: int
    refs_unclassifiable: int
    doiless: int
    doiless_sampled: int
    doiless_matched: int
    doiless_rescued: int
    doiless_unparseable: int
    resolved_estimated: float
    coverage: float | None
    unmeasured_share: float | None
    measurable: bool


def summarize(rows: Iterable[dict], max_unmeasured_share: float) -> list[Summary]:
    """Coverage per frame over the given rows (pass one frame-year's row for a per-year reading)."""
    totals: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
    for row in rows:
        totals[(row["case_id"], row["frame_id"], row["kind"])].update({k: row[k] for k in _SUMMED})
    summaries = []
    for (case_id, frame_id, kind), t in sorted(totals.items()):
        coverage = t["resolved_estimated"] / t["refs"] if t["refs"] else None
        share = t["unmeasured"] / t["sampled"] if t["sampled"] else None
        measurable = coverage is not None and share is not None and share <= max_unmeasured_share
        summaries.append(Summary(case_id, frame_id, kind, *(int(t[k]) for k in _SUMMED[:-1]),
                                 float(t["resolved_estimated"]), coverage, share, measurable))
    return summaries
