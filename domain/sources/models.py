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
    MANUAL = "manual"


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
    respect_robots: bool = True
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
class SourceFetchRequest:
    request_id: str
    source_id: str
    source_type: SourceType
    url: str | None = None
    query: str | None = None
    timeout_seconds: int = 15
    max_bytes: int = 1_000_000
    user_agent: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    since: datetime | None = None
    limit: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_type", SourceType(self.source_type))
        if not self.request_id:
            raise ValueError("request_id is required")
        if not self.source_id:
            raise ValueError("source_id is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "source_id": self.source_id,
            "source_type": self.source_type.value,
            "url": self.url,
            "query": self.query,
            "timeout_seconds": self.timeout_seconds,
            "max_bytes": self.max_bytes,
            "user_agent": self.user_agent,
            "headers": dict(self.headers),
            "since": _dt(self.since),
            "limit": self.limit,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SourceFetchResult:
    request_id: str
    source_id: str
    success: bool
    status_code: int | None = None
    content_type: str | None = None
    content_bytes: int | None = None
    latency_ms: int | None = None
    raw_artifact_ref: Any | None = None
    error_type: str | None = None
    error_message: str | None = None
    skipped: bool = False
    skip_reason: str | None = None
    fetched_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("request_id is required")
        if not self.source_id:
            raise ValueError("source_id is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "source_id": self.source_id,
            "success": self.success,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "content_bytes": self.content_bytes,
            "latency_ms": self.latency_ms,
            "raw_artifact_ref": (
                self.raw_artifact_ref.to_dict()
                if hasattr(self.raw_artifact_ref, "to_dict")
                else self.raw_artifact_ref
            ),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "fetched_at": _dt(self.fetched_at),
            "metadata": dict(self.metadata),
        }


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
    raw_artifact_ref: Any | None = None
    parse_artifact_ref: Any | None = None
    authors: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    language: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_type", SourceType(self.source_type))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_item_id": self.source_item_id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_type": self.source_type.value,
            "title": self.title,
            "url": self.url,
            "fetched_at": _dt(self.fetched_at),
            "published_at": _dt(self.published_at),
            "summary": self.summary,
            "raw_content": self.raw_content,
            "raw_artifact_ref": _artifact_ref(self.raw_artifact_ref),
            "parse_artifact_ref": _artifact_ref(self.parse_artifact_ref),
            "authors": list(self.authors),
            "tags": list(self.tags),
            "language": self.language,
            "metadata": dict(self.metadata),
        }


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
    source_name: str | None = None
    url: str | None = None
    retryable: bool | None = None
    request_ref: Any | None = None
    response_ref: Any | None = None
    occurred_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.retryable is None:
            object.__setattr__(
                self,
                "retryable",
                _metadata_bool(self.metadata.get("retryable"), default=True),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "url": self.url,
            "retryable": self.retryable,
            "request_ref": _artifact_ref(self.request_ref),
            "response_ref": _artifact_ref(self.response_ref),
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
    source_name: str | None = None
    url: str | None = None
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
            "source_name": self.source_name,
            "url": self.url,
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
    avg_fetch_latency_ms: float | None = None
    errors_by_type: dict[str, int] = field(default_factory=dict)
    items_by_source: dict[str, int] = field(default_factory=dict)
    sources_by_type: dict[str, int] = field(default_factory=dict)
    sources_by_reliability: dict[str, int] = field(default_factory=dict)
    fetched_by_type: dict[str, int] = field(default_factory=dict)
    failed_by_type: dict[str, int] = field(default_factory=dict)
    skipped_by_type: dict[str, int] = field(default_factory=dict)
    items_by_source_type: dict[str, int] = field(default_factory=dict)
    items_by_reliability: dict[str, int] = field(default_factory=dict)
    _fetch_latency_total_ms: float = field(default=0.0, init=False, repr=False)
    _fetch_latency_count: int = field(default=0, init=False, repr=False)

    def record_error(self, error: SourceError) -> None:
        self.errors_by_type[error.error_type] = self.errors_by_type.get(error.error_type, 0) + 1

    def record_source_seen(self, source_type: Any, reliability: Any) -> None:
        _increment(self.sources_by_type, _metric_key(source_type))
        _increment(self.sources_by_reliability, _metric_key(reliability))

    def record_source_fetched(
        self,
        *,
        source_id: str,
        source_type: Any,
        reliability: Any,
        item_count: int,
    ) -> None:
        _increment(self.fetched_by_type, _metric_key(source_type))
        self.items_by_source[source_id] = item_count
        _increment(self.items_by_source_type, _metric_key(source_type), item_count)
        _increment(self.items_by_reliability, _metric_key(reliability), item_count)

    def record_source_failed(self, source_type: Any) -> None:
        _increment(self.failed_by_type, _metric_key(source_type))

    def record_source_skipped(self, source_type: Any) -> None:
        _increment(self.skipped_by_type, _metric_key(source_type))

    def record_fetch_latency(self, latency_ms: float) -> None:
        latency = max(0.0, float(latency_ms))
        self._fetch_latency_total_ms += latency
        self._fetch_latency_count += 1
        self.avg_fetch_latency_ms = round(
            self._fetch_latency_total_ms / self._fetch_latency_count,
            3,
        )

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
            "avg_fetch_latency_ms": self.avg_fetch_latency_ms,
            "errors_by_type": dict(self.errors_by_type),
            "items_by_source": dict(self.items_by_source),
            "sources_by_type": dict(self.sources_by_type),
            "sources_by_reliability": dict(self.sources_by_reliability),
            "fetched_by_type": dict(self.fetched_by_type),
            "failed_by_type": dict(self.failed_by_type),
            "skipped_by_type": dict(self.skipped_by_type),
            "items_by_source_type": dict(self.items_by_source_type),
            "items_by_reliability": dict(self.items_by_reliability),
        }


def _dt(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _metadata_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _artifact_ref(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def _metric_key(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _increment(metrics: dict[str, int], key: str, amount: int = 1) -> None:
    metrics[key] = metrics.get(key, 0) + amount
