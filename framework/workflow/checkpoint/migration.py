"""Checkpoint schema migration and compatibility checks."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from framework.events.runtime.models import LegacyEventOffset
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
from framework.workflow.checkpoint.durable import (
    CHECKPOINT_SCHEMA_VERSION_V2,
    WorkflowCheckpointV2Envelope,
    attach_durable_checkpoint_checksum,
    canonical_run_stream_id,
    durable_envelope_from_payload,
    durable_envelope_to_payload,
    verify_durable_checkpoint_checksum,
)

SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS = {
    CHECKPOINT_SCHEMA_VERSION,
    CHECKPOINT_SCHEMA_VERSION_V2,
}
__all__ = [
    "CheckpointCompatibilityResult",
    "CheckpointMigration",
    "CheckpointMigrationRegistry",
    "CheckpointV0ToV1Migration",
    "CheckpointV1ToV2Migration",
    "DurableCheckpointMigrationRegistry",
    "LegacyCheckpointBoundaryMapping",
    "LegacyCheckpointBoundaryResolver",
    "LegacyCheckpointOffsetSemantics",
    "RecordedLegacyCheckpointBoundaryResolver",
    "SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS",
    "check_checkpoint_compatibility",
    "default_checkpoint_migration_registry",
    "durable_checkpoint_migration_registry",
    "normalize_checkpoint_payload_for_migration",
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


class LegacyCheckpointOffsetSemantics(str, Enum):
    """Meaning of the historical integer supplied to the import mapping."""

    JSONL_LINE_INDEX = "jsonl_0_based_line_index"
    RECORDER_EVENT_COUNT = "workflow_recorder_event_count"


@dataclass(frozen=True, slots=True)
class LegacyCheckpointBoundaryMapping:
    """A recorded import result for one ambiguous legacy checkpoint boundary.

    No arithmetic relationship between ``legacy_event_offset`` and
    ``last_durable_stream_sequence`` is assumed.  Quarantine, duplicate
    collapse, and historical recorder-count semantics can all make ``+1``
    incorrect.  An empty source history is represented by an explicit mapping
    whose canonical sequence and event identity are both absent.
    """

    mapping_id: str
    checkpoint_id: str
    run_id: str
    source_semantics: LegacyCheckpointOffsetSemantics
    legacy_event_offset: LegacyEventOffset | None
    stream_id: str
    last_durable_stream_sequence: int | None
    last_event_id: str | None

    def __post_init__(self) -> None:
        mapping_id = _required_mapping_text(self.mapping_id, "mapping_id")
        checkpoint_id = _required_mapping_text(self.checkpoint_id, "checkpoint_id")
        run_id = _required_mapping_text(self.run_id, "run_id")
        semantics = LegacyCheckpointOffsetSemantics(self.source_semantics)
        offset = self.legacy_event_offset
        if offset is not None and not isinstance(offset, LegacyEventOffset):
            offset = LegacyEventOffset(offset)
        stream_id = _required_mapping_text(self.stream_id, "stream_id")
        expected_stream_id = canonical_run_stream_id(run_id)
        if stream_id != expected_stream_id:
            raise ValueError(
                "legacy boundary mapping stream_id does not match run stream: "
                f"{stream_id} != {expected_stream_id}"
            )
        sequence = self.last_durable_stream_sequence
        if sequence is not None and (
            isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1
        ):
            raise ValueError(
                "last_durable_stream_sequence must be a positive 1-based integer"
            )
        event_id = _optional_mapping_text(self.last_event_id, "last_event_id")
        if (sequence is None) != (event_id is None):
            raise ValueError(
                "mapping sequence and last_event_id must both be set or absent"
            )
        object.__setattr__(self, "mapping_id", mapping_id)
        object.__setattr__(self, "checkpoint_id", checkpoint_id)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "source_semantics", semantics)
        object.__setattr__(self, "legacy_event_offset", offset)
        object.__setattr__(self, "stream_id", stream_id)
        object.__setattr__(self, "last_event_id", event_id)


class LegacyCheckpointBoundaryResolver(Protocol):
    def resolve(
        self,
        *,
        checkpoint_id: str,
        run_id: str,
        source_semantics: LegacyCheckpointOffsetSemantics,
        legacy_event_offset: LegacyEventOffset | None,
    ) -> LegacyCheckpointBoundaryMapping | None:
        ...


class RecordedLegacyCheckpointBoundaryResolver:
    """Read-only resolver backed by migration-produced mapping records."""

    def __init__(self, mappings: Iterable[LegacyCheckpointBoundaryMapping]) -> None:
        self._mappings: dict[
            tuple[str, str, LegacyCheckpointOffsetSemantics, int | None],
            LegacyCheckpointBoundaryMapping,
        ] = {}
        checkpoint_identities: set[
            tuple[str, str, LegacyCheckpointOffsetSemantics]
        ] = set()
        for mapping in mappings:
            if not isinstance(mapping, LegacyCheckpointBoundaryMapping):
                raise TypeError("mappings must contain LegacyCheckpointBoundaryMapping")
            key = _legacy_mapping_key(
                checkpoint_id=mapping.checkpoint_id,
                run_id=mapping.run_id,
                source_semantics=mapping.source_semantics,
                legacy_event_offset=mapping.legacy_event_offset,
            )
            if key in self._mappings:
                raise ValueError(
                    "duplicate recorded legacy checkpoint boundary mapping: "
                    f"{mapping.checkpoint_id}"
                )
            checkpoint_identity = (
                mapping.checkpoint_id,
                mapping.run_id,
                mapping.source_semantics,
            )
            if checkpoint_identity in checkpoint_identities:
                raise ValueError(
                    "legacy checkpoint identity has multiple recorded boundaries: "
                    f"{mapping.checkpoint_id}"
                )
            checkpoint_identities.add(checkpoint_identity)
            self._mappings[key] = mapping

    def resolve(
        self,
        *,
        checkpoint_id: str,
        run_id: str,
        source_semantics: LegacyCheckpointOffsetSemantics,
        legacy_event_offset: LegacyEventOffset | None,
    ) -> LegacyCheckpointBoundaryMapping | None:
        return self._mappings.get(
            _legacy_mapping_key(
                checkpoint_id=checkpoint_id,
                run_id=run_id,
                source_semantics=source_semantics,
                legacy_event_offset=legacy_event_offset,
            )
        )


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


class CheckpointV1ToV2Migration:
    """Map a verified v1 checkpoint through recorded event-import identity."""

    source_schema_version = CHECKPOINT_SCHEMA_VERSION
    target_schema_version = CHECKPOINT_SCHEMA_VERSION_V2

    def __init__(self, resolver: LegacyCheckpointBoundaryResolver) -> None:
        self._resolver = resolver

    def migrate(
        self,
        payload: dict[str, Any],
        *,
        source_semantics: LegacyCheckpointOffsetSemantics,
    ) -> dict[str, Any]:
        normalized = normalize_checkpoint_payload_for_migration(payload)
        envelope = envelope_from_payload(normalized)
        if not verify_checkpoint_checksum(envelope):
            raise ValueError("checkpoint checksum is invalid")

        metadata = dict(envelope.metadata)
        offset, semantics = _legacy_offset_and_semantics(
            metadata,
            supplied_semantics=source_semantics,
        )
        mapping = self._resolver.resolve(
            checkpoint_id=envelope.checkpoint_id,
            run_id=envelope.run_id,
            source_semantics=semantics,
            legacy_event_offset=offset,
        )
        if mapping is None:
            raise ValueError(
                "legacy checkpoint boundary is ambiguous without a recorded import mapping"
            )

        metadata.pop("event_offset", None)
        metadata.pop("legacy_event_offset", None)
        metadata.pop("legacy_offset_semantics", None)
        migrations = list(metadata.get("migrations") or [])
        migrations.append(
            {
                "source_schema_version": self.source_schema_version,
                "target_schema_version": self.target_schema_version,
            }
        )
        metadata["migrations"] = migrations
        metadata["legacy_import"] = {
            "mapping_id": mapping.mapping_id,
            "source_schema_version": self.source_schema_version,
            "source_semantics": mapping.source_semantics.value,
            "legacy_event_offset": (
                None
                if mapping.legacy_event_offset is None
                else mapping.legacy_event_offset.value
            ),
        }
        migrated = WorkflowCheckpointV2Envelope(
            checkpoint_id=envelope.checkpoint_id,
            run_id=envelope.run_id,
            workflow_id=envelope.workflow_id,
            workflow_version=envelope.workflow_version,
            current_step_ids=list(envelope.current_step_ids),
            data_buffer_snapshot=dict(envelope.data_buffer_snapshot),
            step_results=dict(envelope.step_results),
            path=list(envelope.path),
            stream_id=mapping.stream_id,
            last_durable_stream_sequence=mapping.last_durable_stream_sequence,
            last_event_id=mapping.last_event_id,
            manifest_hash=envelope.manifest_hash,
            checksum="pending",
            created_at=envelope.created_at,
            metadata=metadata,
        )
        migrated = attach_durable_checkpoint_checksum(migrated)
        if not verify_durable_checkpoint_checksum(migrated):
            raise ValueError("migrated checkpoint checksum is invalid")
        return durable_envelope_to_payload(migrated)


class DurableCheckpointMigrationRegistry:
    """Explicit opt-in v0/v1 -> v2 import path.

    It is intentionally separate from ``default_checkpoint_migration_registry``
    so the deployed v1 writer/read behavior cannot change implicitly.
    """

    def __init__(self, resolver: LegacyCheckpointBoundaryResolver) -> None:
        self._v0_to_v1 = CheckpointV0ToV1Migration()
        self._v1_to_v2 = CheckpointV1ToV2Migration(resolver)

    def migrate_to_v2(
        self,
        payload: dict[str, Any],
        *,
        source_semantics: LegacyCheckpointOffsetSemantics,
    ) -> WorkflowCheckpointV2Envelope:
        working = normalize_checkpoint_payload_for_migration(payload)
        schema_version = _payload_schema_version(working)
        if schema_version == CHECKPOINT_SCHEMA_VERSION_V2:
            envelope = durable_envelope_from_payload(working)
            if not verify_durable_checkpoint_checksum(envelope):
                raise ValueError("checkpoint checksum is invalid")
            return envelope
        if schema_version == CHECKPOINT_SCHEMA_VERSION_V0:
            working = self._v0_to_v1.migrate(working)
            schema_version = _payload_schema_version(working)
        if schema_version != CHECKPOINT_SCHEMA_VERSION:
            raise ValueError(
                "no durable checkpoint migration path from " + schema_version
            )
        envelope = durable_envelope_from_payload(
            self._v1_to_v2.migrate(
                working,
                source_semantics=source_semantics,
            )
        )
        if not verify_durable_checkpoint_checksum(envelope):
            raise ValueError("migrated checkpoint checksum is invalid")
        return envelope


def durable_checkpoint_migration_registry(
    resolver: LegacyCheckpointBoundaryResolver,
) -> DurableCheckpointMigrationRegistry:
    return DurableCheckpointMigrationRegistry(resolver)


def normalize_checkpoint_payload_for_migration(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Normalize saved-model/envelope shapes without guessing event identity."""

    normalized = dict(payload)
    metadata = dict(normalized.get("metadata") or {})
    runtime_only = metadata.get("runtime_only")
    embedded = (
        runtime_only.get("checkpoint_envelope")
        if isinstance(runtime_only, dict)
        else None
    )
    if isinstance(embedded, dict):
        normalized.setdefault("schema_version", embedded.get("schema_version"))
        normalized.setdefault("manifest_hash", embedded.get("manifest_hash"))
        normalized.setdefault("checksum", embedded.get("checksum"))
        metadata.pop("runtime_only", None)

    top_level_offset = normalized.pop("event_offset", None)
    metadata_offset = metadata.get("event_offset")
    if top_level_offset is not None and metadata_offset is not None:
        if _legacy_offset(top_level_offset).value != _legacy_offset(metadata_offset).value:
            raise ValueError("conflicting legacy checkpoint event_offset values")
    if metadata_offset is None and top_level_offset is not None:
        metadata["event_offset"] = _legacy_offset(top_level_offset).value
    normalized["metadata"] = metadata
    return normalized


