"""Reference lists from ingested documents (decision D-1): text extraction, splitting and parsing.

Registered rules (``registry/corpus.yaml``, ``ingestion``):

* ``pypdf_text_v1``: a PDF's text layer as pypdf extracts it; a web page's text with block elements as
  paragraph breaks. No OCR: a document without text yields no reference list, so its work is unmeasured.
* ``reference_section_v1``: the reference list is what follows the last heading line that reads
  "References", "References cited", "Literature cited", "Bibliography" or "Works cited", up to an
  "Appendix" or "About the author" heading. Page furniture (bare page numbers, running heads) is dropped.
  In a web page the section ends at the next heading element, and each paragraph is one reference. In PDF
  text a reference starts at a line that opens with a number ("12." or "[12]"), an author ("Surname, A.",
  "Surname A." or "SURNAME, A.") or a ditto rule, when the previous line ended a sentence (not with an
  initial); a reference whose ditto rule was lost (". 1984b. ...") takes the author part of the one before.
  Other lines continue the current reference, and words hyphenated across a line break are joined. A
  document with no such heading, or none after it, has no reference list.
* Each reference keeps its text; a DOI written in it, its year, and a journal, volume and first page in
  "Journal 31:117-124", "Journal 16(2):26-30" or "Journal 32, 413-425, 1981" form are read into fields, so
  the census classifies and matches it with the same rules as any other reference.

The rules are deliberately simple, and their errors are measured, not assumed away: the ingestion audit
checks a random sample of extracted references against the documents.
"""

from __future__ import annotations

import html
import io
import re

from viveka.census import Reference, References
from viveka.corpus.ids import normalize_doi

_HEADING = re.compile(r"^\s*(?:references(?: cited)?|literature cited|bibliography|works cited)\s*:?\s*$", re.I)
_STOP = re.compile(r"^\s*(?:appendix\b|about the authors?\b)", re.I)
_FURNITURE = re.compile(r"^\s*(?:\d{1,4}|volume \d+,? \w+ \d{4}|.{0,60}\bvol\.\s*\d+\s*,?\s*no\.\s*\d+\s*)$", re.I)
_START = re.compile(
    r"^\s*(?:\[\d{1,3}\]|\d{1,3}\.\s|_{2,}|—+\s|"
    r"[A-Z][A-Za-z'’\-]+(?: [A-Z][A-Za-z'’\-]+)?,\s*(?:[A-Z]\.|[A-Z][a-z]+\b)|"
    r"[A-Z][A-Za-z'’\-]+ [A-Z]\.(?: ?[A-Z]\.)*(?:,| and\b| &| (?:18|19|20)\d\d)|"
    r"[A-Z]{2,}[A-Z'’\- ]*\s*[,:])")
# A reference by the author of the one before, with the name replaced by a rule the text layer lost:
# ". 1984b. Catastrophes ..." or "(editor). 1994a. Grand Canyon ...".
_DITTO = re.compile(r"^\s*[_—–\-.]*\s*(?:\((?:eds?|editors?)\)\.?\s*)?(?:18|19|20)\d\d[a-z]?\.")
_SENTENCE_END = re.compile(r"[.)\]\d]\s*$")
_ENDS_WITH_INITIAL = re.compile(r"(?:^|\s)[A-Z]\.\s*$")
_AUTHOR_PART = re.compile(r"^(.*?)(?:\s|\.)(?:18|19|20)\d\d[a-z]?\.")
_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)
_YEAR = re.compile(r"\b((?:18|19|20)\d{2})[a-z]?\b")
_COLON_STYLE = re.compile(r"(?P<volume>\d{1,4})\s*(?:[({][^)}]{1,12}[)}])?\s*:\s*(?:p+\.\s*)?(?P<page>\d{1,5})\b")
_COMMA_STYLE = re.compile(r"(?P<volume>\d{1,4})\s*,\s*(?P<page>\d{1,5})\s*[-–]\s*\d{1,5}\s*,\s*"
                          r"(?P<year>(?:18|19|20)\d{2})\b")
_ABBREVIATION = re.compile(r"^(?:[A-Z][a-z]{0,6}\.|[A-Z]{2,8}|&|of|and|the)$")


