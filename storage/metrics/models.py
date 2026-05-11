from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class StorageMetrics:
    runs_count: int = 0
    reports_count: int = 0
    artifacts_count: int = 0
    artifact_bytes_total: int = 0
    events_count: int = 0
    lineage_refs_count: int = 0
    generated_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runs_count": self.runs_count,
            "reports_count": self.reports_count,
            "artifacts_count": self.artifacts_count,
            "artifact_bytes_total": self.artifact_bytes_total,
            "events_count": self.events_count,
            "lineage_refs_count": self.lineage_refs_count,
            "generated_at": self.generated_at.isoformat().replace("+00:00", "Z"),
            "metadata": dict(self.metadata),
        }