def default_checkpoint_migration_registry() -> CheckpointMigrationRegistry:
    registry = CheckpointMigrationRegistry()
    registry.register(CheckpointV0ToV1Migration())
    return registry


def check_checkpoint_compatibility(
    *,
    envelope: WorkflowCheckpointEnvelope | WorkflowCheckpointV2Envelope,
    workflow: WorkflowSpec,
    strict: bool = True,
    allow_version_migration: bool = False,
) -> CheckpointCompatibilityResult:
    errors: list[str] = []
    warnings: list[str] = []
    migration_required = False
    migrated_schema_version: str | None = None

    if isinstance(envelope, WorkflowCheckpointV2Envelope):
        checksum_valid = verify_durable_checkpoint_checksum(envelope)
        expected_schema_version = CHECKPOINT_SCHEMA_VERSION_V2
    elif isinstance(envelope, WorkflowCheckpointEnvelope):
        checksum_valid = verify_checkpoint_checksum(envelope)
        expected_schema_version = CHECKPOINT_SCHEMA_VERSION
    else:
        raise TypeError("checkpoint envelope must be a supported v1 or v2 envelope")

    if not checksum_valid:
        message = "checkpoint checksum is invalid"
        if strict:
            errors.append(message)
        else:
            warnings.append(message)

    if envelope.schema_version != expected_schema_version:
        errors.append(
            "checkpoint envelope type does not match schema_version: "
            f"{envelope.schema_version} != {expected_schema_version}"
        )

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


