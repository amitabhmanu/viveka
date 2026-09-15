"""Parquet tables (spec §6), written deterministically so identical inputs give identical hashes."""

from __future__ import annotations

import io
from collections.abc import Iterable
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

_S, _I32, _I64 = pa.string(), pa.int32(), pa.int64()

SCHEMAS: dict[str, pa.Schema] = {
    "works": pa.schema([("work_id", _S), ("doi", _S), ("title", _S), ("year", _I32), ("venue_id", _S),
                        ("venue_name", _S), ("type", _S), ("cited_by_count", _I64), ("source", _S)]),
    "authors": pa.schema([("author_id", _S), ("display_name", _S), ("disambiguation_source", _S),
                          ("confidence", pa.float64())]),
    "authorships": pa.schema([("work_id", _S), ("author_id", _S), ("position", _S),
                              ("institution_ids", pa.list_(_S))]),
    "citations": pa.schema([("citation_id", _S), ("citing_work", _S), ("cited_work", _S)]),
    "frames": pa.schema([("case_id", _S), ("frame_id", _S), ("kind", _S), ("work_id", _S), ("year", _I32)]),
    "contexts": pa.schema([("cited_work", _S), ("citing_doi", _S), ("citing_s2_id", _S), ("context_index", _I32),
                           ("text", _S), ("intents", pa.list_(_S)), ("is_influential", pa.bool_()),
                           ("source", _S)]),
    "census_sample": pa.schema([("case_id", _S), ("frame_id", _S), ("year", _I32), ("work_id", _S),
                                ("status", _S), ("reference_source", _S), ("refs", _I32), ("resolved", _I32)]),
    "coverage": pa.schema([("case_id", _S), ("frame_id", _S), ("kind", _S), ("year", _I32),
                           ("frame_works", _I32), ("sampled", _I32), ("measured", _I32), ("unmeasured", _I32),
                           ("refs", _I32), ("resolved", _I32)]),
}

KEYS: dict[str, tuple[str, ...]] = {
    "works": ("work_id",),
    "authors": ("author_id",),
    "authorships": ("work_id", "author_id", "position"),
    "citations": ("citation_id",),
    "frames": ("case_id", "frame_id", "work_id"),
    "contexts": ("cited_work", "citing_s2_id", "context_index"),
    "census_sample": ("case_id", "frame_id", "year", "work_id"),
    "coverage": ("case_id", "frame_id", "year"),
}


def _sort_key(row: dict, keys: tuple[str, ...]) -> tuple:
    return tuple((row.get(k) is None, "" if row.get(k) is None else row[k]) for k in keys)


def to_parquet(name: str, rows: Iterable[dict]) -> bytes:
    """One row per key (the first seen wins), sorted by key, as Parquet bytes."""
    keys = KEYS[name]
    unique: dict[tuple, dict] = {}
    for row in rows:
        unique.setdefault(tuple(row.get(k) for k in keys), row)
    ordered = sorted(unique.values(), key=lambda r: _sort_key(r, keys))
    table = pa.Table.from_pylist(ordered, schema=SCHEMAS[name])
    sink = io.BytesIO()
    pq.write_table(table, sink, compression="zstd")
    return sink.getvalue()


def read(path: Path) -> list[dict]:
    return pq.read_table(path).to_pylist()
