from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any


@dataclass(frozen=True)
class ImprovementRecommendation:
    recommendation_id: str
    source: str
    board_type: str
    target_type: str
    target_id: str
    severity: str
    reason: str
    suggested_action: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ImprovementRecommendation":
        return cls(
            recommendation_id=str(payload["recommendation_id"]),
            source=str(payload["source"]),
            board_type=str(payload["board_type"]),
            target_type=str(payload["target_type"]),
            target_id=str(payload["target_id"]),
            severity=str(payload["severity"]),
            reason=str(payload["reason"]),
            suggested_action=str(payload["suggested_action"]),
            evidence=[dict(item) for item in payload.get("evidence", [])],
            created_at=str(payload.get("created_at") or datetime.now(UTC).isoformat().replace("+00:00", "Z")),
        )


__all__ = ["ImprovementRecommendation"]
