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


@dataclass(frozen=True)
class CorpusConfig:
    sources: Mapping[str, Source]
    api: Mapping[str, Mapping[str, Any]]
    census: CensusSettings

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
    return CorpusConfig(
        sources=sources,
        api={name: dict(settings) for name, settings in data["api"].items()},
        census=CensusSettings(int(census["works_per_year"]), float(census["max_unmeasured_share"]),
                              int(census["seed"]), str(census["resolution"])),
    )


def load_corpus_config(root: Path) -> CorpusConfig:
    return from_mapping(yaml.safe_load((root / CORPUS).read_text(encoding="utf-8")))
