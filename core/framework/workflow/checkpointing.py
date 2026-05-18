"""Workflow checkpoint envelope helpers.

This module owns workflow-runtime checkpoint wrapping, checksums, and
compatibility checks. It does not replace the storage checkpoint model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from core.framework.specs import StepSpec, WorkflowSpec
from core.framework.workflow.human_review import (
    HumanReviewDecision,
    ensure_human_review_not_expired,
    ensure_human_review_permission,
    validate_human_review_binding,
)
from core.framework.workflow.result import StepOutcome
from storage.checkpoint import WorkflowCheckpoint

CHECKPOINT_SCHEMA_VERSION = "workflow-checkpoint/v1"
CHECKPOINT_SCHEMA_VERSION_V0 = "workflow-checkpoint/v0"
CHECKPOINT_ENVELOPE_METADATA_KEY = "checkpoint_envelope"
SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS = {CHECKPOINT_SCHEMA_VERSION}
PATCH_SYSTEM_KEYS = {
    "checkpoint_id",
    "checksum",
    "created_at",
    "current_step_ids",
    "data_buffer_snapshot",
    "manifest",
    "manifest_hash",
    "metadata",
    "path",
    "run_id",
    "schema_version",
    "step_results",
    "workflow_id",
    "workflow_version",
}
RESUME_DECISIONS = {"approved", "rejected", "needs_changes"}


@dataclass(frozen=True)
class WorkflowCheckpointEnvelope:
    checkpoint_id: str
    schema_version: str
    run_id: str
    workflow_id: str
    workflow_version: str
    current_step_ids: list[str]
    data_buffer_snapshot: dict[str, Any]
    step_results: dict[str, Any]
    path: list[str]
    manifest_hash: str | None
    checksum: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.schema_version:
            raise ValueError("schema_version is required")
        if not self.checksum:
            raise ValueError("checksum is required")


@dataclass(frozen=True)
class CheckpointCompatibilityResult:
    compatible: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    migration_required: bool = False
    migrated_schema_version: str | None = None


class CheckpointMigration(Protocol):
    source_schema_version: str
    target_schema_version: str

    def migrate(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


class ResumeMode(str, Enum):
    EXACT = "resume_exact"
    WITH_PATCH = "resume_with_patch"
    FROM_STEP = "resume_from_step"
    AFTER_HUMAN_REVIEW = "resume_after_human_review"
    AFTER_APPROVAL = "resume_after_approval"


@dataclass(frozen=True)
class WorkflowResumeRequest:
    mode: ResumeMode
    checkpoint: WorkflowCheckpointEnvelope
    run_id: str | None = None
    patch: dict[str, Any] = field(default_factory=dict)
    target_step_id: str | None = None
    human_decision: dict[str, Any] | None = None
    approval_context: dict[str, Any] | None = None
    strict: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", ResumeMode(self.mode))
        if self.mode == ResumeMode.EXACT and self.patch:
            raise ValueError("resume_exact does not allow patch")
        if self.mode == ResumeMode.WITH_PATCH and not self.patch:
            raise ValueError("resume_with_patch requires patch")
        if self.mode == ResumeMode.FROM_STEP and not self.target_step_id:
            raise ValueError("resume_from_step requires target_step_id")
        if self.mode == ResumeMode.AFTER_HUMAN_REVIEW and self.human_decision is None:
            raise ValueError("resume_after_human_review requires human_decision")
        if self.mode == ResumeMode.AFTER_APPROVAL and self.approval_context is None:
            raise ValueError("resume_after_approval requires approval_context")


@dataclass(frozen=True)
class ResumePatchValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    allowed_keys: list[str] = field(default_factory=list)
    rejected_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HumanReviewResumeDecision:
    decision: str
    actor_id: str
    reason: str | None = None
    patch: dict[str, Any] = field(default_factory=dict)
    approval_id: str | None = None
    request_id: str | None = None
    actor_roles: list[str] = field(default_factory=list)
    actor_permissions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.decision not in RESUME_DECISIONS:
            raise ValueError(f"invalid human review decision: {self.decision}")
        if not self.actor_id:
            raise ValueError("human review actor_id is required")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "decision": self.decision,
            "actor_id": self.actor_id,
            "reason": self.reason,
            "patch": dict(self.patch),
        }
        if self.approval_id is not None:
            payload["approval_id"] = self.approval_id
        if self.request_id is not None:
            payload["request_id"] = self.request_id
        if self.actor_roles:
            payload["actor_roles"] = list(self.actor_roles)
        if self.actor_permissions:
            payload["actor_permissions"] = list(self.actor_permissions)
        return payload


@dataclass(frozen=True)
class PartialArtifactRecoveryReport:
    recoverable: bool
    missing_required_artifacts: list[str] = field(default_factory=list)
    missing_optional_artifacts: list[str] = field(default_factory=list)
    recovered_artifacts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recoverable": self.recoverable,
            "missing_required_artifacts": list(self.missing_required_artifacts),
            "missing_optional_artifacts": list(self.missing_optional_artifacts),
            "recovered_artifacts": list(self.recovered_artifacts),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class WorkflowResumePlan:
    mode: ResumeMode
    run_id: str
    initial_buffer_values: dict[str, Any]
    current_step_ids: list[str]
    initial_path: list[str]
    initial_step_results: dict[str, StepOutcome]
    resumed_from_checkpoint_id: str
    resume_metadata: dict[str, Any]


def envelope_from_checkpoint(
    checkpoint: WorkflowCheckpoint,
    *,
    manifest_hash: str | None = None,
) -> WorkflowCheckpointEnvelope:
    stored_envelope = _stored_envelope_metadata(checkpoint.metadata)
    actual_manifest_hash = (
        manifest_hash
        if manifest_hash is not None
        else _optional_str(stored_envelope.get("manifest_hash"))
    )
    stored_checksum = _optional_str(stored_envelope.get("checksum"))
    envelope = WorkflowCheckpointEnvelope(
        checkpoint_id=checkpoint.checkpoint_id,
        schema_version=_optional_str(stored_envelope.get("schema_version"))
        or CHECKPOINT_SCHEMA_VERSION,
        run_id=checkpoint.run_id,
        workflow_id=checkpoint.workflow_id,
        workflow_version=checkpoint.workflow_version,
        current_step_ids=list(checkpoint.current_step_ids),
        data_buffer_snapshot=dict(checkpoint.data_buffer_snapshot),
        step_results=dict(checkpoint.step_results),
        path=list(checkpoint.path),
        manifest_hash=actual_manifest_hash,
        checksum=stored_checksum or "pending",
        created_at=_datetime_to_string(checkpoint.created_at),
        metadata={
            **dict(checkpoint.metadata),
            "event_offset": checkpoint.event_offset,
        },
    )
    if stored_checksum:
        return envelope
    return attach_checkpoint_checksum(envelope)


def envelope_to_payload(envelope: WorkflowCheckpointEnvelope) -> dict[str, Any]:
    return {
        "checkpoint_id": envelope.checkpoint_id,
        "schema_version": envelope.schema_version,
        "run_id": envelope.run_id,
        "workflow_id": envelope.workflow_id,
        "workflow_version": envelope.workflow_version,
        "current_step_ids": list(envelope.current_step_ids),
        "data_buffer_snapshot": dict(envelope.data_buffer_snapshot),
        "step_results": dict(envelope.step_results),
        "path": list(envelope.path),
        "manifest_hash": envelope.manifest_hash,
        "checksum": envelope.checksum,
        "created_at": envelope.created_at,
        "metadata": dict(envelope.metadata),
    }


def envelope_to_checkpoint(envelope: WorkflowCheckpointEnvelope) -> WorkflowCheckpoint:
    event_offset = _event_offset_from_metadata(envelope.metadata)
    metadata = {
        str(key): value
        for key, value in envelope.metadata.items()
        if key != "event_offset"
    }
    runtime_only = metadata.get("runtime_only")
    if not isinstance(runtime_only, dict):
        runtime_only = {}
    else:
        runtime_only = dict(runtime_only)
    runtime_only[CHECKPOINT_ENVELOPE_METADATA_KEY] = {
        "schema_version": envelope.schema_version,
        "manifest_hash": envelope.manifest_hash,
        "checksum": envelope.checksum,
    }
    metadata["runtime_only"] = runtime_only
    return WorkflowCheckpoint(
        checkpoint_id=envelope.checkpoint_id,
        run_id=envelope.run_id,
        workflow_id=envelope.workflow_id,
        workflow_version=envelope.workflow_version,
        current_step_ids=list(envelope.current_step_ids),
        data_buffer_snapshot=dict(envelope.data_buffer_snapshot),
        step_results=dict(envelope.step_results),
        path=list(envelope.path),
        event_offset=event_offset,
        created_at=_parse_datetime(envelope.created_at),
        metadata=metadata,
    )


def checkpoint_checksum_payload(envelope: WorkflowCheckpointEnvelope) -> dict[str, Any]:
    metadata = _metadata_checksum_payload(envelope.metadata)
    return {
        "checkpoint_id": envelope.checkpoint_id,
        "schema_version": envelope.schema_version,
        "run_id": envelope.run_id,
        "workflow_id": envelope.workflow_id,
        "workflow_version": envelope.workflow_version,
        "current_step_ids": list(envelope.current_step_ids),
        "data_buffer_snapshot": envelope.data_buffer_snapshot,
        "step_results": envelope.step_results,
        "path": list(envelope.path),
        "manifest_hash": envelope.manifest_hash,
        "created_at": envelope.created_at,
        "metadata": metadata,
    }


def stable_json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def compute_checkpoint_checksum(payload: dict[str, Any]) -> str:
    return sha256(stable_json_dumps(payload).encode("utf-8")).hexdigest()


def attach_checkpoint_checksum(
    envelope: WorkflowCheckpointEnvelope,
) -> WorkflowCheckpointEnvelope:
    checksum = compute_checkpoint_checksum(checkpoint_checksum_payload(envelope))
    return replace(envelope, checksum=checksum)


def verify_checkpoint_checksum(envelope: WorkflowCheckpointEnvelope) -> bool:
    expected = compute_checkpoint_checksum(checkpoint_checksum_payload(envelope))
    return envelope.checksum == expected


class CheckpointMigrationRegistry:
    def __init__(self) -> None:
        self._migrations: dict[str, CheckpointMigration] = {}

    def register(self, migration: CheckpointMigration) -> None:
        if not migration.source_schema_version:
            raise ValueError("migration source_schema_version is required")
        if not migration.target_schema_version:
            raise ValueError("migration target_schema_version is required")
        self._migrations[migration.source_schema_version] = migration

    def migrate_to_current(
        self,
        payload: dict[str, Any],
    ) -> WorkflowCheckpointEnvelope:
        working_payload = dict(payload)
        schema_version = _payload_schema_version(working_payload)
        if schema_version == CHECKPOINT_SCHEMA_VERSION:
            envelope = envelope_from_payload(working_payload)
            if not verify_checkpoint_checksum(envelope):
                raise ValueError("checkpoint checksum is invalid")
            return envelope

        visited: set[str] = set()
        while schema_version != CHECKPOINT_SCHEMA_VERSION:
            if schema_version in visited:
                raise ValueError(f"checkpoint migration cycle detected: {schema_version}")
            visited.add(schema_version)
            migration = self._migrations.get(schema_version)
            if migration is None:
                raise ValueError(f"no checkpoint migration path from {schema_version}")
            working_payload = migration.migrate(working_payload)
            schema_version = _payload_schema_version(working_payload)

        return attach_checkpoint_checksum(envelope_from_payload(working_payload))


class CheckpointV0ToV1Migration:
    source_schema_version = CHECKPOINT_SCHEMA_VERSION_V0
    target_schema_version = CHECKPOINT_SCHEMA_VERSION

    def migrate(self, payload: dict[str, Any]) -> dict[str, Any]:
        migrated = dict(payload)
        metadata = dict(migrated.get("metadata") or {})
        migrations = list(metadata.get("migrations") or [])
        migrations.append(
            {
                "source_schema_version": self.source_schema_version,
                "target_schema_version": self.target_schema_version,
            }
        )
        metadata["migrations"] = migrations
        migrated["schema_version"] = self.target_schema_version
        migrated.setdefault("manifest_hash", None)
        migrated["metadata"] = metadata
        migrated["checksum"] = "pending"
        return envelope_to_payload(attach_checkpoint_checksum(envelope_from_payload(migrated)))


def default_checkpoint_migration_registry() -> CheckpointMigrationRegistry:
    registry = CheckpointMigrationRegistry()
    registry.register(CheckpointV0ToV1Migration())
    return registry


def envelope_from_payload(payload: dict[str, Any]) -> WorkflowCheckpointEnvelope:
    return WorkflowCheckpointEnvelope(
        checkpoint_id=str(payload["checkpoint_id"]),
        schema_version=str(payload["schema_version"]),
        run_id=str(payload["run_id"]),
        workflow_id=str(payload["workflow_id"]),
        workflow_version=str(payload["workflow_version"]),
        current_step_ids=[str(step_id) for step_id in payload.get("current_step_ids", [])],
        data_buffer_snapshot=dict(payload.get("data_buffer_snapshot") or {}),
        step_results=dict(payload.get("step_results") or {}),
        path=[str(step_id) for step_id in payload.get("path", [])],
        manifest_hash=_optional_str(payload.get("manifest_hash")),
        checksum=str(payload["checksum"]),
        created_at=str(payload["created_at"]),
        metadata=dict(payload.get("metadata") or {}),
    )


def check_checkpoint_compatibility(
    *,
    envelope: WorkflowCheckpointEnvelope,
    workflow: WorkflowSpec,
    strict: bool = True,
    allow_version_migration: bool = False,
) -> CheckpointCompatibilityResult:
    errors: list[str] = []
    warnings: list[str] = []
    migration_required = False
    migrated_schema_version: str | None = None

    if not verify_checkpoint_checksum(envelope):
        message = "checkpoint checksum is invalid"
        if strict:
            errors.append(message)
        else:
            warnings.append(message)

    if envelope.workflow_id != workflow.workflow_id:
        errors.append(
            "checkpoint workflow_id does not match workflow: "
            f"{envelope.workflow_id} != {workflow.workflow_id}"
        )

    if envelope.workflow_version != workflow.version:
        message = (
            "checkpoint workflow_version does not match workflow: "
            f"{envelope.workflow_version} != {workflow.version}"
        )
        if allow_version_migration:
            migration_required = True
            warnings.append(message)
        else:
            errors.append(message)

    if envelope.schema_version not in SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS:
        if allow_version_migration and _can_migrate_schema_version(envelope.schema_version):
            migration_required = True
            migrated_schema_version = CHECKPOINT_SCHEMA_VERSION
            warnings.append(
                "checkpoint schema_version requires migration: "
                f"{envelope.schema_version} -> {CHECKPOINT_SCHEMA_VERSION}"
            )
        else:
            errors.append(f"unsupported checkpoint schema_version: {envelope.schema_version}")

    step_ids = {step.step_id for step in workflow.steps}
    for step_id in envelope.current_step_ids:
        if step_id not in step_ids:
            errors.append(f"checkpoint current_step_ids references unknown step: {step_id}")

    for step_id in envelope.path:
        if step_id not in step_ids:
            errors.append(f"checkpoint path references unknown step: {step_id}")

    for step_id in envelope.step_results:
        if step_id not in step_ids:
            message = f"checkpoint step_results references unknown step: {step_id}"
            if strict:
                errors.append(message)
            else:
                warnings.append(message)

    return CheckpointCompatibilityResult(
        compatible=not errors,
        errors=errors,
        warnings=warnings,
        migration_required=migration_required,
        migrated_schema_version=migrated_schema_version,
    )


def validate_resume_patch(
    *,
    workflow: WorkflowSpec,
    checkpoint: WorkflowCheckpointEnvelope,
    patch: dict[str, Any],
    allowed_patch_keys: list[str] | None = None,
    allow_request_patch: bool = False,
) -> ResumePatchValidationResult:
    allowed_keys = _allowed_resume_patch_keys(
        workflow=workflow,
        checkpoint=checkpoint,
        allowed_patch_keys=allowed_patch_keys,
        allow_request_patch=allow_request_patch,
    )
    errors: list[str] = []
    rejected_keys: list[str] = []
    for key in patch:
        key_text = str(key)
        if _is_internal_patch_key(key_text):
            errors.append(f"resume patch cannot modify internal key: {key_text}")
            rejected_keys.append(key_text)
            continue
        if key_text == "request" and not allow_request_patch:
            errors.append("resume patch cannot modify request unless allow_request_patch=True")
            rejected_keys.append(key_text)
            continue
        if key_text not in allowed_keys:
            errors.append(f"resume patch key is not allowed: {key_text}")
            rejected_keys.append(key_text)
    return ResumePatchValidationResult(
        valid=not errors,
        errors=errors,
        allowed_keys=sorted(allowed_keys),
        rejected_keys=sorted(set(rejected_keys)),
    )


class WorkflowResumePlanner:
    def plan(
        self,
        workflow: WorkflowSpec,
        request: WorkflowResumeRequest,
    ) -> WorkflowResumePlan:
        compatibility = check_checkpoint_compatibility(
            envelope=request.checkpoint,
            workflow=workflow,
            strict=request.strict,
        )
        if not compatibility.compatible:
            raise ValueError(
                "checkpoint is not compatible with workflow: "
                + "; ".join(compatibility.errors)
            )

        checkpoint = request.checkpoint
        run_id = request.run_id or f"{checkpoint.run_id}-resume-{checkpoint.checkpoint_id}"
        buffer_values = dict(checkpoint.data_buffer_snapshot)
        current_step_ids = list(checkpoint.current_step_ids)
        initial_path = list(checkpoint.path)
        step_results = _step_outcomes_from_checkpoint(checkpoint.step_results)
        resume_metadata = _base_resume_metadata(request)

        if request.mode == ResumeMode.WITH_PATCH:
            self._apply_patch(
                workflow=workflow,
                checkpoint=checkpoint,
                buffer_values=buffer_values,
                patch=request.patch,
                metadata=request.metadata,
            )
            resume_metadata["resume_patch_keys"] = sorted(str(key) for key in request.patch)
        elif request.mode == ResumeMode.FROM_STEP:
            target_step_id = str(request.target_step_id)
            _ensure_workflow_step(workflow, target_step_id)
            current_step_ids = [target_step_id]
            initial_path, step_results = _truncate_resume_state(
                target_step_id=target_step_id,
                path=initial_path,
                step_results=step_results,
            )
        elif request.mode == ResumeMode.AFTER_HUMAN_REVIEW:
            decision = coerce_human_review_resume_decision(request.human_decision)
            decision_payload = decision.to_dict()
            human_review_request = _human_review_request_from_checkpoint(checkpoint)
            validate_human_review_binding(
                checkpoint_run_id=checkpoint.run_id,
                checkpoint_id=checkpoint.checkpoint_id,
                current_step_ids=list(checkpoint.current_step_ids),
                request_payload=human_review_request,
                decision_payload=decision_payload,
                strict=(request.strict and human_review_request is not None),
            )
            ensure_human_review_not_expired(request_payload=human_review_request)
            ensure_human_review_permission(
                request_payload=human_review_request,
                decision_payload=decision_payload,
            )
            buffer_values["human_review_decision"] = decision_payload
            if decision.patch:
                self._apply_patch(
                    workflow=workflow,
                    checkpoint=checkpoint,
                    buffer_values=buffer_values,
                    patch=decision.patch,
                    metadata={
                        **dict(request.metadata),
                        "allowed_patch_keys": sorted(decision.patch),
                    },
                )
            resume_metadata["resume_actor_id"] = decision.actor_id
            resume_metadata["resume_human_decision"] = decision.decision
            if decision.approval_id is not None:
                resume_metadata["resume_approval_id"] = decision.approval_id
            if decision.request_id is not None:
                resume_metadata["resume_human_review_request_id"] = decision.request_id
            resume_metadata["resume_current_step_ids"] = list(current_step_ids)
        elif request.mode == ResumeMode.AFTER_APPROVAL:
            approval_context = dict(request.approval_context or {})
            validate_approval_resume_binding(
                checkpoint=checkpoint,
                approval_context=approval_context,
            )
            buffer_values["approval_context"] = approval_context
            buffer_values["approval_result"] = approval_context.get(
                "approval_result",
                approval_context,
            )
            decision = str(approval_context["decision"])
            actor_id = _approval_actor_id(approval_context)
            buffer_values["human_review_decision"] = {
                "decision": decision,
                "actor_id": actor_id,
                "approval_id": approval_context["approval_id"],
            }
            resume_metadata["resume_actor_id"] = actor_id
            resume_metadata["resume_approval_id"] = str(approval_context["approval_id"])

        return WorkflowResumePlan(
            mode=request.mode,
            run_id=run_id,
            initial_buffer_values=buffer_values,
            current_step_ids=current_step_ids,
            initial_path=initial_path,
            initial_step_results=step_results,
            resumed_from_checkpoint_id=checkpoint.checkpoint_id,
            resume_metadata=resume_metadata,
        )

    def _apply_patch(
        self,
        *,
        workflow: WorkflowSpec,
        checkpoint: WorkflowCheckpointEnvelope,
        buffer_values: dict[str, Any],
        patch: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        allowed_patch_keys = _metadata_list(metadata.get("allowed_patch_keys"))
        validation = validate_resume_patch(
            workflow=workflow,
            checkpoint=checkpoint,
            patch=patch,
            allowed_patch_keys=allowed_patch_keys,
            allow_request_patch=bool(metadata.get("allow_request_patch", False)),
        )
        if not validation.valid:
            raise ValueError("resume patch invalid: " + "; ".join(validation.errors))
        buffer_values.update(patch)


def validate_approval_resume_binding(
    *,
    checkpoint: WorkflowCheckpointEnvelope,
    approval_context: dict[str, Any],
) -> None:
    approval_id = str(approval_context.get("approval_id") or "")
    if not approval_id:
        raise ValueError("approval_context.approval_id is required")
    original_run_id = str(approval_context.get("original_run_id") or "")
    if not original_run_id:
        raise ValueError("approval_context.original_run_id is required")
    if original_run_id != checkpoint.run_id:
        raise ValueError(
            "approval_context.original_run_id does not match checkpoint run_id: "
            f"{original_run_id} != {checkpoint.run_id}"
        )
    checkpoint_id = str(approval_context.get("checkpoint_id") or "")
    if not checkpoint_id:
        raise ValueError("approval_context.checkpoint_id is required")
    if checkpoint_id != checkpoint.checkpoint_id:
        raise ValueError(
            "approval_context.checkpoint_id does not match checkpoint checkpoint_id: "
            f"{checkpoint_id} != {checkpoint.checkpoint_id}"
        )
    _approval_actor_id(approval_context)
    decision = str(approval_context.get("decision") or "")
    if decision not in RESUME_DECISIONS:
        raise ValueError(f"invalid approval_context.decision: {decision}")


def coerce_human_review_resume_decision(
    human_decision: HumanReviewResumeDecision | dict[str, Any] | None,
) -> HumanReviewResumeDecision:
    if human_decision is None:
        raise ValueError("human_decision is required")
    if isinstance(human_decision, HumanReviewResumeDecision):
        return human_decision
    if isinstance(human_decision, HumanReviewDecision):
        payload = human_decision.to_dict()
    elif isinstance(human_decision, dict):
        payload = dict(human_decision)
    else:
        raise ValueError("human_decision must be an object")
    patch = payload.get("patch") or {}
    if not isinstance(patch, dict):
        raise ValueError("human_decision.patch must be an object")
    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("human_decision.metadata must be an object")
    approval_id = payload.get("approval_id") or metadata.get("approval_id")
    request_id = payload.get("request_id") or metadata.get("request_id")
    actor_roles = _metadata_list(
        payload.get("actor_roles")
        or payload.get("roles")
        or metadata.get("actor_roles")
        or metadata.get("roles")
    )
    actor_permissions = _metadata_list(
        payload.get("actor_permissions")
        or payload.get("permissions")
        or metadata.get("actor_permissions")
        or metadata.get("permissions")
    )
    return HumanReviewResumeDecision(
        decision=str(payload.get("decision") or ""),
        actor_id=str(payload.get("actor_id") or ""),
        reason=_optional_str(payload.get("reason")),
        patch=dict(patch),
        approval_id=_optional_str(approval_id),
        request_id=_optional_str(request_id),
        actor_roles=actor_roles,
        actor_permissions=actor_permissions,
    )


def _human_review_request_from_checkpoint(
    checkpoint: WorkflowCheckpointEnvelope,
) -> dict[str, Any] | None:
    for value in checkpoint.data_buffer_snapshot.values():
        if not isinstance(value, dict):
            continue
        if value.get("request_id") and value.get("review_type"):
            return dict(value)
    return None


def inspect_checkpoint_artifacts(
    *,
    checkpoint: WorkflowCheckpointEnvelope,
    manifest: dict[str, Any] | None,
    artifact_root: Path,
    strict: bool,
) -> PartialArtifactRecoveryReport:
    missing_required: list[str] = []
    missing_optional: list[str] = []
    recovered: list[str] = []
    warnings: list[str] = []

    run_dir = Path(artifact_root) / checkpoint.run_id
    if manifest is None:
        if strict:
            missing_required.append("manifest.json")
        else:
            missing_optional.append("manifest.json")
            warnings.append("manifest.json is missing")
    else:
        artifacts = manifest.get("artifacts") or {}
        if isinstance(artifacts, dict):
            for artifact_key, artifact_value in sorted(artifacts.items()):
                relative_path = _artifact_manifest_path(artifact_value)
                if relative_path is None:
                    continue
                if (run_dir / relative_path).exists():
                    recovered.append(str(artifact_key))
                    continue
                if _required_artifact_key(str(artifact_key)):
                    missing_required.append(str(artifact_key))
                else:
                    missing_optional.append(str(artifact_key))
                    warnings.append(f"optional artifact is missing: {artifact_key}")
        events_path = run_dir / "events.jsonl"
        if not events_path.exists():
            missing_optional.append("events")
            warnings.append("events.jsonl is missing")

    if checkpoint.data_buffer_snapshot:
        recovered.append("checkpoint.data_buffer_snapshot")
    else:
        missing_required.append("data_buffer_snapshot")

    return PartialArtifactRecoveryReport(
        recoverable=not missing_required,
        missing_required_artifacts=sorted(set(missing_required)),
        missing_optional_artifacts=sorted(set(missing_optional)),
        recovered_artifacts=sorted(set(recovered)),
        warnings=warnings,
    )


def _metadata_checksum_payload(metadata: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    protected = metadata.get("protected")
    if isinstance(protected, dict):
        payload["protected"] = dict(protected)
    return payload


def _can_migrate_schema_version(schema_version: str) -> bool:
    return schema_version in {CHECKPOINT_SCHEMA_VERSION_V0}


def _payload_schema_version(payload: dict[str, Any]) -> str:
    return str(payload.get("schema_version") or CHECKPOINT_SCHEMA_VERSION_V0)


def _allowed_resume_patch_keys(
    *,
    workflow: WorkflowSpec,
    checkpoint: WorkflowCheckpointEnvelope,
    allowed_patch_keys: list[str] | None,
    allow_request_patch: bool,
) -> set[str]:
    allowed = {str(key) for key in (allowed_patch_keys or [])}
    allowed.update({"approval_result", "human_review_decision", "resume_metadata"})
    current_step = _current_workflow_step(workflow, checkpoint)
    if current_step is not None:
        allowed.update(str(key) for key in current_step.write_keys)
        decision_key = current_step.metadata.get("decision_key")
        if decision_key is not None:
            allowed.add(str(decision_key))
    if allow_request_patch:
        allowed.add("request")
    return allowed


def _current_workflow_step(
    workflow: WorkflowSpec,
    checkpoint: WorkflowCheckpointEnvelope,
) -> StepSpec | None:
    if not checkpoint.current_step_ids:
        return None
    step_id = checkpoint.current_step_ids[0]
    try:
        return workflow.step_by_id(step_id)
    except ValueError:
        return None


def _ensure_workflow_step(workflow: WorkflowSpec, step_id: str) -> StepSpec:
    try:
        return workflow.step_by_id(step_id)
    except ValueError as exc:
        raise ValueError(f"resume target step does not exist: {step_id}") from exc


def _truncate_resume_state(
    *,
    target_step_id: str,
    path: list[str],
    step_results: dict[str, StepOutcome],
) -> tuple[list[str], dict[str, StepOutcome]]:
    if target_step_id in path:
        index = path.index(target_step_id)
        remove_step_ids = set(path[index:])
        truncated_path = path[:index]
    else:
        remove_step_ids = {target_step_id}
        truncated_path = list(path)
    truncated_step_results = {
        step_id: outcome
        for step_id, outcome in step_results.items()
        if step_id not in remove_step_ids
    }
    return truncated_path, truncated_step_results


def _step_outcomes_from_checkpoint(payload: dict[str, Any]) -> dict[str, StepOutcome]:
    outcomes: dict[str, StepOutcome] = {}
    for step_id, raw_outcome in payload.items():
        if not isinstance(raw_outcome, dict):
            continue
        outcomes[str(step_id)] = StepOutcome.from_dict(raw_outcome)
    return outcomes


def _metadata_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _is_internal_patch_key(key: str) -> bool:
    return key in PATCH_SYSTEM_KEYS or key.startswith("_") or key.startswith("system_")


def _base_resume_metadata(request: WorkflowResumeRequest) -> dict[str, Any]:
    checkpoint = request.checkpoint
    metadata = dict(request.metadata)
    metadata.update(
        {
            "resume_mode": request.mode.value,
            "resume_original_run_id": checkpoint.run_id,
            "resume_patch_keys": sorted(str(key) for key in request.patch),
            "checkpoint_schema_version": checkpoint.schema_version,
            "checkpoint_checksum": checkpoint.checksum,
            "checkpoint_migrations": list(checkpoint.metadata.get("migrations") or []),
        }
    )
    budget_usage = checkpoint.metadata.get("budget_usage")
    if isinstance(budget_usage, dict):
        metadata["budget_usage"] = dict(budget_usage)
        metadata["resume_budget_inherited"] = True
    return metadata


def _approval_actor_id(approval_context: dict[str, Any]) -> str:
    actor_id = str(
        approval_context.get("actor_id")
        or approval_context.get("approved_by")
        or ""
    )
    if not actor_id:
        raise ValueError("approval_context.approved_by or actor_id is required")
    return actor_id


def _artifact_manifest_path(value: Any) -> Path | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("path")
    if value is None:
        return None
    path = Path(str(value))
    if path.is_absolute() or ".." in path.parts:
        return None
    return path


def _required_artifact_key(artifact_key: str) -> bool:
    return artifact_key in {"data_buffer_snapshot", "manifest"} or artifact_key.endswith(
        (".input", ".output")
    )


def _stored_envelope_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    runtime_only = metadata.get("runtime_only")
    if not isinstance(runtime_only, dict):
        return {}
    envelope_metadata = runtime_only.get(CHECKPOINT_ENVELOPE_METADATA_KEY)
    if not isinstance(envelope_metadata, dict):
        return {}
    return dict(envelope_metadata)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _event_offset_from_metadata(metadata: dict[str, Any]) -> int:
    try:
        return int(metadata.get("event_offset", 0))
    except (TypeError, ValueError):
        return 0


def _datetime_to_string(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
