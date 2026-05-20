from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from framework.shared.json import to_jsonable


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class WorkflowCheckpoint:
    checkpoint_id: str
    run_id: str
    workflow_id: str
    workflow_version: str
    current_step_ids: list[str]
    data_buffer_snapshot: dict[str, Any]
    step_results: dict[str, Any] = field(default_factory=dict)
    path: list[str] = field(default_factory=list)
    event_offset: int = 0
    created_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "current_step_ids": list(self.current_step_ids),
            "data_buffer_snapshot": to_jsonable(self.data_buffer_snapshot),
            "step_results": to_jsonable(self.step_results),
            "path": list(self.path),
            "event_offset": self.event_offset,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> WorkflowCheckpoint:
        return cls(
            checkpoint_id=str(payload["checkpoint_id"]),
            run_id=str(payload["run_id"]),
            workflow_id=str(payload["workflow_id"]),
            workflow_version=str(payload["workflow_version"]),
            current_step_ids=[str(step_id) for step_id in payload.get("current_step_ids", [])],
            data_buffer_snapshot=dict(payload.get("data_buffer_snapshot") or {}),
            step_results=dict(payload.get("step_results") or {}),
            path=[str(step_id) for step_id in payload.get("path", [])],
            event_offset=int(payload.get("event_offset", 0)),
            created_at=_parse_datetime(str(payload["created_at"])),
            metadata=dict(payload.get("metadata") or {}),
        )


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


