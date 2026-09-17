"""The ingestion audit (decision D-1): extracted references checked by hand against their documents.

A census run over ingested venues yields an audit sheet: a seeded random sample of the references
extracted from its sampled papers, and one row per paper those references came from. A person opens
each paper's document and marks every sampled reference

* ``correct``: one whole reference, with its year, journal, volume and page read right (or rightly left empty);
* ``wrong_fields``: one whole reference, but a field read wrong;
* ``merged``: two or more references run together;
* ``split``: part of a reference;
* ``not_reference``: not a reference at all (a heading, a caption, an abbreviation key),

and gives each paper's true number of references. The census report then states these shares and the
papers' extracted count against their true count. Sheets live under ``data/raw/manual/audit/`` because
the verdicts are hand-entered data; they are written once and never overwritten.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from viveka.census import References, reference_kind, stable_key

AUDIT_DIR = "data/raw/manual/audit"
VERDICTS = ("correct", "wrong_fields", "merged", "split", "not_reference")
REFERENCE_COLUMNS = ("work_id", "ref_index", "document_url", "extracted_text", "year", "journal", "volume",
                     "first_page", "kind", "verdict", "note", "checked_by")
WORK_COLUMNS = ("work_id", "document_url", "extracted_count", "document_count", "checked_by")


class AuditError(ValueError):
    pass


def draw(run_id: str, references: Mapping[str, References], size: int, seed: int) -> list[tuple[str, int]]:
    """Up to ``size`` (work, reference index) pairs, uniformly over every extracted reference, from the seed."""
    pool = sorted((work_id, i) for work_id, refs in references.items() for i in range(refs.total))
    if len(pool) <= size:
        return pool
    rng = np.random.default_rng(np.random.SeedSequence(entropy=seed, spawn_key=(stable_key(run_id),)))
    return [pool[i] for i in sorted(rng.choice(len(pool), size=size, replace=False).tolist())]


def _csv(columns: Sequence[str], rows: Sequence[Mapping[str, object]]) -> bytes:
    sink = io.StringIO(newline="")
    writer = csv.DictWriter(sink, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: "" if row.get(c) is None else row.get(c) for c in columns})
    return sink.getvalue().encode("utf-8")


def sheets(chosen: Sequence[tuple[str, int]], references: Mapping[str, References],
           documents: Mapping[str, str]) -> tuple[bytes, bytes]:
    """The references sheet and the works sheet, with the verdict and count columns left blank."""
    reference_rows = []
    for work_id, index in chosen:
        ref = references[work_id].entries[index]
        reference_rows.append({"work_id": work_id, "ref_index": index + 1, "document_url": documents.get(work_id),
                               "extracted_text": ref.text, "year": ref.year, "journal": ref.journal,
                               "volume": ref.volume, "first_page": ref.first_page, "kind": reference_kind(ref)})
    works = sorted({work_id for work_id, _ in chosen})
    work_rows = [{"work_id": w, "document_url": documents.get(w), "extracted_count": references[w].total}
                 for w in works]
    return _csv(REFERENCE_COLUMNS, reference_rows), _csv(WORK_COLUMNS, work_rows)


def write_once(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "xb") as fh:
            fh.write(content)
    except FileExistsError:
        raise AuditError(f"{path.name} already exists; audit sheets are never overwritten") from None


@dataclass(frozen=True)
class AuditResult:
    references: int
    verdicts: Mapping[str, int]
    works: int
    extracted: int
    documented: int
    checkers: tuple[str, ...]


def _read(path: Path, columns: Sequence[str]) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in columns if c not in (reader.fieldnames or [])]
        if missing:
            raise AuditError(f"{path.name}: missing columns {', '.join(missing)}")
        return list(reader)


def works_sheet(references_sheet: Path) -> Path:
    return references_sheet.with_name(references_sheet.name.replace("-references.csv", "-works.csv"))


def read_audit(references_sheet: Path, sampled: set[str]) -> AuditResult:
    """A completed audit; refused when a verdict or count is missing or the sheet belongs to another sample."""
    if not references_sheet.name.endswith("-references.csv"):
        raise AuditError("the audit is read from its <name>-references.csv sheet")
    refs = _read(references_sheet, REFERENCE_COLUMNS)
    works = _read(works_sheet(references_sheet), WORK_COLUMNS)
    problems = []
    for line, row in enumerate(refs, start=2):
        if row["verdict"].strip() not in VERDICTS or not row["checked_by"].strip():
            problems.append(f"{references_sheet.name}:{line}: verdict must be one of {', '.join(VERDICTS)}, "
                            "with checked_by")
    for line, row in enumerate(works, start=2):
        if not row["document_count"].strip().isdigit() or not row["checked_by"].strip():
            problems.append(f"{works_sheet(references_sheet).name}:{line}: document_count must be a whole number, "
                            "with checked_by")
    outside = sorted({r["work_id"] for r in refs + works} - sampled)
    if outside:
        problems.append(f"audited works not in this census sample: {', '.join(outside[:5])}")
    if problems:
        raise AuditError("; ".join(problems[:5]) + ("; ..." if len(problems) > 5 else ""))
    return AuditResult(
        references=len(refs), verdicts=Counter(r["verdict"].strip() for r in refs), works=len(works),
        extracted=sum(int(r["extracted_count"]) for r in works),
        documented=sum(int(r["document_count"]) for r in works),
        checkers=tuple(sorted({r["checked_by"].strip() for r in refs + works})))


def report_lines(audit: AuditResult, sheet: str) -> list[str]:
    shares = ", ".join(f"{name.replace('_', ' ')} {audit.verdicts.get(name, 0)}" for name in VERDICTS)
    return [f"Extraction audit (`{sheet}`, checked by {', '.join(audit.checkers)}): {audit.references} extracted "
            f"references checked against their documents: {shares}. Their {audit.works} papers have "
            f"{audit.extracted} extracted references against {audit.documented} in the documents.", ""]
