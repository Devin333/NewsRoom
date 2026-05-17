from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.framework.workflow.operations import (
    LocalWorkflowRunOperationService,
    OperationActor,
    OperationResult,
    WorkflowRunOperationService,
)


@dataclass(frozen=True)
class RunOperationApplicationResult:
    operation: OperationResult

    def to_dict(self) -> dict[str, Any]:
        return self.operation.to_dict()


class RunOperationApplicationService:
    def __init__(
        self,
        artifact_root: str | Path = ".newsroom/runs",
        *,
        operation_service: WorkflowRunOperationService | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.operation_service = operation_service or LocalWorkflowRunOperationService(
            artifact_root=self.artifact_root
        )

    def cancel_run(
        self,
        run_id: str,
        *,
        reason: str | None = None,
        actor_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunOperationApplicationResult:
        self._ensure_run_exists(run_id)
        return RunOperationApplicationResult(
            self.operation_service.cancel_run(
                run_id,
                reason or "cancel requested through API",
                actor=_actor(actor_id, metadata),
            )
        )

    def rerun_from_step(
        self,
        run_id: str,
        *,
        step_id: str,
        actor_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunOperationApplicationResult:
        self._ensure_run_exists(run_id)
        return RunOperationApplicationResult(
            self.operation_service.rerun_from_step(
                run_id,
                step_id,
                actor=_actor(actor_id, metadata),
            )
        )

    def resume_with_patch(
        self,
        run_id: str,
        *,
        patch: dict[str, Any],
        actor_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunOperationApplicationResult:
        self._ensure_run_exists(run_id)
        return RunOperationApplicationResult(
            self.operation_service.resume_with_patch(
                run_id,
                patch,
                actor=_actor(actor_id, metadata),
            )
        )

    def skip_step(
        self,
        run_id: str,
        *,
        step_id: str,
        reason: str | None = None,
        actor_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunOperationApplicationResult:
        self._ensure_run_exists(run_id)
        return RunOperationApplicationResult(
            self.operation_service.skip_step(
                run_id,
                step_id,
                reason or "skip requested through API",
                actor=_actor(actor_id, metadata),
            )
        )

    def mark_blocked_resolved(
        self,
        run_id: str,
        *,
        reason: str | None = None,
        resolved_by: str | None = None,
        resolution_type: str = "manual",
        actor_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunOperationApplicationResult:
        self._ensure_run_exists(run_id)
        actual_actor_id = actor_id or resolved_by
        resolution = {
            "reason": reason or "blocked run resolved through API",
            "resolved_by": resolved_by or actual_actor_id or "api",
            "resolution_type": resolution_type,
            "metadata": dict(metadata or {}),
        }
        return RunOperationApplicationResult(
            self.operation_service.mark_blocked_resolved(
                run_id,
                resolution,
                actor=_actor(actual_actor_id, metadata),
            )
        )

    def _ensure_run_exists(self, run_id: str) -> None:
        if not (self.artifact_root / run_id / "manifest.json").exists():
            raise FileNotFoundError(f"run not found: {run_id}")


def _actor(actor_id: str | None, metadata: dict[str, Any] | None) -> OperationActor | None:
    if not actor_id:
        return None
    return OperationActor(actor_id=actor_id, metadata=dict(metadata or {}))
