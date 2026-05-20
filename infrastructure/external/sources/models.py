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
    OFFICIAL_BLOG = "official_blog"
    WEB_PAGE = "web_page"
    MANUAL = "manual"
    HACKERNEWS = "hackernews"
    REDDIT = "reddit"
    LOBSTERS = "lobsters"
    STACKOVERFLOW = "stackoverflow"
    DEVTO = "devto"
    MEDIUM = "medium"


class SourceReliability(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SourceHealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    COOLING_DOWN = "cooling_down"
    DISABLED = "disabled"


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Lineage:
    source_id: str
    source_item_id: str | None = None
    normalized_item_id: str | None = None
    ranked_item_id: str | None = None
    raw_url: str | None = None
    canonical_url: str | None = None
    fetched_at: datetime | None = None
    published_at: datetime | None = None
    raw_artifact_ref: Any | None = None
    parse_artifact_ref: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "source_id": self.source_id,
            "source_item_id": self.source_item_id,
            "normalized_item_id": self.normalized_item_id,
            "ranked_item_id": self.ranked_item_id,
            "raw_url": self.raw_url,
            "canonical_url": self.canonical_url,
            "fetched_at": _dt(self.fetched_at),
            "published_at": _dt(self.published_at),
            "raw_artifact_ref": _artifact_ref(self.raw_artifact_ref),
            "parse_artifact_ref": _artifact_ref(self.parse_artifact_ref),
            "metadata": dict(self.metadata),
        }
        return {key: value for key, value in payload.items() if value not in (None, {}, [])}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Lineage:
        return cls(
            source_id=str(payload["source_id"]),
            source_item_id=_optional_str(payload.get("source_item_id")),
            normalized_item_id=_optional_str(payload.get("normalized_item_id")),
            ranked_item_id=_optional_str(payload.get("ranked_item_id")),
            raw_url=_optional_str(payload.get("raw_url")),
            canonical_url=_optional_str(payload.get("canonical_url")),
            fetched_at=_parse_datetime_optional(payload.get("fetched_at")),
            published_at=_parse_datetime_optional(payload.get("published_at")),
            raw_artifact_ref=payload.get("raw_artifact_ref"),
            parse_artifact_ref=payload.get("parse_artifact_ref"),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class SourceDefinition:
    source_id: str
    name: str
    source_type: SourceType
    url: str
    reliability: SourceReliability = SourceReliability.MEDIUM
    authority_score: float = 0.5
    enabled: bool = True
    fetch_interval_seconds: int = 3600
    respect_robots: bool = True
    user_agent: str | None = None
    topics: list[str] = field(default_factory=list)
    category: str | None = None
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
        if self.fetch_interval_seconds < 1:
            raise ValueError("fetch_interval_seconds must be at least 1")
        if self.user_agent is not None:
            user_agent = str(self.user_agent).strip()
            if not user_agent:
                raise ValueError("user_agent must not be blank")
            object.__setattr__(self, "user_agent", user_agent)


@dataclass(frozen=True)
class SourceFetchRequest:
    request_id: str
    source_id: str
    source_type: SourceType
    url: str | None = None
    query: str | None = None
    timeout_seconds: int = 15
    max_bytes: int = 1_000_000
    max_redirects: int = 3
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
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_bytes < 1:
            raise ValueError("max_bytes must be at least 1")
        if self.max_redirects < 0:
            raise ValueError("max_redirects must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "source_id": self.source_id,
            "source_type": self.source_type.value,
            "url": self.url,
            "query": self.query,
            "timeout_seconds": self.timeout_seconds,
            "max_bytes": self.max_bytes,
            "max_redirects": self.max_redirects,
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
        raw_artifact_ref = self.raw_artifact_ref
        return {
            "request_id": self.request_id,
            "source_id": self.source_id,
            "success": self.success,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "content_bytes": self.content_bytes,
            "latency_ms": self.latency_ms,
            "raw_artifact_ref": (
                raw_artifact_ref.to_dict()
                if raw_artifact_ref is not None and hasattr(raw_artifact_ref, "to_dict")
                else raw_artifact_ref
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
    lineage: Lineage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_type", SourceType(self.source_type))
        if self.lineage is None:
            object.__setattr__(
                self,
                "lineage",
                Lineage(
                    source_id=self.source_id,
                    source_item_id=self.source_item_id,
                    raw_url=self.url,
                    fetched_at=self.fetched_at,
                    published_at=self.published_at,
                    raw_artifact_ref=self.raw_artifact_ref,
                    parse_artifact_ref=self.parse_artifact_ref,
                ),
            )

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
            "lineage": self.lineage.to_dict() if self.lineage else None,
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
    lineage: Lineage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_reliability", SourceReliability(self.source_reliability))
        if self.lineage is None:
            metadata_lineage = self.metadata.get("lineage") if isinstance(self.metadata.get("lineage"), dict) else None
            if metadata_lineage is not None:
                object.__setattr__(self, "lineage", Lineage.from_dict(metadata_lineage))
            else:
                object.__setattr__(
                    self,
                    "lineage",
                    Lineage(
                        source_id=self.source_id,
                        source_item_id=self.source_item_id,
                        normalized_item_id=self.normalized_item_id,
                        raw_url=self.url,
                        canonical_url=self.canonical_url,
                        fetched_at=self.fetched_at,
                        published_at=self.published_at,
                    ),
                )


@dataclass(frozen=True)
class RankedSourceItem:
    ranked_item_id: str
    item: NormalizedSourceItem
    relevance_score: float
    recency_score: float
    reliability_score: float
    novelty_score: float
    final_score: float
    authority_score: float = 0.0
    duplicate_cluster_score: float = 0.0
    historical_importance_score: float = 0.0
    subscription_match_score: float = 0.0
    source_quality_score: float | None = None
    rank_reason: str = ""
    lineage: Lineage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.lineage is None:
            metadata_lineage = self.metadata.get("lineage") if isinstance(self.metadata.get("lineage"), dict) else None
            if metadata_lineage is not None:
                object.__setattr__(self, "lineage", Lineage.from_dict(metadata_lineage))
            else:
                item_lineage = self.item.lineage
                object.__setattr__(
                    self,
                    "lineage",
                    Lineage(
                        source_id=self.item.source_id,
                        source_item_id=self.item.source_item_id,
                        normalized_item_id=self.item.normalized_item_id,
                        ranked_item_id=self.ranked_item_id,
                        raw_url=self.item.url,
                        canonical_url=self.item.canonical_url,
                        fetched_at=self.item.fetched_at,
                        published_at=self.item.published_at,
                        raw_artifact_ref=(item_lineage.raw_artifact_ref if item_lineage else None),
                        parse_artifact_ref=(item_lineage.parse_artifact_ref if item_lineage else None),
                    ),
                )


@dataclass(frozen=True)
class DuplicateGroup:
    group_id: str
    kept_item_id: str
    duplicate_item_ids: list[str]
    reasons: list[str] = field(default_factory=list)
    canonical_urls: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "kept_item_id": self.kept_item_id,
            "duplicate_item_ids": list(self.duplicate_item_ids),
            "reasons": list(self.reasons),
            "canonical_urls": list(self.canonical_urls),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class DedupResult:
    kept_items: list[NormalizedSourceItem]
    duplicate_groups: list[DuplicateGroup]
    dropped_items: list[NormalizedSourceItem]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kept_item_count": len(self.kept_items),
            "duplicate_group_count": len(self.duplicate_groups),
            "dropped_item_count": len(self.dropped_items),
            "kept_item_ids": [item.normalized_item_id for item in self.kept_items],
            "dropped_item_ids": [item.normalized_item_id for item in self.dropped_items],
            "duplicate_groups": [group.to_dict() for group in self.duplicate_groups],
            "metadata": dict(self.metadata),
        }


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
    success_count_24h: int = 0
    failure_count_24h: int = 0
    avg_latency_ms_24h: float | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    cooldown_until: datetime | None = None
    last_error: SourceError | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        status = SourceHealthStatus(self.status)
        if status == SourceHealthStatus.COOLING_DOWN:
            status = SourceHealthStatus.DOWN
        object.__setattr__(self, "status", status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "url": self.url,
            "status": self.status.value,
            "health_status": self.status.value,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_failure_count": self.consecutive_failures,
            "success_count_24h": self.success_count_24h,
            "failure_count_24h": self.failure_count_24h,
            "avg_latency_ms_24h": self.avg_latency_ms_24h,
            "last_success_at": _dt(self.last_success_at),
            "last_failure_at": _dt(self.last_failure_at),
            "cooldown_until": _dt(self.cooldown_until),
            "last_error_type": self.last_error.error_type if self.last_error else None,
            "last_error_message": self.last_error.error_message if self.last_error else None,
            "last_error": self.last_error.to_dict() if self.last_error else None,
            "metadata": dict(self.metadata),
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


@dataclass(frozen=True)
class SourceCoverageReport:
    coverage_status: str
    selected_source_count: int
    attempted_source_count: int
    fetched_source_count: int
    failed_source_count: int
    skipped_source_count: int
    unattempted_source_count: int
    raw_item_count: int
    normalized_item_count: int
    deduplicated_item_count: int
    ranked_item_count: int
    duplicate_item_count: int
    error_count: int
    fetch_success_ratio: float
    attempted_source_ratio: float
    item_yield_ratio: float
    avg_fetch_latency_ms: float | None = None
    sources_by_type: dict[str, int] = field(default_factory=dict)
    sources_by_reliability: dict[str, int] = field(default_factory=dict)
    fetched_by_type: dict[str, int] = field(default_factory=dict)
    failed_by_type: dict[str, int] = field(default_factory=dict)
    skipped_by_type: dict[str, int] = field(default_factory=dict)
    items_by_source: dict[str, int] = field(default_factory=dict)
    items_by_source_type: dict[str, int] = field(default_factory=dict)
    items_by_reliability: dict[str, int] = field(default_factory=dict)
    errors_by_type: dict[str, int] = field(default_factory=dict)
    skipped_source_ids: list[str] = field(default_factory=list)
    failed_source_ids: list[str] = field(default_factory=list)
    partial_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage_status": self.coverage_status,
            "selected_source_count": self.selected_source_count,
            "attempted_source_count": self.attempted_source_count,
            "fetched_source_count": self.fetched_source_count,
            "failed_source_count": self.failed_source_count,
            "skipped_source_count": self.skipped_source_count,
            "unattempted_source_count": self.unattempted_source_count,
            "raw_item_count": self.raw_item_count,
            "normalized_item_count": self.normalized_item_count,
            "deduplicated_item_count": self.deduplicated_item_count,
            "ranked_item_count": self.ranked_item_count,
            "duplicate_item_count": self.duplicate_item_count,
            "error_count": self.error_count,
            "fetch_success_ratio": self.fetch_success_ratio,
            "attempted_source_ratio": self.attempted_source_ratio,
            "item_yield_ratio": self.item_yield_ratio,
            "avg_fetch_latency_ms": self.avg_fetch_latency_ms,
            "sources_by_type": dict(self.sources_by_type),
            "sources_by_reliability": dict(self.sources_by_reliability),
            "fetched_by_type": dict(self.fetched_by_type),
            "failed_by_type": dict(self.failed_by_type),
            "skipped_by_type": dict(self.skipped_by_type),
            "items_by_source": dict(self.items_by_source),
            "items_by_source_type": dict(self.items_by_source_type),
            "items_by_reliability": dict(self.items_by_reliability),
            "errors_by_type": dict(self.errors_by_type),
            "skipped_source_ids": list(self.skipped_source_ids),
            "failed_source_ids": list(self.failed_source_ids),
            "partial_reasons": list(self.partial_reasons),
        }


@dataclass(frozen=True)
class SourceConnectorDispatchReport:
    total_dispatch_count: int
    success_count: int
    failed_count: int
    skipped_count: int
    connector_counts: dict[str, int] = field(default_factory=dict)
    success_by_connector: dict[str, int] = field(default_factory=dict)
    failed_by_connector: dict[str, int] = field(default_factory=dict)
    skipped_by_connector: dict[str, int] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_dispatch_count": self.total_dispatch_count,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "connector_counts": dict(self.connector_counts),
            "success_by_connector": dict(self.success_by_connector),
            "failed_by_connector": dict(self.failed_by_connector),
            "skipped_by_connector": dict(self.skipped_by_connector),
            "rows": [dict(row) for row in self.rows],
        }


@dataclass(frozen=True)
class SourceItemQualityScore:
    normalized_item_id: str
    source_item_id: str
    source_id: str
    quality_score: float
    reliability_score: float
    authority_score: float
    traceability_score: float
    freshness_score: float
    content_score: float
    language_score: float
    penalties: list[str] = field(default_factory=list)
    score_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "normalized_item_id": self.normalized_item_id,
            "source_item_id": self.source_item_id,
            "source_id": self.source_id,
            "quality_score": self.quality_score,
            "reliability_score": self.reliability_score,
            "authority_score": self.authority_score,
            "traceability_score": self.traceability_score,
            "freshness_score": self.freshness_score,
            "content_score": self.content_score,
            "language_score": self.language_score,
            "penalties": list(self.penalties),
            "score_reason": self.score_reason,
        }


@dataclass(frozen=True)
class SourceSelectionReport:
    topic: str
    selected_source_count: int
    matched_source_count: int
    fallback_used: bool
    selected_source_ids: list[str] = field(default_factory=list)
    selected_sources: list[dict[str, Any]] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "selected_source_count": self.selected_source_count,
            "matched_source_count": self.matched_source_count,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "selected_source_ids": list(self.selected_source_ids),
            "selected_sources": [dict(source) for source in self.selected_sources],
            "filters": dict(self.filters),
        }


