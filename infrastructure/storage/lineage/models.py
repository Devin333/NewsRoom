from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from hashlib import sha256
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class LineageRef:
    run_id: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    relation_type: str = "derived_from"
    lineage_id: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.lineage_id is None:
            object.__setattr__(self, "lineage_id", _stable_lineage_id(self))

    def to_dict(self) -> dict[str, Any]:
        return {
            "lineage_id": self.lineage_id,
            "run_id": self.run_id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "relation_type": self.relation_type,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LineageRef:
        return cls(
            lineage_id=str(payload["lineage_id"]),
            run_id=str(payload["run_id"]),
            source_type=str(payload["source_type"]),
            source_id=str(payload["source_id"]),
            target_type=str(payload["target_type"]),
            target_id=str(payload["target_id"]),
            relation_type=str(payload.get("relation_type") or "derived_from"),
            created_at=_parse_datetime(str(payload["created_at"])),
            metadata=dict(payload.get("metadata") or {}),
        )


def _stable_lineage_id(ref: LineageRef) -> str:
    payload = "|".join(
        [
            ref.run_id,
            ref.source_type,
            ref.source_id,
            ref.target_type,
            ref.target_id,
            ref.relation_type,
        ]
    )
    return f"lin_{sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
