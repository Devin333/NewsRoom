from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from framework.shared.json import to_jsonable
from framework.shared.time import format_datetime, parse_datetime, utc_now


@dataclass(frozen=True)
class CheckpointReference:
    checkpoint_id: str
    run_id: str
    step_id: str | None
    status: str
    path: str
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "checkpoint_id", str(self.checkpoint_id))
        object.__setattr__(self, "run_id", str(self.run_id))
        object.__setattr__(self, "step_id", str(self.step_id) if self.step_id is not None else None)
        object.__setattr__(self, "status", str(self.status))
        object.__setattr__(self, "path", str(self.path))
        object.__setattr__(self, "created_at", parse_datetime(self.created_at) or utc_now())
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "status": self.status,
            "path": self.path,
            "created_at": format_datetime(self.created_at),
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CheckpointReference":
        return cls(
            checkpoint_id=str(payload["checkpoint_id"]),
            run_id=str(payload["run_id"]),
            step_id=_optional_str(payload.get("step_id")),
            status=str(payload.get("status") or "created"),
            path=str(payload.get("path") or ""),
            created_at=parse_datetime(payload.get("created_at")) or utc_now(),
            metadata=dict(payload.get("metadata") or {}),
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
