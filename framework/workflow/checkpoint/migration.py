"""Checkpoint schema migration and compatibility checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from framework.specs import WorkflowSpec
from framework.workflow.checkpoint.checksum import (
    attach_checkpoint_checksum,
    verify_checkpoint_checksum,
)
from framework.workflow.checkpoint.envelope import (
    CHECKPOINT_SCHEMA_VERSION,
    CHECKPOINT_SCHEMA_VERSION_V0,
    WorkflowCheckpointEnvelope,
    envelope_from_payload,
    envelope_to_payload,
)

SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS = {CHECKPOINT_SCHEMA_VERSION}
__all__ = [
    "CheckpointCompatibilityResult",
    "CheckpointMigration",
    "CheckpointMigrationRegistry",
    "CheckpointV0ToV1Migration",
    "SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS",
    "check_checkpoint_compatibility",
    "default_checkpoint_migration_registry",
]


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


def _can_migrate_schema_version(schema_version: str) -> bool:
    return schema_version in {CHECKPOINT_SCHEMA_VERSION_V0}


def _payload_schema_version(payload: dict[str, Any]) -> str:
    return str(payload.get("schema_version") or CHECKPOINT_SCHEMA_VERSION_V0)
