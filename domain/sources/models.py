from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class SourceType(str, Enum):
    RSS = "rss"
    ATOM = "atom"


class SourceReliability(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


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
