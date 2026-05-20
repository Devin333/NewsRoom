from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from framework.shared import RuntimeStatus
from framework.shared.time import format_datetime, parse_datetime, utc_now


@dataclass(frozen=True)
class StepRuntimeState:
    step_id: str
    status: RuntimeStatus = RuntimeStatus.PENDING
    attempt: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.step_id:
            raise ValueError("step_id is required")
        object.__setattr__(self, "status", RuntimeStatus.from_value(self.status))

    def start(self) -> StepRuntimeState:
        return replace(
            self,
            status=RuntimeStatus.RUNNING,
            attempt=self.attempt + 1,
            started_at=utc_now(),
            finished_at=None,
            error=None,
        )

    def succeed(self) -> StepRuntimeState:
        return replace(self, status=RuntimeStatus.SUCCEEDED, finished_at=utc_now(), error=None)

    def fail(self, error: str) -> StepRuntimeState:
        return replace(self, status=RuntimeStatus.FAILED, finished_at=utc_now(), error=error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "status": self.status.value,
            "attempt": self.attempt,
            "started_at": format_datetime(self.started_at) if self.started_at else None,
            "finished_at": format_datetime(self.finished_at) if self.finished_at else None,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StepRuntimeState:
        return cls(
            step_id=str(payload["step_id"]),
            status=RuntimeStatus.from_value(str(payload.get("status") or RuntimeStatus.PENDING.value)),
            attempt=int(payload.get("attempt") or 0),
            started_at=_optional_datetime(payload.get("started_at")),
            finished_at=_optional_datetime(payload.get("finished_at")),
            error=_optional_str(payload.get("error")),
        )


@dataclass(frozen=True)
class WorkflowRuntimeState:
    run_id: str
    workflow_id: str
    status: RuntimeStatus = RuntimeStatus.PENDING
    current_step_ids: list[str] = field(default_factory=list)
    completed_step_ids: list[str] = field(default_factory=list)
    failed_step_ids: list[str] = field(default_factory=list)
    step_states: dict[str, StepRuntimeState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.workflow_id:
            raise ValueError("workflow_id is required")
        object.__setattr__(self, "status", RuntimeStatus.from_value(self.status))

    def mark_running(self) -> WorkflowRuntimeState:
        return replace(self, status=RuntimeStatus.RUNNING)

    def mark_step_started(self, step_id: str) -> WorkflowRuntimeState:
        step_state = self.step_states.get(step_id, StepRuntimeState(step_id=step_id)).start()
        current_step_ids = [*self.current_step_ids]
        if step_id not in current_step_ids:
            current_step_ids.append(step_id)
        return replace(
            self,
            status=RuntimeStatus.RUNNING,
            current_step_ids=current_step_ids,
            step_states={**self.step_states, step_id: step_state},
        )

    def mark_step_completed(self, step_id: str) -> WorkflowRuntimeState:
        step_state = self.step_states.get(step_id, StepRuntimeState(step_id=step_id)).succeed()
        return replace(
            self,
            current_step_ids=[item for item in self.current_step_ids if item != step_id],
            completed_step_ids=_append_once(self.completed_step_ids, step_id),
            step_states={**self.step_states, step_id: step_state},
        )

    def mark_step_failed(self, step_id: str, error: str) -> WorkflowRuntimeState:
        step_state = self.step_states.get(step_id, StepRuntimeState(step_id=step_id)).fail(error)
        return replace(
            self,
            status=RuntimeStatus.FAILED,
            current_step_ids=[item for item in self.current_step_ids if item != step_id],
            failed_step_ids=_append_once(self.failed_step_ids, step_id),
            step_states={**self.step_states, step_id: step_state},
        )

    def is_terminal(self) -> bool:
        return self.status.is_terminal()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "current_step_ids": list(self.current_step_ids),
            "completed_step_ids": list(self.completed_step_ids),
            "failed_step_ids": list(self.failed_step_ids),
            "step_states": {
                step_id: step_state.to_dict()
                for step_id, step_state in self.step_states.items()
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> WorkflowRuntimeState:
        return cls(
            run_id=str(payload["run_id"]),
            workflow_id=str(payload["workflow_id"]),
            status=RuntimeStatus.from_value(str(payload.get("status") or RuntimeStatus.PENDING.value)),
            current_step_ids=[str(item) for item in payload.get("current_step_ids", [])],
            completed_step_ids=[str(item) for item in payload.get("completed_step_ids", [])],
            failed_step_ids=[str(item) for item in payload.get("failed_step_ids", [])],
            step_states={
                str(step_id): StepRuntimeState.from_dict(step_payload)
                for step_id, step_payload in (payload.get("step_states") or {}).items()
            },
        )


def _append_once(values: list[str], value: str) -> list[str]:
    if value in values:
        return list(values)
    return [*values, value]


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    return parse_datetime(str(value))


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


