from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.framework.serialization import to_json_safe
from core.framework.specs import WorkflowStatus
from core.framework.workflow.result import WorkflowResult


@dataclass(frozen=True)
class RunResult:
    run_id: str
    workflow_id: str
    workflow_version: str
    status: WorkflowStatus
    output: dict[str, Any] = field(default_factory=dict)
    artifact_dir: str | None = None
    manifest_path: str | None = None
    events_path: str | None = None
    error: dict[str, Any] | None = None
    manifest: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_workflow_result(cls, result: WorkflowResult) -> RunResult:
        return cls(
            run_id=result.run_id,
            workflow_id=result.workflow_id,
            workflow_version=result.workflow_version,
            status=result.status,
            output=result.output,
            artifact_dir=result.artifact_dir,
            manifest_path=result.manifest_path,
            events_path=result.events_path,
            error=result.error.to_dict() if result.error else None,
            manifest=result.manifest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "status": self.status.value,
            "output": to_json_safe(self.output),
            "artifact_dir": self.artifact_dir,
            "manifest_path": self.manifest_path,
            "events_path": self.events_path,
            "error": to_json_safe(self.error),
            "manifest": to_json_safe(self.manifest),
        }
