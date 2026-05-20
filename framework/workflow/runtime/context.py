from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from framework.shared.time import ensure_utc, format_datetime, parse_datetime, utc_now


@dataclass(frozen=True)
class WorkflowRunContext:
    run_id: str
    workflow_id: str
    profile: str
    started_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.workflow_id:
            raise ValueError("workflow_id is required")
        object.__setattr__(self, "started_at", ensure_utc(self.started_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "profile": self.profile,
            "started_at": format_datetime(self.started_at),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> WorkflowRunContext:
        return cls(
            run_id=str(payload["run_id"]),
            workflow_id=str(payload["workflow_id"]),
            profile=str(payload.get("profile") or "default"),
            started_at=parse_datetime(str(payload["started_at"])),
            metadata=dict(payload.get("metadata") or {}),
        )

    def child_context(self, *, step_id: str) -> StepRunContext:
        return StepRunContext(
            run_id=self.run_id,
            workflow_id=self.workflow_id,
            step_id=step_id,
            attempt=1,
            metadata=dict(self.metadata),
        )


@dataclass(frozen=True)
class StepRunContext:
    run_id: str
    workflow_id: str
    step_id: str
    attempt: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.workflow_id:
            raise ValueError("workflow_id is required")
        if not self.step_id:
            raise ValueError("step_id is required")
        if self.attempt < 1:
            raise ValueError("attempt must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "attempt": self.attempt,
            "metadata": dict(self.metadata),
        }


