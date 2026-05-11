from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class QualityEvent:
    event_type: str
    occurred_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat().replace("+00:00", "Z"),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class QualityGateMetrics:
    evidence_items_count: int
    unsupported_urls_count: int
    missing_section_sources_count: int
    unsupported_sections_count: int
    blocked: bool
    decision: str
    citation_coverage_score: float
    support_coverage: float
    quality_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_items_count": self.evidence_items_count,
            "unsupported_urls_count": self.unsupported_urls_count,
            "missing_section_sources_count": self.missing_section_sources_count,
            "unsupported_sections_count": self.unsupported_sections_count,
            "blocked": self.blocked,
            "decision": self.decision,
            "citation_coverage_score": self.citation_coverage_score,
            "support_coverage": self.support_coverage,
            "quality_score": self.quality_score,
        }
