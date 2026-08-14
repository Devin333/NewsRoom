from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any

from scripts.graph_only_migration.contracts import (
    ConversionStatus,
    LegacyRecord,
    LegacyRecordKind,
    LegacySourceDescriptor,
    MigrationContractError,
    MigrationInventoryRecord,
    MigrationPlan,
    MigrationPlanItem,
    QuarantineReasonCode,
    QuarantineRecord,
    RunGraphMapping,
    TransformedGraphRecord,
    checksum_for,
    required_checksum,
    required_reference,
)
from scripts.graph_only_migration.reader import (
    BoundedLegacySourceReader,
    MigrationSourceReadError,
)
from scripts.graph_only_migration.transformer import (
    GraphHistoryTransformer,
    record_run_id,
)


class GraphMigrationPlanner:
    """Build a deterministic dry-run plan without any target writes."""

    def __init__(
        self,
        *,
        reader: BoundedLegacySourceReader | None = None,
        transformer: GraphHistoryTransformer | None = None,
    ) -> None:
        self._reader = reader or BoundedLegacySourceReader()
        self._transformer = transformer or GraphHistoryTransformer()

    def build_plan(
        self,
        sources: Iterable[LegacySourceDescriptor],
        run_mappings: Mapping[str, RunGraphMapping],
        *,
        existing_targets: Mapping[str, str] | None = None,
    ) -> MigrationPlan:
        ordered_sources = _normalize_sources(sources)
        mappings = _normalize_mappings(run_mappings)
        existing = _normalize_existing_targets(existing_targets or {})
        items: list[MigrationPlanItem] = []
        for source in ordered_sources:
            try:
                records = self._reader.read(source)
            except MigrationSourceReadError as exc:
                items.append(
                    _quarantine_item(
                        source=source,
                        record=None,
                        reason_code=exc.reason_code,
                        detail=str(exc),
                    )
                )
                continue
            for record in records:
                items.append(self._plan_record(record, mappings))

        items = _enforce_event_sequences(items, mappings)
        items = _enforce_checkpoint_boundaries(items)
        items = _resolve_target_conflicts(items, existing)
        items = _enforce_referential_integrity(items)
        return MigrationPlan(
            items=tuple(items),
            source_aggregate_checksum=_source_aggregate_checksum(ordered_sources),
            mapping_aggregate_checksum=checksum_for(
                [mappings[key].mapping_checksum for key in sorted(mappings)]
            ),
        )

    def _plan_record(
        self,
        record: LegacyRecord,
        mappings: Mapping[str, RunGraphMapping],
    ) -> MigrationPlanItem:
        try:
            run_id = record_run_id(record)
            run_mapping = mappings.get(run_id) if run_id is not None else None
            target = self._transformer.transform(record, run_mapping)
        except MigrationContractError as exc:
            return _quarantine_item(
                source=record.source,
                record=record,
                reason_code=exc.reason_code,
                detail=str(exc),
            )
        except (KeyError, TypeError, ValueError) as exc:
            return _quarantine_item(
                source=record.source,
                record=record,
                reason_code=QuarantineReasonCode.AMBIGUOUS_RECORD,
                detail=f"record failed structural conversion: {type(exc).__name__}",
            )
        return _target_item(record, target)


def _normalize_sources(
    sources: Iterable[LegacySourceDescriptor],
) -> tuple[LegacySourceDescriptor, ...]:
    values = tuple(sources)
    if any(not isinstance(item, LegacySourceDescriptor) for item in values):
        raise TypeError("sources must contain LegacySourceDescriptor values")
    identities: set[tuple[str, str, str]] = set()
    for source in values:
        identity = (
            source.environment,
            source.source_store,
            source.relative_path.replace("\\", "/"),
        )
        if identity in identities:
            raise ValueError("migration source descriptor identity is duplicated")
        identities.add(identity)
    return tuple(
        sorted(
            values,
            key=lambda source: (
                source.environment,
                source.source_store,
                source.relative_path.replace("\\", "/"),
                source.record_kind.value,
                source.source_schema_version,
            ),
        )
    )


def _normalize_mappings(
    run_mappings: Mapping[str, RunGraphMapping],
) -> dict[str, RunGraphMapping]:
    normalized: dict[str, RunGraphMapping] = {}
    for raw_run_id, value in run_mappings.items():
        if not isinstance(value, RunGraphMapping):
            raise TypeError("run_mappings must contain RunGraphMapping values")
        run_id = str(raw_run_id)
        if run_id != value.run_id:
            raise ValueError("run mapping dictionary key does not match mapping run_id")
        normalized[run_id] = value
    return normalized


def _normalize_existing_targets(value: Mapping[str, str]) -> dict[str, str]:
    return {
        required_reference(raw_ref, "existing target ref"): required_checksum(
            raw_checksum,
            "existing target checksum",
        )
        for raw_ref, raw_checksum in value.items()
    }


