from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from core.framework.specs import StepStatus, WorkflowStatus


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


@dataclass(frozen=True)
class WorkflowError:
    error_type: str
    message: str
    step_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "message": self.message,
            "step_id": self.step_id,
            "details": _json_safe(self.details),
        }


@dataclass(frozen=True)
class StepOutcome:
    status: StepStatus
    outputs: dict[str, Any] = field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None
    error_details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "outputs": _json_safe(self.outputs),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "error_details": _json_safe(self.error_details),
        }


@dataclass(frozen=True)
class WorkflowResult:
    run_id: str
    workflow_id: str
    workflow_version: str
    status: WorkflowStatus
    output: dict[str, Any] = field(default_factory=dict)
    error: WorkflowError | None = None
    path: list[str] = field(default_factory=list)
    step_results: dict[str, StepOutcome] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    artifact_dir: str | None = None
    manifest_path: str | None = None
    events_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "status": self.status.value,
            "output": _json_safe(self.output),
            "error": self.error.to_dict() if self.error else None,
            "path": list(self.path),
            "step_results": {
                step_id: outcome.to_dict() for step_id, outcome in self.step_results.items()
            },
            "manifest": _json_safe(self.manifest),
            "artifact_dir": self.artifact_dir,
            "manifest_path": self.manifest_path,
            "events_path": self.events_path,
        }
