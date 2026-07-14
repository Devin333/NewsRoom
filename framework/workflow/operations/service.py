"""Run operation models and artifact-backed operation service.

This module owns operator actions against existing workflow run artifacts.
It does not own normal workflow execution; the executor only observes markers
written here, such as cancel.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from dataclasses import replace
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from enum import Enum
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from framework.artifacts import (
    resolve_artifact_descendant,
    validate_artifact_path_segment,
    validate_relative_artifact_path,
)
from framework.shared.json import to_jsonable as to_json_safe
from framework.specs import StepStatus, WorkflowSpec
from framework.workflow.buffer import DataBuffer, step_scope_from_spec
from framework.workflow.checkpoint.envelope import envelope_from_checkpoint
from framework.workflow.checkpoint.resume import (
    ResumeMode,
    WorkflowResumePlan,
    WorkflowResumePlanner,
    WorkflowResumeRequest,
)
from framework.workflow.runtime.manifest import manifest_hash, normalize_legacy_run_manifest, stable_json_dumps
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.routing import RoutingEngine
from framework.workflow.checkpoint.model import WorkflowCheckpoint


# =============================================================================
# Constants
# =============================================================================

TERMINAL_STATUSES = {
    "succeeded",
    "failed",
    "blocked",
    "cancelled",
    "budget_exceeded",
}

MUTABLE_STATUSES = {
    "running",
    "paused",
    "waiting_for_human",
}

_CANCELLABLE_STATUSES = {"running", "paused", "waiting_for_human", "blocked"}
_RESUME_WITH_PATCH_STATUSES = {"paused", "waiting_for_human", "budget_exceeded"}
_RERUN_FROM_STEP_STATUSES = {
    "paused",
    "waiting_for_human",
    "succeeded",
    "failed",
    "blocked",
    "cancelled",
    "budget_exceeded",
}
_SKIP_STEP_STATUSES = {"paused", "waiting_for_human", "failed", "blocked"}
_MARK_BLOCKED_RESOLVED_STATUSES = {"blocked"}


# =============================================================================
# Data Models
# =============================================================================


class WorkflowOperationType(str, Enum):
    CANCEL_RUN = "cancel_run"
    RERUN_FROM_STEP = "rerun_from_step"
    RESUME_WITH_PATCH = "resume_with_patch"
    SKIP_STEP = "skip_step"
    MARK_BLOCKED_RESOLVED = "mark_blocked_resolved"


class WorkflowOperationStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    APPLIED = "applied"
    FAILED = "failed"


@dataclass(frozen=True)
class OperationActor:
    actor_id: str
    actor_type: str = "user"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "metadata": to_json_safe(self.metadata),
        }


@dataclass(frozen=True)
class OperationResult:
    operation_id: str
    operation_type: WorkflowOperationType
    status: WorkflowOperationStatus
    run_id: str
    message: str
    new_run_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "operation_type",
            WorkflowOperationType(self.operation_type),
        )
        object.__setattr__(self, "status", WorkflowOperationStatus(self.status))

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type.value,
            "status": self.status.value,
            "run_id": self.run_id,
            "message": self.message,
            "new_run_id": self.new_run_id,
            "details": to_json_safe(self.details),
        }


@dataclass(frozen=True)
class WorkflowOperationRecord:
    operation_id: str
    operation_type: str
    status: str
    run_id: str
    actor_id: str | None
    reason: str | None
    created_at: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "status": self.status,
            "run_id": self.run_id,
            "actor_id": self.actor_id,
            "reason": self.reason,
            "created_at": self.created_at,
            "details": to_json_safe(self.details),
        }


@dataclass(frozen=True)
class RunOperationGuardResult:
    allowed: bool
    reason: str | None = None
    status: str | None = None


# =============================================================================
# Protocols
# =============================================================================


class WorkflowRunOperationService(Protocol):
    def cancel_run(
        self,
        run_id: str,
        reason: str,
        *,
        actor: OperationActor | None = None,
    ) -> OperationResult:
        ...

    def rerun_from_step(
        self,
        run_id: str,
        step_id: str,
        *,
        actor: OperationActor | None = None,
    ) -> OperationResult:
        ...

    def resume_with_patch(
        self,
        run_id: str,
        patch: dict[str, Any],
        *,
        actor: OperationActor | None = None,
    ) -> OperationResult:
        ...

    def skip_step(
        self,
        run_id: str,
        step_id: str,
        reason: str,
        *,
        actor: OperationActor | None = None,
    ) -> OperationResult:
        ...

    def mark_blocked_resolved(
        self,
        run_id: str,
        resolution: dict[str, Any],
        *,
        actor: OperationActor | None = None,
    ) -> OperationResult:
        ...


class CheckpointReader(Protocol):
    def get_latest_checkpoint(self, run_id: str) -> WorkflowCheckpoint | None:
        ...


class ResumeExecutor(Protocol):
    def execute_resume_plan(
        self,
        workflow: WorkflowSpec,
        plan: Any,
        *,
        profile: str,
    ) -> Any:
        ...


# =============================================================================
# Core Implementations
# =============================================================================


class RunOperationGuard:
    def can_cancel(self, status: str) -> RunOperationGuardResult:
        return _guard_status(status, _CANCELLABLE_STATUSES, "run cannot be cancelled")

    def can_resume_with_patch(self, status: str) -> RunOperationGuardResult:
        return _guard_status(
            status,
            _RESUME_WITH_PATCH_STATUSES,
            "run cannot resume with patch",
        )

    def can_rerun_from_step(self, status: str) -> RunOperationGuardResult:
        return _guard_status(
            status,
            _RERUN_FROM_STEP_STATUSES,
            "run cannot rerun from step",
        )

    def can_skip_step(self, status: str) -> RunOperationGuardResult:
        return _guard_status(status, _SKIP_STEP_STATUSES, "run cannot skip step")

    def can_mark_blocked_resolved(self, status: str) -> RunOperationGuardResult:
        return _guard_status(
            status,
            _MARK_BLOCKED_RESOLVED_STATUSES,
            "run is not blocked",
        )


class LocalWorkflowRunOperationService:
    def __init__(
        self,
        *,
        artifact_root: str | Path,
        workflow: WorkflowSpec | None = None,
        runner: ResumeExecutor | None = None,
        checkpoint_store: CheckpointReader | None = None,
        guard: RunOperationGuard | None = None,
        routing_engine: RoutingEngine | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.workflow = workflow
        self.runner = runner
        self.checkpoint_store = checkpoint_store
        self.guard = guard or RunOperationGuard()
        self.routing_engine = routing_engine or RoutingEngine()

    def cancel_run(
        self,
        run_id: str,
        reason: str,
        *,
        actor: OperationActor | None = None,
    ) -> OperationResult:
        operation_id = new_operation_id()
        operation_type = WorkflowOperationType.CANCEL_RUN
        requested_at = _utc_now()
        try:
            manifest = load_run_manifest(self.artifact_root, run_id)
        except FileNotFoundError as exc:
            return OperationResult(
                operation_id=operation_id,
                operation_type=operation_type,
                status=WorkflowOperationStatus.FAILED,
                run_id=run_id,
                message=str(exc),
            )

        details = {"previous_status": str(manifest.get("status") or "")}
        append_operation_event(
            self._run_dir(run_id),
            operation_event(
                "run_operation_requested",
                operation_id=operation_id,
                operation_type=operation_type,
                run_id=run_id,
                actor=actor,
                reason=reason,
                details=details,
                created_at=requested_at,
            ),
        )
        guard = self.guard.can_cancel(_manifest_status(manifest))
        if not guard.allowed:
            return self._reject(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=reason,
                actor=actor,
                message=guard.reason or "cancel_run rejected",
                details={**details, "status": guard.status},
                created_at=requested_at,
            )

        cancel_payload = {
            "run_id": run_id,
            "operation_id": operation_id,
            "reason": reason,
            "actor_id": actor.actor_id if actor else None,
            "created_at": requested_at,
        }
        self._write_json(run_id, "cancel.json", cancel_payload)
        manifest["status"] = "cancelled"
        manifest["cancelled_at"] = requested_at
        manifest["cancel_reason"] = reason
        manifest["cancel_operation_id"] = operation_id
        result = OperationResult(
            operation_id=operation_id,
            operation_type=operation_type,
            status=WorkflowOperationStatus.APPLIED,
            run_id=run_id,
            message="run cancelled",
            details={**details, "cancel_marker": "cancel.json"},
        )
        self._record_result(
            manifest=manifest,
            result=result,
            actor=actor,
            reason=reason,
            created_at=requested_at,
        )
        append_operation_event(
            self._run_dir(run_id),
            operation_event(
                "run_operation_applied",
                operation_id=operation_id,
                operation_type=operation_type,
                run_id=run_id,
                actor=actor,
                reason=reason,
                details=result.details,
                created_at=requested_at,
            ),
        )
        save_run_manifest(self.artifact_root, run_id, manifest)
        return result

    def rerun_from_step(
        self,
        run_id: str,
        step_id: str,
        *,
        actor: OperationActor | None = None,
    ) -> OperationResult:
        operation_id = new_operation_id()
        operation_type = WorkflowOperationType.RERUN_FROM_STEP
        requested_at = _utc_now()
        try:
            manifest = load_run_manifest(self.artifact_root, run_id)
        except FileNotFoundError as exc:
            return OperationResult(
                operation_id=operation_id,
                operation_type=operation_type,
                status=WorkflowOperationStatus.FAILED,
                run_id=run_id,
                message=str(exc),
            )
        details = {"target_step_id": step_id, "previous_status": _manifest_status(manifest)}
        append_operation_event(
            self._run_dir(run_id),
            operation_event(
                "run_operation_requested",
                operation_id=operation_id,
                operation_type=operation_type,
                run_id=run_id,
                actor=actor,
                reason=None,
                details=details,
                created_at=requested_at,
            ),
        )
        guard = self.guard.can_rerun_from_step(_manifest_status(manifest))
        if not guard.allowed:
            return self._reject(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=None,
                actor=actor,
                message=guard.reason or "rerun_from_step rejected",
                details={**details, "status": guard.status},
                created_at=requested_at,
            )
        workflow = self._workflow_for_manifest(manifest)
        if workflow is None:
            return self._fail(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=None,
                actor=actor,
                message="workflow is required for rerun_from_step",
                details=details,
                created_at=requested_at,
            )
        try:
            workflow.step_by_id(step_id)
        except Exception as exc:
            return self._reject(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=None,
                actor=actor,
                message=str(exc),
                details=details,
                created_at=requested_at,
            )
        checkpoint = self._checkpoint_for_manifest(manifest)
        if checkpoint is None:
            return self._fail(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=None,
                actor=actor,
                message=f"checkpoint not found for run_id: {run_id}",
                details=details,
                created_at=requested_at,
            )

        new_run_id = f"{run_id}-rerun-{operation_id}"
        try:
            plan = WorkflowResumePlanner().plan(
                workflow,
                WorkflowResumeRequest(
                    mode=ResumeMode.FROM_STEP,
                    checkpoint=envelope_from_checkpoint(checkpoint),
                    run_id=new_run_id,
                    target_step_id=step_id,
                    metadata={
                        "_public_resume_metadata": {
                            "operation_id": operation_id,
                            "operation_type": operation_type.value,
                            "original_run_id": run_id,
                            "target_step_id": step_id,
                            "actor_id": actor.actor_id if actor else None,
                        },
                    },
                ),
            )
            plan.resume_metadata.update(
                {
                    "operation_id": operation_id,
                    "operation_type": operation_type.value,
                    "original_run_id": run_id,
                    "rerun_from_run_id": run_id,
                    "rerun_from_step_id": step_id,
                    "target_step_id": step_id,
                    "actor_id": actor.actor_id if actor else None,
                }
            )
            self._execute_resume_plan(
                workflow=workflow,
                plan=plan,
                profile=str(manifest.get("profile") or "default"),
            )
        except ValueError as exc:
            return self._reject(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=None,
                actor=actor,
                message=str(exc),
                details=details,
                created_at=requested_at,
            )
        except Exception as exc:
            return self._fail(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=None,
                actor=actor,
                message=str(exc),
                details={**details, "exception_type": type(exc).__name__},
                created_at=requested_at,
            )

        result = OperationResult(
            operation_id=operation_id,
            operation_type=operation_type,
            status=WorkflowOperationStatus.APPLIED,
            run_id=run_id,
            message="run rerun from step",
            new_run_id=new_run_id,
            details={**details, "new_run_id": new_run_id},
        )
        self._record_result(
            manifest=manifest,
            result=result,
            actor=actor,
            reason=None,
            created_at=requested_at,
        )
        append_operation_event(
            self._run_dir(run_id),
            operation_event(
                "run_operation_applied",
                operation_id=operation_id,
                operation_type=operation_type,
                run_id=run_id,
                actor=actor,
                reason=None,
                details=result.details,
                created_at=requested_at,
            ),
        )
        save_run_manifest(self.artifact_root, run_id, manifest)
        return result

    def resume_with_patch(
        self,
        run_id: str,
        patch: dict[str, Any],
        *,
        actor: OperationActor | None = None,
    ) -> OperationResult:
        operation_id = new_operation_id()
        operation_type = WorkflowOperationType.RESUME_WITH_PATCH
        requested_at = _utc_now()
        try:
            manifest = load_run_manifest(self.artifact_root, run_id)
        except FileNotFoundError as exc:
            return OperationResult(
                operation_id=operation_id,
                operation_type=operation_type,
                status=WorkflowOperationStatus.FAILED,
                run_id=run_id,
                message=str(exc),
            )

        patch_diff = _patch_diff(run_id=run_id, patch=patch, artifact_root=self.artifact_root)
        details = {
            "patch_keys": sorted(str(key) for key in patch),
            "patch_diff": patch_diff,
        }
        append_operation_event(
            self._run_dir(run_id),
            operation_event(
                "run_operation_requested",
                operation_id=operation_id,
                operation_type=operation_type,
                run_id=run_id,
                actor=actor,
                reason=None,
                details=details,
                created_at=requested_at,
            ),
        )
        guard = self.guard.can_resume_with_patch(_manifest_status(manifest))
        if not guard.allowed:
            return self._reject(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=None,
                actor=actor,
                message=guard.reason or "resume_with_patch rejected",
                details={**details, "status": guard.status},
                created_at=requested_at,
            )
        if self.workflow is None or self.runner is None or self.checkpoint_store is None:
            return self._fail(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=None,
                actor=actor,
                message="workflow, runner, and checkpoint_store are required",
                details=details,
                created_at=requested_at,
            )

        checkpoint = self.checkpoint_store.get_latest_checkpoint(run_id)
        if checkpoint is None:
            return self._fail(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=None,
                actor=actor,
                message=f"checkpoint not found for run_id: {run_id}",
                details=details,
                created_at=requested_at,
            )

        new_run_id = f"{run_id}-resume-{operation_id}"
        try:
            plan = WorkflowResumePlanner().plan(
                self.workflow,
                WorkflowResumeRequest(
                    mode=ResumeMode.WITH_PATCH,
                    checkpoint=envelope_from_checkpoint(checkpoint),
                    run_id=new_run_id,
                    patch=dict(patch),
                    strict=True,
                    metadata={
                        "_public_resume_metadata": {
                            "operation_id": operation_id,
                            "operation_type": operation_type.value,
                            "patch_keys": details["patch_keys"],
                            "patch_diff": patch_diff,
                            "actor_id": actor.actor_id if actor else None,
                        },
                    },
                ),
            )
            plan.resume_metadata.update(
                {
                    "operation_id": operation_id,
                    "operation_type": operation_type.value,
                    "resume_patch_keys": details["patch_keys"],
                    "patch_keys": details["patch_keys"],
                    "patch_diff": patch_diff,
                    "actor_id": actor.actor_id if actor else None,
                }
            )
            self.runner.execute_resume_plan(
                self.workflow,
                plan,
                profile=str(manifest.get("profile") or "default"),
            )
        except Exception as exc:
            return self._fail(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=None,
                actor=actor,
                message=str(exc),
                details={**details, "exception_type": type(exc).__name__},
                created_at=requested_at,
            )

        result = OperationResult(
            operation_id=operation_id,
            operation_type=operation_type,
            status=WorkflowOperationStatus.APPLIED,
            run_id=run_id,
            message="run resumed with patch",
            new_run_id=new_run_id,
            details=details,
        )
        self._record_result(
            manifest=manifest,
            result=result,
            actor=actor,
            reason=None,
            created_at=requested_at,
        )
        append_operation_event(
            self._run_dir(run_id),
            operation_event(
                "run_operation_applied",
                operation_id=operation_id,
                operation_type=operation_type,
                run_id=run_id,
                actor=actor,
                reason=None,
                details={**details, "new_run_id": new_run_id},
                created_at=requested_at,
            ),
        )
        save_run_manifest(self.artifact_root, run_id, manifest)
        return result

    def skip_step(
        self,
        run_id: str,
        step_id: str,
        reason: str,
        *,
        actor: OperationActor | None = None,
    ) -> OperationResult:
        operation_id = new_operation_id()
        operation_type = WorkflowOperationType.SKIP_STEP
        requested_at = _utc_now()
        try:
            manifest = load_run_manifest(self.artifact_root, run_id)
        except FileNotFoundError as exc:
            return OperationResult(
                operation_id=operation_id,
                operation_type=operation_type,
                status=WorkflowOperationStatus.FAILED,
                run_id=run_id,
                message=str(exc),
            )
        details = {"step_id": step_id, "reason": reason, "previous_status": _manifest_status(manifest)}
        append_operation_event(
            self._run_dir(run_id),
            operation_event(
                "run_operation_requested",
                operation_id=operation_id,
                operation_type=operation_type,
                run_id=run_id,
                actor=actor,
                reason=reason,
                details=details,
                created_at=requested_at,
            ),
        )
        guard = self.guard.can_skip_step(_manifest_status(manifest))
        if not guard.allowed:
            return self._reject(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=reason,
                actor=actor,
                message=guard.reason or "skip_step rejected",
                details={**details, "status": guard.status},
                created_at=requested_at,
            )
        workflow = self._workflow_for_manifest(manifest)
        if workflow is None:
            return self._fail(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=reason,
                actor=actor,
                message="workflow is required for skip_step",
                details=details,
                created_at=requested_at,
            )
        try:
            step = workflow.step_by_id(step_id)
        except Exception as exc:
            return self._reject(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=reason,
                actor=actor,
                message=str(exc),
                details=details,
                created_at=requested_at,
            )
        if step.metadata.get("allow_manual_skip") is not True:
            return self._reject(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=reason,
                actor=actor,
                message=f"step does not allow manual skip: {step_id}",
                details=details,
                created_at=requested_at,
            )
        checkpoint = self._checkpoint_for_manifest(manifest)
        if checkpoint is None:
            return self._fail(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=reason,
                actor=actor,
                message=f"checkpoint not found for run_id: {run_id}",
                details=details,
                created_at=requested_at,
            )
        skip_output = dict(step.metadata.get("skip_output") or {})
        output_error = _skip_output_error(step, skip_output)
        if output_error is not None:
            return self._reject(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=reason,
                actor=actor,
                message=output_error,
                details={**details, "skip_output": skip_output},
                created_at=requested_at,
            )
        skipped = StepOutcome(
            status=StepStatus.SKIPPED,
            outputs=skip_output,
            metrics={"operation_id": operation_id, "manual_skip": True},
            next_hint=str(step.metadata.get("skip_next_hint") or "skipped"),
        )
        buffer_values = dict(checkpoint.data_buffer_snapshot)
        buffer_values.update(skip_output)
        buffer = DataBuffer(buffer_values)
        buffer.register_scopes(step_scope for step_scope in _step_scopes(workflow))
        next_step_ids = self.routing_engine.next_steps(
            workflow,
            step,
            skipped,
            buffer=buffer,
        )
        new_run_id = f"{run_id}-skip-{operation_id}"
        try:
            base_plan = WorkflowResumePlanner().plan(
                workflow,
                WorkflowResumeRequest(
                    mode=ResumeMode.FROM_STEP,
                    checkpoint=envelope_from_checkpoint(checkpoint),
                    run_id=new_run_id,
                    target_step_id=step_id,
                    metadata={
                        "_public_resume_metadata": {
                            "operation_id": operation_id,
                            "operation_type": operation_type.value,
                            "skip_step_id": step_id,
                            "actor_id": actor.actor_id if actor else None,
                        },
                    },
                ),
            )
            step_results = dict(base_plan.initial_step_results)
            step_results[step_id] = skipped
            plan = replace(
                base_plan,
                initial_buffer_values=buffer_values,
                current_step_ids=list(next_step_ids),
                initial_path=[*base_plan.initial_path, step_id],
                initial_step_results=step_results,
            )
            plan.resume_metadata.update(
                {
                    "operation_id": operation_id,
                    "operation_type": operation_type.value,
                    "skip_step_id": step_id,
                    "skip_reason": reason,
                    "skip_next_step_ids": list(next_step_ids),
                    "actor_id": actor.actor_id if actor else None,
                }
            )
            self._execute_resume_plan(
                workflow=workflow,
                plan=plan,
                profile=str(manifest.get("profile") or "default"),
            )
        except Exception as exc:
            return self._fail(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=reason,
                actor=actor,
                message=str(exc),
                details={**details, "exception_type": type(exc).__name__},
                created_at=requested_at,
            )
        result = OperationResult(
            operation_id=operation_id,
            operation_type=operation_type,
            status=WorkflowOperationStatus.APPLIED,
            run_id=run_id,
            message="step skipped and workflow resumed",
            new_run_id=new_run_id,
            details={
                **details,
                "skip_output": skip_output,
                "next_step_ids": list(next_step_ids),
                "new_run_id": new_run_id,
            },
        )
        self._record_result(
            manifest=manifest,
            result=result,
            actor=actor,
            reason=reason,
            created_at=requested_at,
        )
        append_operation_event(
            self._run_dir(run_id),
            operation_event(
                "run_operation_applied",
                operation_id=operation_id,
                operation_type=operation_type,
                run_id=run_id,
                actor=actor,
                reason=reason,
                details=result.details,
                created_at=requested_at,
            ),
        )
        append_operation_event(
            self._run_dir(run_id),
            operation_event(
                "step_skipped",
                operation_id=operation_id,
                operation_type=operation_type,
                run_id=run_id,
                actor=actor,
                reason=reason,
                details={"step_id": step_id, "new_run_id": new_run_id},
                created_at=requested_at,
            ),
        )
        save_run_manifest(self.artifact_root, run_id, manifest)
        return result

    def mark_blocked_resolved(
        self,
        run_id: str,
        resolution: dict[str, Any],
        *,
        actor: OperationActor | None = None,
    ) -> OperationResult:
        operation_id = new_operation_id()
        operation_type = WorkflowOperationType.MARK_BLOCKED_RESOLVED
        requested_at = _utc_now()
        try:
            manifest = load_run_manifest(self.artifact_root, run_id)
        except FileNotFoundError as exc:
            return OperationResult(
                operation_id=operation_id,
                operation_type=operation_type,
                status=WorkflowOperationStatus.FAILED,
                run_id=run_id,
                message=str(exc),
            )
        details = {"resolution": to_json_safe(resolution), "previous_status": _manifest_status(manifest)}
        append_operation_event(
            self._run_dir(run_id),
            operation_event(
                "run_operation_requested",
                operation_id=operation_id,
                operation_type=operation_type,
                run_id=run_id,
                actor=actor,
                reason=str(resolution.get("reason") or ""),
                details=details,
                created_at=requested_at,
            ),
        )
        guard = self.guard.can_mark_blocked_resolved(_manifest_status(manifest))
        if not guard.allowed:
            return self._reject(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=str(resolution.get("reason") or ""),
                actor=actor,
                message=guard.reason or "mark_blocked_resolved rejected",
                details={**details, "status": guard.status},
                created_at=requested_at,
            )
        resolution_error = _blocked_resolution_error(resolution)
        if resolution_error is not None:
            return self._reject(
                manifest=manifest,
                operation_id=operation_id,
                operation_type=operation_type,
                reason=str(resolution.get("reason") or ""),
                actor=actor,
                message=resolution_error,
                details=details,
                created_at=requested_at,
            )
        manifest["blocked_resolution"] = {
            "operation_id": operation_id,
            "reason": str(resolution["reason"]),
            "resolved_by": str(resolution["resolved_by"]),
            "resolution_type": str(resolution["resolution_type"]),
            "metadata": to_json_safe(resolution.get("metadata") or {}),
            "resolved_at": requested_at,
        }
        result = OperationResult(
            operation_id=operation_id,
            operation_type=operation_type,
            status=WorkflowOperationStatus.APPLIED,
            run_id=run_id,
            message="blocked run marked resolved",
            details=details,
        )
        self._record_result(
            manifest=manifest,
            result=result,
            actor=actor,
            reason=str(resolution["reason"]),
            created_at=requested_at,
        )
        append_operation_event(
            self._run_dir(run_id),
            operation_event(
                "run_operation_applied",
                operation_id=operation_id,
                operation_type=operation_type,
                run_id=run_id,
                actor=actor,
                reason=str(resolution["reason"]),
                details=result.details,
                created_at=requested_at,
            ),
        )
        save_run_manifest(self.artifact_root, run_id, manifest)
        return result

    def _reject(
        self,
        *,
        manifest: dict[str, Any],
        operation_id: str,
        operation_type: WorkflowOperationType,
        reason: str | None,
        actor: OperationActor | None,
        message: str,
        details: dict[str, Any],
        created_at: str,
    ) -> OperationResult:
        run_id = str(manifest["run_id"])
        result = OperationResult(
            operation_id=operation_id,
            operation_type=operation_type,
            status=WorkflowOperationStatus.REJECTED,
            run_id=run_id,
            message=message,
            details=details,
        )
        self._record_result(
            manifest=manifest,
            result=result,
            actor=actor,
            reason=reason,
            created_at=created_at,
        )
        append_operation_event(
            self._run_dir(run_id),
            operation_event(
                "run_operation_rejected",
                operation_id=operation_id,
                operation_type=operation_type,
                run_id=run_id,
                actor=actor,
                reason=reason,
                details=details,
                created_at=created_at,
            ),
        )
        save_run_manifest(self.artifact_root, run_id, manifest)
        return result

    def _fail(
        self,
        *,
        manifest: dict[str, Any],
        operation_id: str,
        operation_type: WorkflowOperationType,
        reason: str | None,
        actor: OperationActor | None,
        message: str,
        details: dict[str, Any],
        created_at: str,
    ) -> OperationResult:
        run_id = str(manifest["run_id"])
        result = OperationResult(
            operation_id=operation_id,
            operation_type=operation_type,
            status=WorkflowOperationStatus.FAILED,
            run_id=run_id,
            message=message,
            details=details,
        )
        self._record_result(
            manifest=manifest,
            result=result,
            actor=actor,
            reason=reason,
            created_at=created_at,
        )
        append_operation_event(
            self._run_dir(run_id),
            operation_event(
                "run_operation_failed",
                operation_id=operation_id,
                operation_type=operation_type,
                run_id=run_id,
                actor=actor,
                reason=reason,
                details=details,
                created_at=created_at,
            ),
        )
        save_run_manifest(self.artifact_root, run_id, manifest)
        return result

    def _record_result(
        self,
        *,
        manifest: dict[str, Any],
        result: OperationResult,
        actor: OperationActor | None,
        reason: str | None,
        created_at: str,
    ) -> None:
        record = WorkflowOperationRecord(
            operation_id=result.operation_id,
            operation_type=result.operation_type.value,
            status=result.status.value,
            run_id=result.run_id,
            actor_id=actor.actor_id if actor else None,
            reason=reason,
            created_at=created_at,
            details={**dict(result.details), "new_run_id": result.new_run_id},
        )
        append_operation_record(manifest, record)

    def _run_dir(self, run_id: str) -> Path:
        return _resolve_run_dir(self.artifact_root, run_id)

    def _write_json(self, run_id: str, relative_path: str, payload: dict[str, Any]) -> None:
        path = _resolve_run_artifact_path(self.artifact_root, run_id, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(stable_json_dumps(to_json_safe(payload), indent=2) + "\n", encoding="utf-8")

    def _workflow_for_manifest(self, manifest: dict[str, Any]) -> WorkflowSpec | None:
        if self.workflow is None:
            return load_workflow_spec_from_run(self.artifact_root, str(manifest["run_id"]))
        if (
            self.workflow.workflow_id != str(manifest.get("workflow_id"))
            or self.workflow.version != str(manifest.get("workflow_version"))
        ):
            return None
        return self.workflow

    def _checkpoint_for_manifest(self, manifest: dict[str, Any]) -> WorkflowCheckpoint | None:
        run_id = str(manifest["run_id"])
        if self.checkpoint_store is not None:
            checkpoint = self.checkpoint_store.get_latest_checkpoint(run_id)
            if checkpoint is not None:
                return checkpoint
        return checkpoint_from_run_artifacts(
            self.artifact_root,
            run_id=run_id,
            manifest=manifest,
        )

    def _execute_resume_plan(
        self,
        *,
        workflow: WorkflowSpec,
        plan: WorkflowResumePlan,
        profile: str,
    ) -> Any:
        if self.runner is None:
            raise ValueError("runner is required to execute operation resume plan")
        return self.runner.execute_resume_plan(workflow, plan, profile=profile)


# =============================================================================
# Helpers
# =============================================================================


def _resolve_run_dir(artifact_root: str | Path, run_id: str) -> Path:
    validated_run_id = validate_artifact_path_segment(run_id, field="run_id")
    return resolve_artifact_descendant(
        artifact_root,
        validated_run_id,
        field="run_id",
    )


def _resolve_run_artifact_path(
    artifact_root: str | Path,
    run_id: str,
    relative_path: str,
) -> Path:
    run_dir = _resolve_run_dir(artifact_root, run_id)
    normalized_relative_path = validate_relative_artifact_path(
        relative_path,
        field="artifact_path",
    )
    return resolve_artifact_descendant(
        run_dir,
        normalized_relative_path,
        field="artifact_path",
    )


def load_run_manifest(artifact_root: str | Path, run_id: str) -> dict[str, Any]:
    path = _resolve_run_artifact_path(artifact_root, run_id, "manifest.json")
    if not path.exists():
        raise FileNotFoundError(f"manifest not found for run_id: {run_id}")
    return normalize_legacy_run_manifest(json.loads(path.read_text(encoding="utf-8")))


def save_run_manifest(
    artifact_root: str | Path,
    run_id: str,
    manifest: dict[str, Any],
) -> None:
    path = _resolve_run_artifact_path(artifact_root, run_id, "manifest.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest["manifest_hash"] = manifest_hash(manifest)
    path.write_text(stable_json_dumps(to_json_safe(manifest), indent=2) + "\n", encoding="utf-8")


def load_workflow_spec_from_run(
    artifact_root: str | Path,
    run_id: str,
) -> WorkflowSpec | None:
    path = _resolve_run_artifact_path(artifact_root, run_id, "workflow_spec.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return WorkflowSpec(**payload)


def checkpoint_from_run_artifacts(
    artifact_root: str | Path,
    *,
    run_id: str,
    manifest: dict[str, Any] | None = None,
) -> WorkflowCheckpoint | None:
    run_dir = _resolve_run_dir(artifact_root, run_id)
    manifest = dict(manifest or load_run_manifest(artifact_root, run_id))
    snapshot = _read_json(
        resolve_artifact_descendant(
            run_dir,
            "data_buffer_snapshot.json",
            field="data_buffer_snapshot_path",
        )
    )
    if not isinstance(snapshot, dict):
        snapshot = {}
    step_results = _read_json(
        resolve_artifact_descendant(
            run_dir,
            "step_results.json",
            field="step_results_path",
        )
    )
    if not isinstance(step_results, dict):
        step_results = {}
    return WorkflowCheckpoint(
        checkpoint_id=str(manifest.get("latest_checkpoint_id") or f"manifest:{run_id}"),
        run_id=run_id,
        workflow_id=str(manifest["workflow_id"]),
        workflow_version=str(manifest["workflow_version"]),
        current_step_ids=[
            str(step_id)
            for step_id in manifest.get("current_step_ids", [])
            if step_id is not None
        ],
        data_buffer_snapshot=snapshot,
        step_results=step_results,
        path=[str(step_id) for step_id in manifest.get("path", [])],
        event_offset=int(manifest.get("event_count") or 0),
        metadata={"profile": str(manifest.get("profile") or "default")},
    )


def append_operation_event(run_dir: Path, event: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    events_path = resolve_artifact_descendant(
        run_dir,
        "events.jsonl",
        field="events_path",
    )
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(to_json_safe(event), ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def append_operation_record(
    manifest: dict[str, Any],
    record: WorkflowOperationRecord | dict[str, Any],
) -> None:
    payload = _operation_record_payload(record)
    operations = manifest.setdefault("operations", [])
    if not isinstance(operations, list):
        operations = []
        manifest["operations"] = operations
    operations.append(to_json_safe(payload))
    manifest["operation_count"] = len(operations)
    manifest["latest_operation_id"] = payload.get("operation_id")
    manifest["latest_operation_type"] = payload.get("operation_type")
    manifest["latest_operation_status"] = payload.get("status")


def _operation_record_payload(record: WorkflowOperationRecord | dict[str, Any]) -> dict[str, Any]:
    if isinstance(record, WorkflowOperationRecord):
        return record.to_dict()
    return dict(record)


def operation_event(
    event_type: str,
    *,
    operation_id: str,
    operation_type: WorkflowOperationType,
    run_id: str,
    actor: OperationActor | None,
    reason: str | None,
    details: dict[str, Any],
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "event_id": uuid4().hex,
        "run_id": run_id,
        "event_type": event_type,
        "occurred_at": created_at or _utc_now(),
        "payload": {
            "operation_id": operation_id,
            "operation_type": operation_type.value,
            "actor_id": actor.actor_id if actor else None,
            "actor_type": actor.actor_type if actor else None,
            "reason": reason,
            "details": to_json_safe(details),
        },
    }


def new_operation_id() -> str:
    return f"op_{uuid4().hex}"


def _guard_status(
    status: str,
    allowed_statuses: set[str],
    reason_prefix: str,
) -> RunOperationGuardResult:
    actual_status = str(status)
    if actual_status in allowed_statuses:
        return RunOperationGuardResult(allowed=True, status=actual_status)
    return RunOperationGuardResult(
        allowed=False,
        reason=f"{reason_prefix} while status is {actual_status}",
        status=actual_status,
    )


def _manifest_status(manifest: dict[str, Any]) -> str:
    return str(manifest.get("status") or "")


def _patch_diff(
    *,
    run_id: str,
    patch: dict[str, Any],
    artifact_root: Path,
) -> dict[str, dict[str, Any]]:
    snapshot_path = _resolve_run_artifact_path(
        artifact_root,
        run_id,
        "data_buffer_snapshot.json",
    )
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        snapshot = {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    return {
        str(key): {
            "before": snapshot.get(str(key)),
            "after": to_json_safe(value),
        }
        for key, value in patch.items()
    }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _step_scopes(workflow: WorkflowSpec) -> list[Any]:
    return [step_scope_from_spec(step) for step in workflow.steps]


def _skip_output_error(step: Any, skip_output: dict[str, Any]) -> str | None:
    missing_required = sorted(set(step.required_output_keys) - set(skip_output))
    if missing_required:
        return "skip_output missing required output keys: " + ", ".join(missing_required)
    nullable_keys = set(step.nullable_output_keys)
    for key, value in skip_output.items():
        if value is None and key not in nullable_keys:
            return f"skip_output key cannot be null unless nullable: {key}"
    return None


def _blocked_resolution_error(resolution: dict[str, Any]) -> str | None:
    missing = [
        key
        for key in ("reason", "resolved_by", "resolution_type")
        if not resolution.get(key)
    ]
    if missing:
        return "blocked resolution missing required fields: " + ", ".join(missing)
    if "metadata" in resolution and not isinstance(resolution.get("metadata"), dict):
        return "blocked resolution metadata must be an object"
    return None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")