def _legacy_offset_and_semantics(
    metadata: dict[str, Any],
    *,
    supplied_semantics: LegacyCheckpointOffsetSemantics,
) -> tuple[LegacyEventOffset | None, LegacyCheckpointOffsetSemantics]:
    raw_event_offset = metadata.get("event_offset")
    raw_import_offset = metadata.get("legacy_event_offset")
    if raw_event_offset is not None and raw_import_offset is not None:
        if _legacy_offset(raw_event_offset).value != _legacy_offset(raw_import_offset).value:
            raise ValueError("conflicting legacy checkpoint event offsets")
    raw_offset = (
        raw_event_offset if raw_event_offset is not None else raw_import_offset
    )
    semantics = LegacyCheckpointOffsetSemantics(supplied_semantics)
    raw_semantics = metadata.get("legacy_offset_semantics")
    if raw_semantics is not None:
        declared = LegacyCheckpointOffsetSemantics(str(raw_semantics))
        if declared is not semantics:
            raise ValueError("conflicting legacy checkpoint offset semantics")
    offset = None if raw_offset is None else _legacy_offset(raw_offset)
    return offset, semantics


def _legacy_offset(value: Any) -> LegacyEventOffset:
    if isinstance(value, LegacyEventOffset):
        return value
    if isinstance(value, bool):
        raise ValueError("legacy event offset must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("legacy event offset must be a non-negative integer") from exc
    return LegacyEventOffset(parsed)


def _legacy_mapping_key(
    *,
    checkpoint_id: str,
    run_id: str,
    source_semantics: LegacyCheckpointOffsetSemantics,
    legacy_event_offset: LegacyEventOffset | None,
) -> tuple[str, str, LegacyCheckpointOffsetSemantics, int | None]:
    semantics = LegacyCheckpointOffsetSemantics(source_semantics)
    offset = (
        None
        if legacy_event_offset is None
        else _legacy_offset(legacy_event_offset).value
    )
    return (
        _required_mapping_text(checkpoint_id, "checkpoint_id"),
        _required_mapping_text(run_id, "run_id"),
        semantics,
        offset,
    )


def _required_mapping_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _optional_mapping_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} cannot be empty")
    return value.strip()
