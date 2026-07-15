from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from framework.artifacts.paths import (
    resolve_artifact_descendant,
    validate_artifact_path_segment,
)
from framework.workflow.operations import (
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
        event_env: Mapping[str, str] | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self._operation_service = operation_service
        self._event_env = None if event_env is None else dict(event_env)

    def cancel_run(
        self,
        run_id: str,
        *,
        reason: str | None = None,
        actor_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunOperationApplicationResult:
        self._ensure_run_exists(run_id)
        operation_service = self._get_operation_service()
        return RunOperationApplicationResult(
            operation_service.cancel_run(
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
        operation_service = self._get_operation_service()
        return RunOperationApplicationResult(
            operation_service.rerun_from_step(
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
        operation_service = self._get_operation_service()
        return RunOperationApplicationResult(
            operation_service.resume_with_patch(
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
        operation_service = self._get_operation_service()
        return RunOperationApplicationResult(
            operation_service.skip_step(
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
        operation_service = self._get_operation_service()
        actual_actor_id = actor_id or resolved_by
        resolution = {
            "reason": reason or "blocked run resolved through API",
            "resolved_by": resolved_by or actual_actor_id or "api",
            "resolution_type": resolution_type,
            "metadata": dict(metadata or {}),
        }
        return RunOperationApplicationResult(
            operation_service.mark_blocked_resolved(
                run_id,
                resolution,
                actor=_actor(actual_actor_id, metadata),
            )
        )

    def _ensure_run_exists(self, run_id: str) -> None:
        safe_run_id = validate_artifact_path_segment(run_id, field="run_id")
        run_dir = resolve_artifact_descendant(
            self.artifact_root,
            safe_run_id,
            field="run_id",
        )
        manifest_path = resolve_artifact_descendant(
            run_dir,
            "manifest.json",
            field="run manifest path",
        )
        if not manifest_path.exists():
            raise FileNotFoundError(f"run not found: {run_id}")

    def _get_operation_service(self) -> WorkflowRunOperationService:
        operation_service = self._operation_service
        if operation_service is not None:
            return operation_service

        from infrastructure.storage.events.factory import (
            durable_event_storage_from_env,
        )

        event_storage = durable_event_storage_from_env(
            artifact_root=self.artifact_root,
            env=self._event_env,
        )
        operation_service = LocalWorkflowRunOperationService(
            artifact_root=self.artifact_root,
            event_runtime=event_storage.event_runtime,
            event_reader=event_storage.event_store,
            event_schema_catalog=event_storage.schema_catalog,
        )
        self._operation_service = operation_service
        return operation_service


def _actor(actor_id: str | None, metadata: dict[str, Any] | None) -> OperationActor | None:
    if not actor_id:
        return None
    return OperationActor(actor_id=actor_id, metadata=dict(metadata or {}))