def _source_aggregate_checksum(
    sources: tuple[LegacySourceDescriptor, ...],
) -> str:
    return checksum_for(
        [
            {
                "environment": source.environment,
                "source_store": source.source_store,
                "owner": source.owner,
                "record_kind": source.record_kind.value,
                "relative_path": source.relative_path.replace("\\", "/"),
                "source_schema_version": source.source_schema_version,
                "source_checksum": source.source_checksum,
            }
            for source in sources
        ]
    )


def _target_item(
    record: LegacyRecord,
    target: TransformedGraphRecord,
) -> MigrationPlanItem:
    inventory = MigrationInventoryRecord(
        environment=record.source.environment,
        source_store=record.source.source_store,
        source_record_ref=record.source_record_ref,
        source_schema_version=record.source.source_schema_version,
        source_checksum=record.source.source_checksum,
        record_kind=record.source.record_kind,
        conversion_status=ConversionStatus.CONVERTED,
        target_ref=target.target_ref,
        target_checksum=target.target_checksum,
        quarantine_reason=None,
        owner=record.source.owner,
    )
    return MigrationPlanItem(inventory=inventory, target=target)


def _quarantine_item(
    *,
    source: LegacySourceDescriptor,
    record: LegacyRecord | None,
    reason_code: QuarantineReasonCode,
    detail: str,
    target_ref: str | None = None,
    target_checksum: str | None = None,
) -> MigrationPlanItem:
    source_record_ref = record.source_record_ref if record is not None else source.source_ref
    quarantine = QuarantineRecord(
        environment=source.environment,
        source_store=source.source_store,
        source_record_ref=source_record_ref,
        source_schema_version=source.source_schema_version,
        source_checksum=source.source_checksum,
        source_record_checksum=(
            record.source_record_checksum if record is not None else None
        ),
        record_kind=source.record_kind,
        reason_code=reason_code,
        owner=source.owner,
        detail=detail,
    )
    inventory = MigrationInventoryRecord(
        environment=source.environment,
        source_store=source.source_store,
        source_record_ref=source_record_ref,
        source_schema_version=source.source_schema_version,
        source_checksum=source.source_checksum,
        record_kind=source.record_kind,
        conversion_status=ConversionStatus.QUARANTINED,
        target_ref=target_ref,
        target_checksum=target_checksum,
        quarantine_reason=reason_code,
        owner=source.owner,
    )
    return MigrationPlanItem(inventory=inventory, quarantine=quarantine)


def _quarantine_target_item(
    item: MigrationPlanItem,
    *,
    reason_code: QuarantineReasonCode,
    detail: str,
) -> MigrationPlanItem:
    target = item.target
    assert target is not None
    record_checksum = target.provenance.source_record_checksum
    quarantine = QuarantineRecord(
        environment=item.inventory.environment,
        source_store=item.inventory.source_store,
        source_record_ref=item.inventory.source_record_ref,
        source_schema_version=item.inventory.source_schema_version,
        source_checksum=item.inventory.source_checksum,
        source_record_checksum=record_checksum,
        record_kind=item.inventory.record_kind,
        reason_code=reason_code,
        owner=item.inventory.owner,
        detail=detail,
    )
    inventory = replace(
        item.inventory,
        conversion_status=ConversionStatus.QUARANTINED,
        quarantine_reason=reason_code,
    )
    return MigrationPlanItem(inventory=inventory, quarantine=quarantine)


def _enforce_event_sequences(
    items: list[MigrationPlanItem],
    mappings: Mapping[str, RunGraphMapping],
) -> list[MigrationPlanItem]:
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, item in enumerate(items):
        target = item.target
        if (
            target is None
            or target.record_kind is not LegacyRecordKind.WORKFLOW_EVENT
            or target.run_id is None
            or target.stream_id is None
            or target.stream_sequence is None
        ):
            continue
        groups[(target.run_id, target.stream_id)].append(index)
    result = list(items)
    for (run_id, _stream_id), indexes in sorted(groups.items()):
        values = sorted(
            result[index].target.stream_sequence  # type: ignore[union-attr]
            for index in indexes
        )
        first_sequence = mappings[run_id].event_first_sequence
        expected = list(range(first_sequence, first_sequence + len(values)))
        if values == expected:
            continue
        for index in indexes:
            result[index] = _quarantine_target_item(
                result[index],
                reason_code=QuarantineReasonCode.EVENT_SEQUENCE_GAP,
                detail="event stream is duplicated, missing, or starts outside the reviewed boundary",
            )
    return result


def _enforce_checkpoint_boundaries(
    items: list[MigrationPlanItem],
) -> list[MigrationPlanItem]:
    events: dict[tuple[str, int], str] = {}
    for item in items:
        target = item.target
        if (
            target is not None
            and target.record_kind is LegacyRecordKind.WORKFLOW_EVENT
            and target.run_id is not None
            and target.stream_sequence is not None
        ):
            events[(target.run_id, target.stream_sequence)] = target.target_ref
    result = list(items)
    for index, item in enumerate(result):
        target = item.target
        if (
            target is None
            or target.record_kind is not LegacyRecordKind.WORKFLOW_CHECKPOINT
            or target.run_id is None
            or target.stream_sequence is None
        ):
            continue
        event_ref = events.get((target.run_id, target.stream_sequence))
        if event_ref is None:
            result[index] = _quarantine_target_item(
                item,
                reason_code=QuarantineReasonCode.INCOMPATIBLE_CHECKPOINT,
                detail="checkpoint boundary is absent from converted event history",
            )
            continue
        last_event_id = target.payload.get("last_event_id")
        if event_ref.endswith(f"/{last_event_id}"):
            continue
        result[index] = _quarantine_target_item(
            item,
            reason_code=QuarantineReasonCode.INCOMPATIBLE_CHECKPOINT,
            detail="checkpoint boundary event does not match converted event history",
        )
    return result