def pdf_text(content: bytes) -> str:
    """The PDF's text layer, page by page; empty when it has none or cannot be read."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except (PdfReadError, ValueError, KeyError, TypeError, OSError):
        return ""


_BLOCK = re.compile(r"</?(?:p|div|li|h[1-6]|br|tr|section|article|ul|ol|table)\b[^>]*>", re.I)


def html_text(content: bytes, encoding: str = "utf-8") -> str:
    """A page's text, one paragraph per block element, separated by blank lines."""
    page = content.decode(encoding, errors="replace")
    page = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", page, flags=re.I | re.S)
    page = _BLOCK.sub("\n\n", page)
    page = html.unescape(re.sub(r"<[^>]+>", "", page))
    lines = [" ".join(line.split()) for line in page.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


_HTML_HEADING = re.compile(r"<h[1-6]\b[^>]*>(.*?)</h[1-6]>", re.I | re.S)


def html_reference_text(content: bytes, encoding: str = "utf-8") -> str:
    """A web page's reference section as text: from its reference heading to the next heading.

    Pages without a heading element that reads as a reference heading fall back to the whole page's text.
    """
    page = content.decode(encoding, errors="replace")
    headings = list(_HTML_HEADING.finditer(page))
    for i in range(len(headings) - 1, -1, -1):
        if _HEADING.match(html.unescape(re.sub(r"<[^>]+>", "", headings[i].group(1)))):
            end = headings[i + 1].start() if i + 1 < len(headings) else len(page)
            return "References\n\n" + html_text(page[headings[i].end() : end].encode(encoding), encoding)
    return html_text(content, encoding)


def reference_lines(text: str) -> list[str] | None:
    """The lines after the last reference heading, or None when the document has no reference section."""
    lines = text.splitlines()
    heading = max((i for i, line in enumerate(lines) if _HEADING.match(line)), default=None)
    if heading is None:
        return None
    body = []
    for line in lines[heading + 1 :]:
        if _STOP.match(line):
            break
        body.append(line)
    return body


def split_paragraphs(lines: list[str]) -> list[str]:
    """Web pages: one reference per paragraph."""
    entries, current = [], []
    for line in lines:
        if line.strip():
            current.append(line.strip())
        elif current:
            entries.append(" ".join(current))
            current = []
    if current:
        entries.append(" ".join(current))
    return entries


def split_lines(lines: list[str]) -> list[str]:
    """PDF text: a reference starts at a line that looks like its start and follows a finished sentence.

    A line ending in an initial ("... and V.") does not finish a sentence. A reference that opens with a
    lost ditto rule takes the author part of the reference before it.
    """
    entries: list[str] = []
    current = ""
    for raw in lines:
        line = raw.strip()
        if not line or _FURNITURE.match(line):
            continue
        finished = bool(current) and _SENTENCE_END.search(current) and not _ENDS_WITH_INITIAL.search(current)
        if finished and _DITTO.match(line):
            entries.append(current)
            author = _AUTHOR_PART.match(current)
            current = f"{author.group(1).strip()} {line.lstrip('_—–-. ')}" if author else line
        elif finished and _START.match(line):
            entries.append(current)
            current = line
        elif current.endswith(("-", "¬")) and not current.endswith(" -"):
            current = current[:-1] + line
        else:
            current = f"{current} {line}".strip()
    if current:
        entries.append(current)
    return entries


def _journal_before(text: str) -> str | None:
    """The journal name just before a volume: the last sentence, extended backwards over abbreviations."""
    pieces = [p for p in re.split(r"(?<=[.?!])\s+", text.strip().rstrip(",;")) if p]
    if not pieces:
        return None
    taken = [pieces.pop()]
    # Extend over abbreviations ("Ann. Rev. Med.") or a leading "J." ("J. Orthomolecular Psychiat."), but not
    # over the end of a title ("... Mount St. Helens. Origins").
    while pieces and all(_ABBREVIATION.match(w) for w in pieces[-1].split()) and (
            _ABBREVIATION.match(taken[0].split()[0]) or re.fullmatch(r"[A-Z]\.", pieces[-1])):
        taken.insert(0, pieces.pop())
    journal = " ".join(taken).strip(" .,;")
    return journal if re.search(r"[A-Za-z]{2,}", journal) and not _YEAR.fullmatch(journal) else None


def parse_reference(text: str) -> Reference:
    doi_match = _DOI.search(text)
    doi = normalize_doi(doi_match.group(1).rstrip(".,;)")) if doi_match else None
    comma = _COMMA_STYLE.search(text)
    if comma:
        journal = _journal_before(text[: comma.start()])
        return Reference(doi, int(comma["year"]), comma["volume"], comma["page"], journal, text=text)
    years = _YEAR.findall(text[:160]) or _YEAR.findall(text)
    year = int(years[0]) if years else None
    for colon in _COLON_STYLE.finditer(text):
        journal = _journal_before(text[: colon.start()])
        if journal and not re.fullmatch(r"(?:18|19|20)\d{2}[a-z]?", journal):
            return Reference(doi, year, colon["volume"], colon["page"], journal, text=text)
    return Reference(doi, year, text=text)


def extract_references(text: str, paragraphs: bool) -> References | None:
    """The document's reference list, or None when it has none (its work is then unmeasured)."""
    lines = reference_lines(text)
    if lines is None:
        return None
    entries = split_paragraphs(lines) if paragraphs else split_lines(lines)
    entries = [e for e in entries if len(e) >= 12]
    if not entries:
        return None
    return References(tuple(parse_reference(e) for e in entries), "ingested")