@dataclass(frozen=True)
class SourceGovernanceFinding:
    finding_type: str
    severity: str
    source_id: str
    message: str
    action: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_type": self.finding_type,
            "severity": self.severity,
            "source_id": self.source_id,
            "message": self.message,
            "action": self.action,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SourceGovernanceReport:
    finding_count: int
    blocking_finding_count: int
    requires_strict_verification_source_ids: list[str] = field(default_factory=list)
    findings: list[SourceGovernanceFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_count": self.finding_count,
            "blocking_finding_count": self.blocking_finding_count,
            "requires_strict_verification_source_ids": list(
                self.requires_strict_verification_source_ids
            ),
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass(frozen=True)
class SourceRankingScore:
    ranked_item_id: str
    normalized_item_id: str
    source_item_id: str
    source_id: str
    title: str
    url: str
    relevance_score: float
    recency_score: float
    reliability_score: float
    authority_score: float
    novelty_score: float
    final_score: float
    duplicate_cluster_score: float = 0.0
    historical_importance_score: float = 0.0
    subscription_match_score: float = 0.0
    source_quality_score: float | None = None
    rank_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ranked_item_id": self.ranked_item_id,
            "normalized_item_id": self.normalized_item_id,
            "source_item_id": self.source_item_id,
            "source_id": self.source_id,
            "title": self.title,
            "url": self.url,
            "relevance_score": self.relevance_score,
            "recency_score": self.recency_score,
            "reliability_score": self.reliability_score,
            "authority_score": self.authority_score,
            "novelty_score": self.novelty_score,
            "duplicate_cluster_score": self.duplicate_cluster_score,
            "historical_importance_score": self.historical_importance_score,
            "subscription_match_score": self.subscription_match_score,
            "source_quality_score": self.source_quality_score,
            "final_score": self.final_score,
            "rank_reason": self.rank_reason,
        }