def _resolve_target_conflicts(
    items: list[MigrationPlanItem],
    existing_targets: Mapping[str, str],
) -> list[MigrationPlanItem]:
    groups: dict[str, list[int]] = defaultdict(list)
    for index, item in enumerate(items):
        if item.target is not None:
            groups[item.target.target_ref].append(index)
    result = list(items)
    for target_ref, indexes in sorted(groups.items()):
        checksums = {
            result[index].target.target_checksum  # type: ignore[union-attr]
            for index in indexes
        }
        existing_checksum = existing_targets.get(target_ref)
        if len(checksums) > 1 or (
            existing_checksum is not None and existing_checksum not in checksums
        ):
            for index in indexes:
                result[index] = _quarantine_target_item(
                    result[index],
                    reason_code=QuarantineReasonCode.TARGET_CONFLICT,
                    detail="target identity already resolves to different canonical content",
                )
            continue
        if existing_checksum is not None:
            for index in indexes:
                result[index] = _mark_idempotent(result[index])
            continue
        for duplicate_index in indexes[1:]:
            result[duplicate_index] = _mark_idempotent(result[duplicate_index])
    return result


def _enforce_referential_integrity(
    items: list[MigrationPlanItem],
) -> list[MigrationPlanItem]:
    result = list(items)
    result = _require_references_for_kinds(
        result,
        kinds=(LegacyRecordKind.RUN_MANIFEST,),
    )
    result = _require_references_for_kinds(
        result,
        kinds=(
            LegacyRecordKind.CONVERSATION_CURSOR,
            LegacyRecordKind.ITERATION_CHECKPOINT,
        ),
    )
    return _require_references_for_kinds(
        result,
        kinds=(LegacyRecordKind.REPLAY_BUNDLE,),
    )


def _require_references_for_kinds(
    items: list[MigrationPlanItem],
    *,
    kinds: tuple[LegacyRecordKind, ...],
) -> list[MigrationPlanItem]:
    available = {
        item.target.target_ref
        for item in items
        if item.target is not None
    }
    result = list(items)
    for index, item in enumerate(result):
        target = item.target
        if target is None or target.record_kind not in kinds:
            continue
        required_refs = _required_target_references(target)
        missing = tuple(sorted(ref for ref in required_refs if ref not in available))
        if not missing:
            continue
        reason_code = (
            QuarantineReasonCode.INCOMPATIBLE_CHECKPOINT
            if target.record_kind
            in {
                LegacyRecordKind.CONVERSATION_CURSOR,
                LegacyRecordKind.ITERATION_CHECKPOINT,
            }
            else QuarantineReasonCode.MISSING_TERMINAL_EVIDENCE
        )
        result[index] = _quarantine_target_item(
            item,
            reason_code=reason_code,
            detail="converted record references absent or quarantined staging evidence",
        )
    return result


def _required_target_references(
    target: TransformedGraphRecord,
) -> tuple[str, ...]:
    payload = target.payload
    if target.record_kind is LegacyRecordKind.RUN_MANIFEST:
        return (required_reference(payload.get("checkpoint_ref"), "checkpoint_ref"),)
    if target.record_kind is LegacyRecordKind.REPLAY_BUNDLE:
        return tuple(
            required_reference(ref, "replay evidence ref")
            for ref in (
                payload.get("terminal_manifest_ref"),
                payload.get("checkpoint_ref"),
                *tuple(payload.get("event_refs", ())),
                *tuple(payload.get("artifact_refs", ())),
            )
        )
    references: list[str] = []
    checkpoint_ref = payload.get("graph_checkpoint_ref")
    if checkpoint_ref is not None:
        references.append(
            required_reference(checkpoint_ref, "graph_checkpoint_ref")
        )
    if target.record_kind is LegacyRecordKind.ITERATION_CHECKPOINT:
        references.extend(
            required_reference(ref, "llm_call_artifact_ref")
            for ref in payload.get("llm_call_artifact_refs", ())
            if str(ref).startswith("graph://")
        )
    return tuple(references)


def _mark_idempotent(item: MigrationPlanItem) -> MigrationPlanItem:
    assert item.target is not None
    return MigrationPlanItem(
        inventory=replace(
            item.inventory,
            conversion_status=ConversionStatus.SKIPPED_IDEMPOTENT,
        ),
        target=item.target,
    )


__all__ = ["GraphMigrationPlanner"]
