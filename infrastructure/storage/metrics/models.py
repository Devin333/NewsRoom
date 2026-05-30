from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class StorageMetrics:
    runs_count: int = 0
    reports_count: int = 0
    artifacts_count: int = 0
    source_items_count: int = 0
    evidence_items_count: int = 0
    claims_count: int = 0
    quality_results_count: int = 0
    vector_documents_count: int = 0
    artifact_bytes_total: int = 0
    events_count: int = 0
    lineage_refs_count: int = 0
    postgres_query_latency_ms: float | None = None
    vector_search_latency_ms: float | None = None
    cache_hit_rate: float | None = None
    generated_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runs_count": self.runs_count,
            "reports_count": self.reports_count,
            "artifacts_count": self.artifacts_count,
            "source_items_count": self.source_items_count,
            "evidence_items_count": self.evidence_items_count,
            "claims_count": self.claims_count,
            "quality_results_count": self.quality_results_count,
            "vector_documents_count": self.vector_documents_count,
            "artifact_bytes_total": self.artifact_bytes_total,
            "events_count": self.events_count,
            "lineage_refs_count": self.lineage_refs_count,
            "postgres_query_latency_ms": self.postgres_query_latency_ms,
            "vector_search_latency_ms": self.vector_search_latency_ms,
            "cache_hit_rate": self.cache_hit_rate,
            "generated_at": self.generated_at.isoformat().replace("+00:00", "Z"),
            "metadata": dict(self.metadata),
        }
