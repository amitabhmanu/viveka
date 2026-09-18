"""Author lines on contents pages: names with degrees removed, shared by the venue adapters."""

from __future__ import annotations

import re

from viveka.corpus.ingest import Author

_ET_AL = re.compile(r"\bet\.?\s*al\.?", re.I)
_DEGREE = re.compile(
    r"^(?:m\.?d|ph\.?d|d\.?m\.?d|d\.?d\.?s|d\.?sc|b\.?sc|m\.?sc|m\.?s|b\.?s|m\.?a|b\.?a|r\.?n|n\.?d|d\.?c|d\.?o|"
    r"m\.?p\.?h|m\.?b|ch\.?b|b\.?ch|b\.?m|d\.?phil|r\.?d|c\.?c\.?n|f\.?a\.?c\.?n|facp|frcp\w*|mrcp\w*|"
    r"f\.?r\.?c\.?p\.?(?:\(c\))?|dip\.?|c\.?h\.?|m\.?a\.?s\.?c\.?h|psy\.?d|ed\.?d|pharm\.?d|j\.?d|jr|sr|dr|prof|"
    r"ii|iii|iv|"
    r"\(\w+\.?\))\.?$", re.I)


def authors_of(line: str) -> tuple[Author, ...]:
    """Names from an author line such as "A. HOFFER, M.D., Ph. D. and E Cheraskin DMD, MD"."""
    line = re.sub(r"\d+|\*", "", _ET_AL.sub("", line))
    line = re.sub(r"\bPh\.\s+D\.", "Ph.D.", line)
    authors = []
    for part in re.split(r",|;|\band\b|&", line):
        words = [w for w in part.split() if not _DEGREE.match(w)]
        if len(words) < 2 or not re.fullmatch(r"[A-Za-zÀ-ÿ'’\-]{2,}", words[-1]):
            continue
        *given, family = words
        authors.append(Author(family, " ".join(given)))
    return tuple(authors)