@dataclass(frozen=True)
class SourceFreshnessReport:
    freshness_status: str
    ranked_item_count: int
    fresh_item_count: int
    stale_item_count: int
    missing_published_at_count: int
    future_timestamp_count: int
    buckets: dict[str, int] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "freshness_status": self.freshness_status,
            "ranked_item_count": self.ranked_item_count,
            "fresh_item_count": self.fresh_item_count,
            "stale_item_count": self.stale_item_count,
            "missing_published_at_count": self.missing_published_at_count,
            "future_timestamp_count": self.future_timestamp_count,
            "buckets": dict(self.buckets),
            "rows": [dict(row) for row in self.rows],
        }


@dataclass(frozen=True)
class SourceFallbackReport:
    total_fallback_count: int
    selection_fallback_used: bool
    item_fallback_count: int
    error_fallback_count: int
    selection_fallback_reason: str | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_fallback_count": self.total_fallback_count,
            "selection_fallback_used": self.selection_fallback_used,
            "selection_fallback_reason": self.selection_fallback_reason,
            "item_fallback_count": self.item_fallback_count,
            "error_fallback_count": self.error_fallback_count,
            "rows": [dict(row) for row in self.rows],
        }


@dataclass(frozen=True)
class SourceErrorPolicyReport:
    total_error_count: int
    retryable_error_count: int
    non_retryable_error_count: int
    health_affecting_error_count: int
    workflow_blocking_error_count: int
    operator_action_required_count: int
    errors_by_type: dict[str, int] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_error_count": self.total_error_count,
            "retryable_error_count": self.retryable_error_count,
            "non_retryable_error_count": self.non_retryable_error_count,
            "health_affecting_error_count": self.health_affecting_error_count,
            "workflow_blocking_error_count": self.workflow_blocking_error_count,
            "operator_action_required_count": self.operator_action_required_count,
            "errors_by_type": dict(self.errors_by_type),
            "rows": [dict(row) for row in self.rows],
        }


