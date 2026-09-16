"""Hand-entered reference lists, for works with no machine-readable list (plan M4a).

The CSV lives under ``data/raw/manual/`` and is recorded as a run input. One row per reference:
``work_id, ref_index, ref_text, doi, entered_by, source_note``. A work with an imported list is
measured like any other; its ``doi`` column is resolved by the same rule as Crossref references.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from viveka.census import Reference, References
from viveka.corpus.ids import normalize_doi

COLUMNS = ("work_id", "ref_index", "ref_text", "doi", "entered_by", "source_note")
MANUAL_DIR = "data/raw/manual"


class ManualImportError(ValueError):
    pass


def load_manual(path: Path) -> dict[str, References]:
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ManualImportError(f"{path.name}: missing columns {', '.join(missing)}")
        by_work: dict[str, dict[int, Reference]] = defaultdict(dict)
        for line, row in enumerate(reader, start=2):
            work_id, index, entered_by = row["work_id"].strip(), row["ref_index"].strip(), row["entered_by"].strip()
            if not work_id or not index.isdigit() or not entered_by or not row["ref_text"].strip():
                raise ManualImportError(f"{path.name}:{line}: work_id, a numeric ref_index, ref_text and entered_by "
                                        "are required")
            if int(index) in by_work[work_id]:
                raise ManualImportError(f"{path.name}:{line}: reference {index} of {work_id} appears twice")
            by_work[work_id][int(index)] = Reference(normalize_doi(row["doi"]), text=row["ref_text"].strip())
    return {work: References(tuple(refs[i] for i in sorted(refs)), "manual") for work, refs in by_work.items()}
