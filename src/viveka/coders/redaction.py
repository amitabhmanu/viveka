"""Mechanical redaction (stage S6; framework, "Blinding by redaction, then tested").

Field-identifying words are replaced by bracketed placeholders from registered dictionaries, applied
mechanically. Nothing is rewritten freely, because a rewriter is itself a coder that knows the field. Every
dictionary is applied to every item, whichever subject the item comes from, so a placeholder says nothing about
which dictionary supplied it.

A dictionary (registry/redaction/<subject>.yaml, format 1) lists entries under the placeholder they become:
``terms`` -> [TERM], ``names`` -> [NAME], ``places`` -> [PLACE], ``organisations`` -> [ORG]. An entry is
matched case-insensitively as whole words; a trailing ``*`` also matches any word ending (``homeopath*`` matches
homeopathy, homeopathic, homeopaths); spaces in an entry match any run of spaces or hyphens.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

REDACTION = Path("registry") / "redaction"
PLACEHOLDERS = {"terms": "[TERM]", "names": "[NAME]", "places": "[PLACE]", "organisations": "[ORG]"}


class RedactionError(ValueError):
    pass


@dataclass(frozen=True)
class Redactor:
    pattern: re.Pattern | None
    placeholder_of: Mapping[str, str]  # lower-cased literal entry text -> placeholder, for exact entries
    stems: tuple[tuple[str, str], ...]  # (lower-cased stem, placeholder) for '*' entries, longest first

    def __call__(self, text: str) -> str:
        if self.pattern is None:
            return text
        return self.pattern.sub(self._replacement, text)

    def _replacement(self, match: re.Match) -> str:
        found = re.sub(r"[\s-]+", " ", match.group(0).lower())
        if found in self.placeholder_of:
            return self.placeholder_of[found]
        for stem, placeholder in self.stems:
            if found.startswith(stem):
                return placeholder
        return "[TERM]"


def _entry_regex(entry: str) -> str:
    stem = entry.endswith("*")
    words = entry.rstrip("*").strip().split()
    body = r"[\s-]+".join(re.escape(w) for w in words)
    return rf"\b{body}\w*" if stem else rf"\b{body}\b"


def build(dictionaries: Iterable[Mapping]) -> Redactor:
    """One redactor from every dictionary given; longer entries win where entries overlap."""
    entries: dict[str, str] = {}
    for dictionary in dictionaries:
        for key, placeholder in PLACEHOLDERS.items():
            for raw in dictionary.get(key) or []:
                entry = " ".join(str(raw).split())
                if not entry or entry == "*":
                    raise RedactionError(f"empty redaction entry under {key!r}")
                entries.setdefault(entry.lower(), placeholder)
    if not entries:
        return Redactor(None, {}, ())
    ordered = sorted(entries, key=lambda e: (-len(e.rstrip("*")), e))
    pattern = re.compile("|".join(_entry_regex(e) for e in ordered), re.IGNORECASE)
    exact = {e: p for e, p in entries.items() if not e.endswith("*")}
    stems = tuple((e.rstrip("*").strip(), p) for e, p in sorted(entries.items(), key=lambda kv: -len(kv[0]))
                  if e.endswith("*"))
    return Redactor(pattern, exact, stems)


def load_dictionaries(root: Path, subjects: Sequence[str] | None = None) -> list[dict]:
    """The registered dictionaries (all of them unless subjects are named), each checked against format 1."""
    folder = root / REDACTION
    paths = sorted(folder.glob("*.yaml")) if subjects is None else [folder / f"{s}.yaml" for s in subjects]
    out = []
    for path in paths:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        problems = check(data)
        if problems:
            raise RedactionError(f"{path.name}: " + "; ".join(problems))
        out.append(data)
    return out


_TOKEN = re.compile(r"[^\W\d_][\w'’\-]*[^\W_]|[^\W\d_]")
_PLACEHOLDER_WORDS = frozenset({"term", "name", "place", "org", "ref", "cited"})
# Function words carry no field and only differ by style; leaving them out lets content words surface.
_STOPWORDS = frozenset("""a about above after again against all also although am among an and any are as at be
because been before being below between both but by can could did do does doing down during each either et
etc few for from further had has have having he her here hers him his how however i if in into is it its
itself just may might more most much must my no nor not now of off on once only or other our ours out over
own per same she should since so some such than that the their theirs them then there these they this those
through thus to too under until up upon very via was we were what when where whether which while who whom
whose why will with within without would yet you your al fig figs table eg ie""".split())


def distinctive_terms(texts_by_subject: Mapping[str, Iterable[str]], top: int = 60, min_count: int = 5,
                      min_z: float = 1.96) -> dict[str, list[tuple[str, float, int]]]:
    """Candidate dictionary entries: for each subject, the words most over-represented in its texts against all
    the others, by the log-odds ratio with an informative Dirichlet prior (Monroe, Colaresi and Quinn 2008),
    scored as a z value. Texts are expected already redacted, so what is listed is what still leaks. The list is
    for review: nothing enters a dictionary without the owner."""
    import math

    counts: dict[str, Counter] = {}
    for subject, texts in texts_by_subject.items():
        c: Counter = Counter()
        for text in texts:
            c.update(w for w in (t.lower() for t in _TOKEN.findall(text))
                     if w not in _PLACEHOLDER_WORDS and w not in _STOPWORDS and len(w) > 2)
        counts[subject] = c
    total = Counter()
    for c in counts.values():
        total.update(c)
    alpha0 = sum(total.values()) or 1
    prior = {w: n / alpha0 * 500.0 for w, n in total.items()}  # prior pseudo-counts, 500 in all
    a_sum = sum(prior.values())
    out = {}
    for subject, c in counts.items():
        rest = total - c
        n_i, n_j = sum(c.values()), sum(rest.values())
        scored = []
        for w, y_i in c.items():
            if y_i < min_count:
                continue
            a = prior[w]
            y_j = rest.get(w, 0)
            delta = (math.log((y_i + a) / (n_i + a_sum - y_i - a))
                     - math.log((y_j + a) / (n_j + a_sum - y_j - a)))
            z = delta / math.sqrt(1 / (y_i + a) + 1 / (y_j + a))
            if z >= min_z:  # significantly over-represented only
                scored.append((w, round(z, 2), y_i))
        out[subject] = sorted(scored, key=lambda s: -s[1])[:top]
    return out


def check(data: object) -> list[str]:
    """Format 1 of a redaction dictionary (the JSON Schema joins registry/schemas/ at the next freeze)."""
    if not isinstance(data, dict):
        return ["a redaction dictionary is a YAML mapping"]
    problems = []
    if data.get("format") != 1:
        problems.append("format must be 1")
    if not isinstance(data.get("subject"), str):
        problems.append("subject must name the field or case")
    unknown = set(data) - {"format", "subject", "note", *PLACEHOLDERS}
    if unknown:
        problems.append(f"unknown keys {sorted(unknown)}")
    for key in PLACEHOLDERS:
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            problems.append(f"{key} must be a list of non-empty strings")
    return problems