@dataclass(frozen=True)
class SourceHealthReport:
    health_update_count: int
    status_counts: dict[str, int] = field(default_factory=dict)
    down_source_ids: list[str] = field(default_factory=list)
    cooling_down_source_ids: list[str] = field(default_factory=list)
    degraded_source_ids: list[str] = field(default_factory=list)
    disabled_source_ids: list[str] = field(default_factory=list)
    max_consecutive_failures: int = 0
    rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "health_update_count": self.health_update_count,
            "status_counts": dict(self.status_counts),
            "down_source_ids": list(self.down_source_ids),
            "cooling_down_source_ids": list(self.cooling_down_source_ids),
            "degraded_source_ids": list(self.degraded_source_ids),
            "disabled_source_ids": list(self.disabled_source_ids),
            "max_consecutive_failures": self.max_consecutive_failures,
            "rows": [dict(row) for row in self.rows],
        }


@dataclass(frozen=True)
class SourceTraceabilityIssue:
    ranked_item_id: str
    normalized_item_id: str
    source_item_id: str
    source_id: str
    issue_type: str
    field: str
    expected: str | None = None
    actual: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ranked_item_id": self.ranked_item_id,
            "normalized_item_id": self.normalized_item_id,
            "source_item_id": self.source_item_id,
            "source_id": self.source_id,
            "issue_type": self.issue_type,
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass(frozen=True)
class SourceTraceabilityReport:
    traceability_status: str
    ranked_item_count: int
    traceable_item_count: int
    untraceable_item_count: int
    issue_count: int
    rows: list[dict[str, Any]] = field(default_factory=list)
    issues: list[SourceTraceabilityIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "traceability_status": self.traceability_status,
            "ranked_item_count": self.ranked_item_count,
            "traceable_item_count": self.traceable_item_count,
            "untraceable_item_count": self.untraceable_item_count,
            "issue_count": self.issue_count,
            "rows": [dict(row) for row in self.rows],
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class SourceQualitySummaryReport:
    item_count: int
    average_quality_score: float | None = None
    min_quality_score: float | None = None
    max_quality_score: float | None = None
    low_quality_count: int = 0
    weak_traceability_count: int = 0
    penalty_counts: dict[str, int] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_count": self.item_count,
            "average_quality_score": self.average_quality_score,
            "min_quality_score": self.min_quality_score,
            "max_quality_score": self.max_quality_score,
            "low_quality_count": self.low_quality_count,
            "weak_traceability_count": self.weak_traceability_count,
            "penalty_counts": dict(self.penalty_counts),
            "rows": [dict(row) for row in self.rows],
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


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_datetime_optional(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
