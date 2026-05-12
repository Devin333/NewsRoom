from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class SourceType(str, Enum):
    RSS = "rss"
    ATOM = "atom"
    ARXIV = "arxiv"
    GITHUB = "github"
    HTML = "html"


class SourceReliability(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SourceHealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    COOLING_DOWN = "cooling_down"
    DISABLED = "disabled"


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class SourceDefinition:
    source_id: str
    name: str
    source_type: SourceType
    url: str
    reliability: SourceReliability = SourceReliability.MEDIUM
    authority_score: float = 0.5
    enabled: bool = True
    topics: list[str] = field(default_factory=list)
    language: str | None = None
    region: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_type", SourceType(self.source_type))
        object.__setattr__(self, "reliability", SourceReliability(self.reliability))
        if not self.source_id:
            raise ValueError("source_id is required")
        if not self.name:
            raise ValueError("source name is required")
        if not self.url:
            raise ValueError("source url is required")


@dataclass(frozen=True)
class RawSourceItem:
    source_item_id: str
    source_id: str
    source_name: str
    source_type: SourceType
    title: str
    url: str
    fetched_at: datetime
    published_at: datetime | None = None
    summary: str | None = None
    raw_content: str | None = None
    authors: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    language: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_type", SourceType(self.source_type))


@dataclass(frozen=True)
class NormalizedSourceItem:
    normalized_item_id: str
    source_item_id: str
    source_id: str
    title: str
    normalized_title: str
    url: str
    canonical_url: str
    canonical_url_hash: str
    title_hash: str
    content_hash: str
    source_reliability: SourceReliability
    fetched_at: datetime
    published_at: datetime | None = None
    summary: str | None = None
    normalized_summary: str | None = None
    language: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_reliability", SourceReliability(self.source_reliability))


@dataclass(frozen=True)
class RankedSourceItem:
    ranked_item_id: str
    item: NormalizedSourceItem
    relevance_score: float
    recency_score: float
    reliability_score: float
    novelty_score: float
    final_score: float
    rank_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceError:
    source_id: str
    error_type: str
    error_message: str
    url: str | None = None
    occurred_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "url": self.url,
            "occurred_at": self.occurred_at.isoformat().replace("+00:00", "Z"),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SourcePipelineEvent:
    event_type: str
    source_id: str | None = None
    occurred_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "source_id": self.source_id,
            "occurred_at": self.occurred_at.isoformat().replace("+00:00", "Z"),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SourceHealth:
    source_id: str
    status: SourceHealthStatus = SourceHealthStatus.HEALTHY
    consecutive_failures: int = 0
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    cooldown_until: datetime | None = None
    last_error: SourceError | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", SourceHealthStatus(self.status))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "status": self.status.value,
            "consecutive_failures": self.consecutive_failures,
            "last_success_at": _dt(self.last_success_at),
            "last_failure_at": _dt(self.last_failure_at),
            "cooldown_until": _dt(self.cooldown_until),
            "last_error": self.last_error.to_dict() if self.last_error else None,
        }


@dataclass
class SourcePipelineMetrics:
    sources_total: int = 0
    sources_fetched: int = 0
    sources_failed: int = 0
    sources_skipped: int = 0
    raw_items_count: int = 0
    normalized_items_count: int = 0
    deduplicated_items_count: int = 0
    ranked_items_count: int = 0
    duplicate_count: int = 0
    errors_by_type: dict[str, int] = field(default_factory=dict)
    items_by_source: dict[str, int] = field(default_factory=dict)

    def record_error(self, error: SourceError) -> None:
        self.errors_by_type[error.error_type] = self.errors_by_type.get(error.error_type, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources_total": self.sources_total,
            "sources_fetched": self.sources_fetched,
            "sources_failed": self.sources_failed,
            "sources_skipped": self.sources_skipped,
            "raw_items_count": self.raw_items_count,
            "normalized_items_count": self.normalized_items_count,
            "deduplicated_items_count": self.deduplicated_items_count,
            "ranked_items_count": self.ranked_items_count,
            "duplicate_count": self.duplicate_count,
            "errors_by_type": dict(self.errors_by_type),
            "items_by_source": dict(self.items_by_source),
        }


def _dt(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None
