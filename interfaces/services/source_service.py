from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sources import SourceRegistry
from sources.health import BasicSourceHealthManager


@dataclass(frozen=True)
class SourceSummary:
    source_id: str
    name: str
    source_type: str
    url: str
    reliability: str
    authority_score: float
    enabled: bool
    topics: list[str]
    language: str | None = None
    region: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "source_type": self.source_type,
            "url": self.url,
            "reliability": self.reliability,
            "authority_score": self.authority_score,
            "enabled": self.enabled,
            "topics": list(self.topics),
            "language": self.language,
            "region": self.region,
        }


@dataclass(frozen=True)
class SourceListResult:
    sources: list[SourceSummary]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_count": len(self.sources),
            "sources": [source.to_dict() for source in self.sources],
        }


@dataclass(frozen=True)
class SourceHealthResult:
    health: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_count": len(self.health),
            "health": [dict(item) for item in self.health],
        }


class SourceApplicationService:
    def __init__(
        self,
        *,
        source_registry: SourceRegistry | None = None,
        health_manager: BasicSourceHealthManager | None = None,
    ) -> None:
        if source_registry is None:
            from workflows.daily_intelligence.runner import build_default_source_registry

            source_registry = build_default_source_registry()
        self.source_registry = source_registry
        self.health_manager = health_manager or BasicSourceHealthManager()

    def list_sources(self, *, enabled_only: bool = True) -> SourceListResult:
        return SourceListResult(
            [
                SourceSummary(
                    source_id=source.source_id,
                    name=source.name,
                    source_type=source.source_type.value,
                    url=source.url,
                    reliability=source.reliability.value,
                    authority_score=source.authority_score,
                    enabled=source.enabled,
                    topics=list(source.topics),
                    language=source.language,
                    region=source.region,
                )
                for source in self.source_registry.list_sources(enabled_only=enabled_only)
            ]
        )

    def source_health(self, *, enabled_only: bool = True) -> SourceHealthResult:
        return SourceHealthResult(
            [
                self.health_manager.get(source.source_id).to_dict()
                for source in self.source_registry.list_sources(enabled_only=enabled_only)
            ]
        )
