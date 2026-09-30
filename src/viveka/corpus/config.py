"""Corpus settings (registry/corpus.yaml) as immutable objects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CORPUS = "registry/corpus.yaml"
LIVE_SOURCES = ("openalex", "crossref", "semanticscholar")


@dataclass(frozen=True)
class Source:
    name: str
    kind: str
    url: str
    terms_reference: str | None


@dataclass(frozen=True)
class CensusSettings:
    works_per_year: int
    max_unmeasured_share: float
    seed: int
    resolution: str
    doiless_sample_per_work: int
    match_year_tolerance: int
    paper_types: frozenset[str]
    reference_classification: str
    rescue_min_score: float
    rescue_title_share: float


@dataclass(frozen=True)
class Venue:
    """A community venue ingested directly from its own archive (decision D-1)."""

    venue_id: str
    name: str
    issn_l: str | None
    adapter: str
    url: str
    aliases: tuple[str, ...]
    types: Mapping[str, str]  # the archive's item type or section -> work type
    default_type: str
    first_volume_year: int | None = None
    type_patterns: tuple[tuple[str, str], ...] = ()  # (regex over a section title, work type), tried in order
    record_pattern: str | None = None  # endnote_v1: regex over a record's proceedings or journal title
    last_year: int | None = None  # the venue's last year in this archive (later issues are indexed elsewhere)

    def work_type(self, section: str | None) -> str:
        """A section's work type: its exact name in ``types``, else the first matching pattern, else the default."""
        import re

        name = " ".join((section or "").split())
        for key, value in self.types.items():
            if key.lower() == name.lower():
                return value
        for pattern, value in self.type_patterns:
            if re.search(pattern, name, re.I):
                return value
        return self.default_type


@dataclass(frozen=True)
class IngestionSettings:
    requests_per_second: float
    text_extraction: str
    reference_extraction: str
    catalogue_match: str
    venues: Mapping[str, Venue]
    audit_references: int = 60


@dataclass(frozen=True)
class SocialSettings:
    """Stage S3 settings (corpus.yaml ``social``): graph rule, Leiden seed, lineage floor, S4's resolution."""

    graph: str
    leiden_seed: int
    lineage_min_members: int
    primary_resolution: float
    bearing_results: str | None = None  # S4's pre-coding rule for the results bearing on p
    lineage_works: str = "own_frames_v1"  # which of its members' papers a lineage is credited with (S4, S2C)


@dataclass(frozen=True)
class CorpusConfig:
    sources: Mapping[str, Source]
    api: Mapping[str, Mapping[str, Any]]
    census: CensusSettings
    ingestion: IngestionSettings | None = None
    calibration_selection: tuple[str, float, int] | None = None  # (measure, largest overlap, core works), D-10
    social: SocialSettings | None = None

    def venue(self, venue_id: str) -> Venue:
        if self.ingestion is None or venue_id not in self.ingestion.venues:
            raise KeyError(f"no ingested venue {venue_id!r} in {CORPUS}")
        return self.ingestion.venues[venue_id]

    def rate(self, source: str) -> float:
        return float(self.api[source]["requests_per_second"])

    def terms(self, source: str) -> str | None:
        found = self.sources.get(source)
        return found.terms_reference if found else None

    def price(self, source: str, kind: str) -> float:
        return float(self.api.get(source, {}).get("prices_usd", {}).get(kind, 0.0))

    @property
    def openalex(self) -> Mapping[str, Any]:
        return self.api["openalex"]

    @property
    def semanticscholar(self) -> Mapping[str, Any]:
        return self.api["semanticscholar"]


def from_mapping(data: Mapping[str, Any]) -> CorpusConfig:
    sources = {s["name"]: Source(s["name"], s["kind"], s["url"], s.get("terms_reference")) for s in data["sources"]}
    census = data["census"]
    ingestion = None
    if data.get("ingestion"):
        block = data["ingestion"]
        venues = {vid: Venue(vid, v["name"], v.get("issn_l"), v["adapter"], v["url"].rstrip("/"),
                             tuple(v["aliases"]), dict(v.get("types") or {}), v["default_type"],
                             v.get("first_volume_year"),
                             tuple((str(k), str(t)) for k, t in (v.get("type_patterns") or {}).items()),
                             v.get("record_pattern"), v.get("last_year"))
                  for vid, v in (block.get("venues") or {}).items()}
        ingestion = IngestionSettings(float(block["requests_per_second"]), str(block["text_extraction"]),
                                      str(block["reference_extraction"]), str(block["catalogue_match"]), venues,
                                      int(block["audit_references"]))
    return CorpusConfig(
        sources=sources,
        api={name: dict(settings) for name, settings in data["api"].items()},
        census=CensusSettings(int(census["works_per_year"]), float(census["max_unmeasured_share"]),
                              int(census["seed"]), str(census["resolution"]), int(census["doiless_sample_per_work"]),
                              int(census["match_year_tolerance"]), frozenset(census["paper_types"]),
                              str(census["reference_classification"]),
                              float(census["bibliographic_rescue"]["min_score"]),
                              float(census["bibliographic_rescue"]["title_word_share"])),
        ingestion=ingestion,
        calibration_selection=(str(data["calibration_selection"]["overlap_measure"]),
                               float(data["calibration_selection"]["max_overlap"]),
                               int(data["calibration_selection"].get("core_min_works", 1)))
        if data.get("calibration_selection") else None,
        social=SocialSettings(str(data["social"]["graph"]), int(data["social"]["leiden_seed"]),
                              int(data["social"]["lineage_min_members"]), float(data["social"]["primary_resolution"]),
                              data["social"].get("bearing_results"),
                              str(data["social"]["lineage_works"]))
        if data.get("social") else None,
    )


def load_corpus_config(root: Path) -> CorpusConfig:
    return from_mapping(yaml.safe_load((root / CORPUS).read_text(encoding="utf-8")))
