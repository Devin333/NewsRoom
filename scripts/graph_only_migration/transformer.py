from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from hmac import compare_digest
from pathlib import PurePosixPath, PureWindowsPath
import re
from typing import Any

from scripts.graph_only_migration.contracts import (
    GRAPH_ARTIFACT_INDEX_SCHEMA,
    GRAPH_CHECKPOINT_SCHEMA,
    GRAPH_CONVERSATION_CURSOR_SCHEMA,
    GRAPH_EVENT_SCHEMA,
    GRAPH_ITERATION_CHECKPOINT_SCHEMA,
    GRAPH_REPLAY_BUNDLE_SCHEMA,
    GRAPH_TERMINAL_MANIFEST_SCHEMA,
    GraphNodeBinding,
    LegacyRecord,
    LegacyRecordKind,
    MigrationContractError,
    QuarantineReasonCode,
    RunGraphMapping,
    TransformedGraphRecord,
    aware_datetime,
    canonical_json_bytes,
    checksum_for,
    mapping,
    normalize_checksum,
    provenance_for,
    required_checksum,
    required_identifier,
    required_reference,
    required_text,
    sequence,
    thaw_json,
)


_WINDOWS_RESERVED_CHARACTERS = frozenset('<>:"|?*')
_DOS_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "client_secret",
        "credential",
        "credentials",
        "password",
        "passwd",
        "private_context",
        "raw_prompt",
        "refresh_token",
        "secret",
        "system_prompt",
        "token",
    }
)
_SENSITIVE_SUFFIXES = (
    "_api_key",
    "_credential",
    "_credentials",
    "_password",
    "_secret",
    "_token",
)
_MEDIA_TYPE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\Z"
)
_LEGACY_REQUIRED_RUN_ARTIFACT_KEYS = frozenset(
    {
        "request",
        "workflow_spec",
        "workflow_version",
        "events",
        "manifest",
        "data_buffer_snapshot",
        "data_buffer_initial",
        "data_buffer_final",
        "data_buffer_diff",
        "step_results",
        "metrics",
        "redaction_report",
    }
)


class GraphHistoryTransformer:
    """Pure conversion from detached legacy records into Graph history records."""

    def transform(
        self,
        record: LegacyRecord,
        run_mapping: RunGraphMapping | None,
    ) -> TransformedGraphRecord:
        if not isinstance(record, LegacyRecord):
            raise TypeError("record must be a LegacyRecord")
        if run_mapping is not None and not isinstance(run_mapping, RunGraphMapping):
            raise TypeError("run_mapping must be RunGraphMapping or None")
        run_id = record_run_id(record)
        if run_id is not None:
            if run_mapping is None:
                raise MigrationContractError(
                    QuarantineReasonCode.MISSING_GRAPH_IDENTITY,
                    "legacy record has no reviewed Graph run mapping",
                )
            if run_mapping.run_id != run_id:
                raise MigrationContractError(
                    QuarantineReasonCode.AMBIGUOUS_RECORD,
                    "legacy record run identity conflicts with its Graph mapping",
                )
            _validate_mapping_identity(record.value, record.record_kind, run_mapping)
        elif run_mapping is not None:
            raise MigrationContractError(
                QuarantineReasonCode.AMBIGUOUS_RECORD,
                "record without a run identity received a Graph run mapping",
            )

        dispatch = {
            LegacyRecordKind.RUN_MANIFEST: self._manifest,
            LegacyRecordKind.WORKFLOW_EVENT: self._event,
            LegacyRecordKind.WORKFLOW_CHECKPOINT: self._checkpoint,
            LegacyRecordKind.REPLAY_BUNDLE: self._replay_bundle,
            LegacyRecordKind.ARTIFACT_INDEX: self._artifact_index,
            LegacyRecordKind.CONVERSATION_CURSOR: self._conversation_cursor,
            LegacyRecordKind.ITERATION_CHECKPOINT: self._iteration_checkpoint,
        }
        return dispatch[record.record_kind](record, run_mapping)

    def _manifest(
        self,
        record: LegacyRecord,
        run_mapping: RunGraphMapping | None,
    ) -> TransformedGraphRecord:
        current = _required_run_mapping(run_mapping)
        _require_terminal_evidence(current)
        value = record.value
        status = required_text(value.get("status"), "status")
        if status != current.terminal_status:
            raise MigrationContractError(
                QuarantineReasonCode.MISSING_TERMINAL_EVIDENCE,
                "manifest terminal status does not match the reviewed Graph mapping",
            )
        aware_datetime(value.get("started_at"), "started_at")
        completed_raw = value.get("finished_at") or value.get("completed_at")
        if completed_raw is None:
            raise MigrationContractError(
                QuarantineReasonCode.MISSING_TERMINAL_EVIDENCE,
                "terminal manifest has no completion timestamp",
            )
        aware_datetime(completed_raw, "completed_at")
        legacy_checkpoint_id = _first_text(
            value,
            "checkpoint_ref",
            "latest_checkpoint_id",
        )
        if legacy_checkpoint_id is None:
            raise MigrationContractError(
                QuarantineReasonCode.MISSING_TERMINAL_EVIDENCE,
                "terminal manifest has no checkpoint reference",
            )
        graph_checkpoint_ref = current.checkpoint_ref(legacy_checkpoint_id)
        artifacts = _terminal_artifacts(value, current)
        if any(item["required_for_publication"] for item in artifacts):
            if current.publication_evidence is None:
                raise MigrationContractError(
                    QuarantineReasonCode.MISSING_TERMINAL_EVIDENCE,
                    "publication-marked artifacts require reviewed publication evidence",
                )
            publication: Mapping[str, Any] | None = current.publication_evidence
        else:
            publication = None
        try:
            manifest = _terminal_manifest_payload(
                run_mapping=current,
                started_at_raw=required_text(value.get("started_at"), "started_at"),
                completed_at_raw=required_text(completed_raw, "completed_at"),
                graph_checkpoint_ref=graph_checkpoint_ref,
                artifacts=artifacts,
                publication=publication,
            )
        except (TypeError, ValueError) as exc:
            raise MigrationContractError(
                QuarantineReasonCode.MISSING_TERMINAL_EVIDENCE,
                "legacy manifest cannot satisfy the Graph terminal manifest contract",
            ) from exc
        return TransformedGraphRecord(
            record_kind=record.record_kind,
            run_id=current.run_id,
            target_ref=f"graph://runs/{current.run_id}/terminal-manifest",
            target_schema_version=GRAPH_TERMINAL_MANIFEST_SCHEMA,
            payload=manifest,
            target_checksum=manifest["manifest_hash"],
            provenance=provenance_for(record, current),
        )

    def _event(
        self,
        record: LegacyRecord,
        run_mapping: RunGraphMapping | None,
    ) -> TransformedGraphRecord:
        current = _required_run_mapping(run_mapping)
        _require_gate_evidence(current)
        value = record.value
        event = _event_source_view(value)
        event_id = required_identifier(event["event_id"], "event_id")
        stream_id = required_text(event["stream_id"], "stream_id")
        expected_stream_id = f"run:{current.run_id}"
        if stream_id != expected_stream_id:
            raise MigrationContractError(
                QuarantineReasonCode.AMBIGUOUS_RECORD,
                "event stream identity does not match its run",
            )
        stream_sequence = _positive_int(
            event["stream_sequence"],
            "stream_sequence",
        )
        occurred_at = event["occurred_at"]
        if occurred_at is None:
            raise MigrationContractError(
                QuarantineReasonCode.AMBIGUOUS_RECORD,
                "event has no authoritative timestamp",
            )
        aware_datetime(occurred_at, "occurred_at")
        source_event_type = required_text(event["event_type"], "event_type")
        raw_step_id = _optional_text(event["step_id"])
        binding = current.node_binding(raw_step_id) if raw_step_id is not None else None
        raw_payload = mapping(event["payload"], "payload")
        migrated_payload = _map_control_identity(raw_payload, current)
        source_tenant_id = _optional_text(event["tenant_id"])
        if source_tenant_id is not None and source_tenant_id != current.tenant_id:
            raise MigrationContractError(
                QuarantineReasonCode.AMBIGUOUS_RECORD,
                "event tenant identity conflicts with its Graph mapping",
            )
        payload = {
            "schema_version": GRAPH_EVENT_SCHEMA,
            "event_id": event_id,
            "event_type": f"graph_history.{source_event_type}",
            "source_event_type": source_event_type,
            "occurred_at": occurred_at,
            "tenant_id": current.tenant_id,
            "run_id": current.run_id,
            "graph_ref": current.graph_ref.to_dict(),
            "node_id": binding.node_id if binding is not None else None,
            "node_instance_id": (
                binding.node_instance_id if binding is not None else None
            ),
            "stream_id": stream_id,
            "stream_sequence": stream_sequence,
            "payload": migrated_payload,
            "gate_evidence_refs": list(current.gate_evidence_refs),
            "history_only": True,
        }
        checked, target_checksum = _attach_record_checksum(payload)
        return TransformedGraphRecord(
            record_kind=record.record_kind,
            run_id=current.run_id,
            target_ref=f"graph://runs/{current.run_id}/events/{event_id}",
            target_schema_version=GRAPH_EVENT_SCHEMA,
            payload=checked,
            target_checksum=target_checksum,
            provenance=provenance_for(record, current),
            stream_id=stream_id,
            stream_sequence=stream_sequence,
        )

    def _checkpoint(
        self,
        record: LegacyRecord,
        run_mapping: RunGraphMapping | None,
    ) -> TransformedGraphRecord:
        current = _required_run_mapping(run_mapping)
        _require_gate_evidence(current)
        value = record.value
        _verify_legacy_checkpoint_integrity(record)
        checkpoint_id = required_identifier(
            value.get("checkpoint_id"),
            "checkpoint_id",
        )
        graph_checkpoint_ref = current.checkpoint_ref(checkpoint_id)
        stream_id = _optional_text(value.get("stream_id")) or f"run:{current.run_id}"
        if stream_id != f"run:{current.run_id}":
            raise MigrationContractError(
                QuarantineReasonCode.INCOMPATIBLE_CHECKPOINT,
                "checkpoint stream identity does not match its run",
            )
        last_sequence = _checkpoint_sequence(value)
        if last_sequence is None or last_sequence < 1:
            raise MigrationContractError(
                QuarantineReasonCode.INCOMPATIBLE_CHECKPOINT,
                "checkpoint has no positive durable event boundary",
            )
        last_event_id = _optional_text(value.get("last_event_id"))
        if last_event_id is None:
            metadata = value.get("metadata")
            if isinstance(metadata, Mapping):
                last_event_id = _optional_text(metadata.get("last_event_id"))
        if last_event_id is None:
            raise MigrationContractError(
                QuarantineReasonCode.INCOMPATIBLE_CHECKPOINT,
                "checkpoint has no boundary event identity",
            )
        active_bindings = tuple(
            current.node_binding(required_identifier(item, "current_step_id"))
            for item in sequence(value.get("current_step_ids"), "current_step_ids")
        )
        path_bindings = tuple(
            current.node_binding(required_identifier(item, "path_step_id"))
            for item in sequence(value.get("path", ()), "path")
        )
        step_results = mapping(value.get("step_results", {}), "step_results")
        node_results = {
            current.node_binding(required_identifier(step_id, "step_result_id"))
            .node_instance_id: thaw_json(result)
            for step_id, result in step_results.items()
        }
        created_at = required_text(value.get("created_at"), "created_at")
        aware_datetime(created_at, "created_at")
        historical_output = {
            "read_only": True,
            "resume_allowed": False,
            "snapshot": thaw_json(
                mapping(value.get("data_buffer_snapshot"), "data_buffer_snapshot")
            ),
            "node_results": dict(sorted(node_results.items())),
        }
        payload = {
            "schema_version": GRAPH_CHECKPOINT_SCHEMA,
            "record_role": "migration_history_evidence",
            "checkpoint_id": checkpoint_id,
            "checkpoint_ref": graph_checkpoint_ref,
            "tenant_id": current.tenant_id,
            "run_id": current.run_id,
            "graph_ref": current.graph_ref.to_dict(),
            "active_node_instance_ids": sorted(
                binding.node_instance_id for binding in active_bindings
            ),
            "completed_path_node_instance_ids": [
                binding.node_instance_id for binding in path_bindings
            ],
            "historical_output_evidence": historical_output,
            "historical_output_evidence_ref": checksum_for(historical_output),
            "stream_id": stream_id,
            "last_event_sequence": last_sequence,
            "last_event_id": required_identifier(last_event_id, "last_event_id"),
            "gate_evidence_refs": list(current.gate_evidence_refs),
            "created_at": created_at,
            "history_only": True,
            "resume_allowed": False,
            "replay_validation_allowed": True,
            "replay_execution_allowed": False,
            "publication_allowed": False,
        }
        checked, target_checksum = _attach_record_checksum(payload)
        return TransformedGraphRecord(
            record_kind=record.record_kind,
            run_id=current.run_id,
            target_ref=graph_checkpoint_ref,
            target_schema_version=GRAPH_CHECKPOINT_SCHEMA,
            payload=checked,
            target_checksum=target_checksum,
            provenance=provenance_for(record, current),
            stream_id=stream_id,
            stream_sequence=last_sequence,
        )

    def _replay_bundle(
        self,
        record: LegacyRecord,
        run_mapping: RunGraphMapping | None,
    ) -> TransformedGraphRecord:
        current = _required_run_mapping(run_mapping)
        _require_terminal_evidence(current)
        value = record.value
        integrity = mapping(value.get("integrity"), "integrity")
        if integrity.get("valid") is not True:
            raise MigrationContractError(
                QuarantineReasonCode.MISSING_TERMINAL_EVIDENCE,
                "replay bundle integrity is not explicitly valid",
            )
        manifest = mapping(value.get("manifest"), "manifest")
        status = required_text(manifest.get("status"), "manifest.status")
        if status != current.terminal_status:
            raise MigrationContractError(
                QuarantineReasonCode.MISSING_TERMINAL_EVIDENCE,
                "replay bundle terminal status conflicts with the Graph mapping",
            )
        legacy_checkpoint_id = _first_text(
            manifest,
            "checkpoint_ref",
            "latest_checkpoint_id",
        )
        if legacy_checkpoint_id is None:
            raise MigrationContractError(
                QuarantineReasonCode.MISSING_TERMINAL_EVIDENCE,
                "replay bundle has no checkpoint reference",
            )
        checkpoint_ref = current.checkpoint_ref(legacy_checkpoint_id)
        events = sequence(value.get("events"), "events")
        event_rows = tuple(
            _replay_event_reference(item, current) for item in events
        )
        _validate_contiguous_sequences(
            tuple(item[1] for item in event_rows),
            first_sequence=current.event_first_sequence,
        )
        event_refs = [item[0] for item in sorted(event_rows, key=lambda item: item[1])]
        artifacts = sequence(value.get("artifacts"), "artifacts")
        artifact_refs = sorted(
            f"graph://runs/{current.run_id}/artifacts/"
            + required_identifier(
                mapping(item, "replay artifact").get("artifact_id"),
                "artifact_id",
            )
            for item in artifacts
        )
        routing = mapping(value.get("routing_diagnostics"), "routing_diagnostics")
        target_steps = sequence(routing.get("target_step_ids", ()), "target_step_ids")
        selected_node_ids = [
            current.node_binding(required_identifier(item, "target_step_id")).node_id
            for item in target_steps
        ]
        evaluations = sequence(routing.get("evaluations", ()), "evaluations")
        mapped_evaluations = [
            _map_control_identity(mapping(item, "routing evaluation"), current)
            for item in evaluations
        ]
        decision_projection = {
            "selected_node_ids": selected_node_ids,
            "evaluation_evidence_refs": [
                checksum_for(item) for item in mapped_evaluations
            ],
            "gate_evidence_refs": list(current.gate_evidence_refs),
            "terminal_status": current.terminal_status,
        }
        payload = {
            "schema_version": GRAPH_REPLAY_BUNDLE_SCHEMA,
            "tenant_id": current.tenant_id,
            "run_id": current.run_id,
            "graph_ref": current.graph_ref.to_dict(),
            "terminal_manifest_ref": (
                f"graph://runs/{current.run_id}/terminal-manifest"
            ),
            "checkpoint_ref": checkpoint_ref,
            "event_refs": event_refs,
            "artifact_refs": artifact_refs,
            "decision_projection": decision_projection,
            "decision_projection_checksum": checksum_for(decision_projection),
            "replay_policy": {
                "history_only": True,
                "offline_validation_allowed": True,
                "replay_execution_allowed": False,
                "publication_allowed": False,
                "live_worker_calls": 0,
                "live_side_effect_calls": 0,
                "legacy_executor_calls": 0,
            },
        }
        checked, target_checksum = _attach_record_checksum(payload)
        return TransformedGraphRecord(
            record_kind=record.record_kind,
            run_id=current.run_id,
            target_ref=f"graph://runs/{current.run_id}/replay-bundle",
            target_schema_version=GRAPH_REPLAY_BUNDLE_SCHEMA,
            payload=checked,
            target_checksum=target_checksum,
            provenance=provenance_for(record, current),
        )

    def _artifact_index(
        self,
        record: LegacyRecord,
        run_mapping: RunGraphMapping | None,
    ) -> TransformedGraphRecord:
        current = _required_run_mapping(run_mapping)
        artifact = _artifact_index_payload(record.value, current)
        checked, target_checksum = _attach_record_checksum(
            {
                "schema_version": GRAPH_ARTIFACT_INDEX_SCHEMA,
                "tenant_id": current.tenant_id,
                "run_id": current.run_id,
                "graph_ref": current.graph_ref.to_dict(),
                **artifact,
                "history_only": True,
                "replay_eligible": False,
                "publication_eligible": False,
            }
        )
        return TransformedGraphRecord(
            record_kind=record.record_kind,
            run_id=current.run_id,
            target_ref=(
                f"graph://runs/{current.run_id}/artifacts/{artifact['artifact_id']}"
            ),
            target_schema_version=GRAPH_ARTIFACT_INDEX_SCHEMA,
            payload=checked,
            target_checksum=target_checksum,
            provenance=provenance_for(record, current),
        )

    def _conversation_cursor(
        self,
        record: LegacyRecord,
        run_mapping: RunGraphMapping | None,
    ) -> TransformedGraphRecord:
        value = record.value
        conversation_id = required_identifier(
            value.get("conversation_id"),
            "conversation_id",
        )
        message_offset = _non_negative_int(
            value.get("message_offset"),
            "message_offset",
        )
        updated_at = required_text(value.get("updated_at"), "updated_at")
        aware_datetime(updated_at, "updated_at")
        graph_fields = _cursor_graph_fields(value, run_mapping)
        payload = {
            "schema_version": GRAPH_CONVERSATION_CURSOR_SCHEMA,
            "conversation_id": conversation_id,
            "message_offset": message_offset,
            "message_id": _optional_text(value.get("message_id")),
            **graph_fields,
            "updated_at": updated_at,
            "metadata": _redacted_json(value.get("metadata", {})),
            "history_only": True,
            "resume_allowed": False,
        }
        checked, target_checksum = _attach_record_checksum(payload)
        return TransformedGraphRecord(
            record_kind=record.record_kind,
            run_id=(run_mapping.run_id if run_mapping is not None else None),
            target_ref=f"graph://conversations/{conversation_id}/cursor",
            target_schema_version=GRAPH_CONVERSATION_CURSOR_SCHEMA,
            payload=checked,
            target_checksum=target_checksum,
            provenance=provenance_for(record, run_mapping),
        )

    def _iteration_checkpoint(
        self,
        record: LegacyRecord,
        run_mapping: RunGraphMapping | None,
    ) -> TransformedGraphRecord:
        value = record.value
        conversation_id = required_identifier(
            value.get("conversation_id"),
            "conversation_id",
        )
        agent_id = required_identifier(value.get("agent_id"), "agent_id")
        iteration = _non_negative_int(value.get("iteration"), "iteration")
        updated_at = required_text(value.get("updated_at"), "updated_at")
        aware_datetime(updated_at, "updated_at")
        graph_fields = _cursor_graph_fields(value, run_mapping)
        raw_artifact_ids = sequence(
            value.get("llm_call_artifact_ids", ()),
            "llm_call_artifact_ids",
        )
        artifact_ids = sorted(
            required_identifier(item, "llm_call_artifact_id")
            for item in raw_artifact_ids
        )
        payload = {
            "schema_version": GRAPH_ITERATION_CHECKPOINT_SCHEMA,
            "conversation_id": conversation_id,
            "agent_id": agent_id,
            "iteration": iteration,
            "status": required_text(value.get("status"), "status"),
            "stop_reason": _optional_text(value.get("stop_reason")),
            **graph_fields,
            "message_id": _optional_text(value.get("message_id")),
            "trace_summary": _redacted_json(value.get("trace_summary", {})),
            "diagnostics_summary": _redacted_json(
                value.get("diagnostics_summary", {})
            ),
            "last_tool_observation": _redacted_json(
                value.get("last_tool_observation")
            ),
            "llm_call_artifact_refs": [
                f"graph://runs/{run_mapping.run_id}/artifacts/{artifact_id}"
                if run_mapping is not None
                else f"history-artifact:{artifact_id}"
                for artifact_id in artifact_ids
            ],
            "updated_at": updated_at,
            "metadata": _redacted_json(value.get("metadata", {})),
            "history_only": True,
            "resume_allowed": False,
            "replay_execution_allowed": False,
        }
        checked, target_checksum = _attach_record_checksum(payload)
        return TransformedGraphRecord(
            record_kind=record.record_kind,
            run_id=(run_mapping.run_id if run_mapping is not None else None),
            target_ref=(
                f"graph://conversations/{conversation_id}/iteration-checkpoint"
            ),
            target_schema_version=GRAPH_ITERATION_CHECKPOINT_SCHEMA,
            payload=checked,
            target_checksum=target_checksum,
            provenance=provenance_for(record, run_mapping),
        )


def _event_source_view(value: Mapping[str, Any]) -> dict[str, Any]:
    if "content_checksum" not in value or "business_context" not in value:
        return {
            "event_id": value.get("event_id"),
            "event_type": value.get("event_type"),
            "occurred_at": _first_text(
                value,
                "occurred_at",
                "timestamp",
                "created_at",
            ),
            "run_id": value.get("run_id"),
            "step_id": value.get("step_id"),
            "stream_id": value.get("stream_id"),
            "stream_sequence": value.get("stream_sequence"),
            "tenant_id": value.get("tenant_id"),
            "payload": value.get("payload"),
        }
    _verify_canonical_stored_event(value)
    context = mapping(value.get("business_context"), "business_context")
    payload = value.get("payload")
    if payload is None:
        raise MigrationContractError(
            QuarantineReasonCode.MISSING_TERMINAL_EVIDENCE,
            "detached event payload is not present in the migration snapshot",
        )
    return {
        "event_id": value.get("event_id"),
        "event_type": value.get("event_type"),
        "occurred_at": value.get("occurred_at"),
        "run_id": context.get("run_id"),
        "step_id": context.get("step_id"),
        "stream_id": value.get("stream_id"),
        "stream_sequence": value.get("stream_sequence"),
        "tenant_id": value.get("tenant_id"),
        "payload": payload,
    }


def _verify_canonical_stored_event(value: Mapping[str, Any]) -> None:
    expected_fields = {
        "envelope_schema",
        "event_id",
        "event_type",
        "data_schema",
        "source",
        "subject",
        "occurred_at",
        "stream_id",
        "correlation_id",
        "causation_id",
        "business_context",
        "producer",
        "trace",
        "tenant_id",
        "security_classification",
        "content_type",
        "payload",
        "payload_ref",
        "extensions",
        "content_checksum",
        "observed_at",
        "stream_sequence",
        "record_checksum",
    }
    if set(value) != expected_fields:
        raise MigrationContractError(
            QuarantineReasonCode.AMBIGUOUS_RECORD,
            "canonical stored event has missing or unknown fields",
        )
    aware_datetime(value.get("occurred_at"), "occurred_at")
    aware_datetime(value.get("observed_at"), "observed_at")
    supplied_content_checksum = required_checksum(
        value.get("content_checksum"),
        "content_checksum",
    )
    content_projection = {
        key: thaw_json(item)
        for key, item in value.items()
        if key
        not in {
            "content_checksum",
            "observed_at",
            "stream_sequence",
            "record_checksum",
        }
    }
    if not compare_digest(checksum_for(content_projection), supplied_content_checksum):
        raise MigrationContractError(
            QuarantineReasonCode.CHECKSUM_MISMATCH,
            "canonical event content checksum does not match",
        )
    supplied_record_checksum = required_checksum(
        value.get("record_checksum"),
        "record_checksum",
    )
    record_projection = {
        key: thaw_json(item)
        for key, item in value.items()
        if key != "record_checksum"
    }
    if not compare_digest(checksum_for(record_projection), supplied_record_checksum):
        raise MigrationContractError(
            QuarantineReasonCode.CHECKSUM_MISMATCH,
            "canonical event record checksum does not match",
        )


def record_run_id(record: LegacyRecord) -> str | None:
    value = record.value
    candidates: list[str] = []
    direct = _optional_text(value.get("run_id"))
    if direct is not None:
        candidates.append(direct)
    if record.record_kind is LegacyRecordKind.WORKFLOW_EVENT:
        business_context = value.get("business_context")
        if isinstance(business_context, Mapping):
            contextual = _optional_text(business_context.get("run_id"))
            if contextual is not None:
                candidates.append(contextual)
    if record.record_kind is LegacyRecordKind.REPLAY_BUNDLE:
        raw_manifest = value.get("manifest")
        if isinstance(raw_manifest, Mapping):
            nested = _optional_text(raw_manifest.get("run_id"))
            if nested is not None:
                candidates.append(nested)
    unique = set(candidates)
    if len(unique) > 1:
        raise MigrationContractError(
            QuarantineReasonCode.AMBIGUOUS_RECORD,
            "legacy record contains conflicting run identities",
        )
    if not candidates:
        if record.record_kind in {
            LegacyRecordKind.CONVERSATION_CURSOR,
            LegacyRecordKind.ITERATION_CHECKPOINT,
        }:
            return None
        raise MigrationContractError(
            QuarantineReasonCode.MISSING_GRAPH_IDENTITY,
            "legacy record has no run identity",
        )
    try:
        return required_identifier(candidates[0], "run_id")
    except ValueError as exc:
        raise MigrationContractError(
            QuarantineReasonCode.AMBIGUOUS_RECORD,
            "legacy record run identity is invalid",
        ) from exc


def _validate_mapping_identity(
    value: Mapping[str, Any],
    kind: LegacyRecordKind,
    run_mapping: RunGraphMapping,
) -> None:
    identity = value
    if kind is LegacyRecordKind.REPLAY_BUNDLE:
        identity = mapping(value.get("manifest"), "manifest")
    elif kind is LegacyRecordKind.WORKFLOW_EVENT and isinstance(
        value.get("business_context"),
        Mapping,
    ):
        identity = mapping(value.get("business_context"), "business_context")
    workflow_id = _optional_text(identity.get("workflow_id"))
    workflow_version = _optional_text(identity.get("workflow_version"))
    if workflow_id is not None and workflow_id != run_mapping.legacy_workflow_id:
        raise MigrationContractError(
            QuarantineReasonCode.AMBIGUOUS_RECORD,
            "legacy workflow identity conflicts with the reviewed mapping",
        )
    if (
        workflow_version is not None
        and workflow_version != run_mapping.legacy_workflow_version
    ):
        raise MigrationContractError(
            QuarantineReasonCode.AMBIGUOUS_RECORD,
            "legacy workflow version conflicts with the reviewed mapping",
        )


def _required_run_mapping(value: RunGraphMapping | None) -> RunGraphMapping:
    if value is None:
        raise MigrationContractError(
            QuarantineReasonCode.MISSING_GRAPH_IDENTITY,
            "record requires a reviewed Graph run mapping",
        )
    return value


def _require_gate_evidence(value: RunGraphMapping) -> None:
    if not value.gate_evidence_refs:
        raise MigrationContractError(
            QuarantineReasonCode.MISSING_GATE_EVIDENCE,
            "Graph mapping has no deterministic gate evidence",
        )


def _require_terminal_evidence(value: RunGraphMapping) -> None:
    _require_gate_evidence(value)
    if value.terminal_state_ref is None or not value.terminal_node_ids:
        raise MigrationContractError(
            QuarantineReasonCode.MISSING_TERMINAL_EVIDENCE,
            "Graph mapping has incomplete terminal state evidence",
        )


def _terminal_artifacts(
    value: Mapping[str, Any],
    run_mapping: RunGraphMapping,
) -> tuple[dict[str, Any], ...]:
    raw_artifacts = mapping(value.get("artifacts"), "artifacts")
    declared_paths: dict[str, str] = {}
    reverse_paths: dict[str, str] = {}
    for raw_key, raw_path in raw_artifacts.items():
        key = required_identifier(raw_key, "artifact_key")
        path = _relative_artifact_path(raw_path, "manifest artifact path")
        if path in reverse_paths:
            raise MigrationContractError(
                QuarantineReasonCode.AMBIGUOUS_RECORD,
                "manifest assigns one artifact path to multiple keys",
            )
        declared_paths[key] = path
        reverse_paths[path] = key
    missing_required = _LEGACY_REQUIRED_RUN_ARTIFACT_KEYS - set(declared_paths)
    if missing_required:
        raise MigrationContractError(
            QuarantineReasonCode.MISSING_TERMINAL_EVIDENCE,
            "legacy manifest is missing required owner artifact membership",
        )
    if run_mapping.terminal_status == "succeeded" and "output" not in declared_paths:
        raise MigrationContractError(
            QuarantineReasonCode.MISSING_TERMINAL_EVIDENCE,
            "succeeded legacy manifest has no output artifact",
        )
    indexes_by_path = _artifact_records_by_path(
        sequence(value.get("artifact_index", ()), "artifact_index"),
        reverse_paths=reverse_paths,
        record_name="artifact index",
    )
    refs_by_path = _artifact_records_by_path(
        sequence(value.get("artifact_refs", ()), "artifact_refs"),
        reverse_paths=reverse_paths,
        record_name="artifact ref",
    )
    raw_metadata = value.get("artifact_metadata", {})
    metadata_by_key = mapping(raw_metadata, "artifact_metadata")
    converted: list[dict[str, Any]] = []
    artifact_ids: set[str] = set()
    for artifact_key, path in sorted(declared_paths.items()):
        if artifact_key == "manifest" or path == "manifest.json":
            continue
        item = indexes_by_path.get(path, {})
        ref = refs_by_path.get(path, {})
        metadata_raw = metadata_by_key.get(artifact_key, {})
        metadata = mapping(metadata_raw, f"artifact_metadata.{artifact_key}")
        try:
            artifact_id = _coalesced_identifier(
                (item.get("artifact_id"), ref.get("artifact_id"), artifact_key),
                "artifact_id",
                prefer_last_default=True,
            )
            if artifact_id in artifact_ids:
                raise ValueError("artifact identity is duplicated")
            artifact_ids.add(artifact_id)
            _validate_artifact_run_identity(item, ref, run_mapping=run_mapping)
            step_id = _coalesced_optional_identifier(
                (
                    _first_text(item, "step_id", "created_by_step_id"),
                    _first_text(ref, "step_id", "created_by_step_id"),
                ),
                "artifact step identity",
            ) or run_mapping.default_artifact_step_id
            binding = run_mapping.node_binding(step_id)
            media_type = _coalesced_text(
                (
                    item.get("content_type") or item.get("media_type"),
                    ref.get("content_type") or ref.get("media_type"),
                    metadata.get("content_type") or metadata.get("media_type"),
                ),
                "artifact media_type",
            )
            if _MEDIA_TYPE.fullmatch(media_type) is None:
                raise ValueError("artifact media type is invalid")
            content_checksum = _coalesced_checksum(
                (
                    item.get("checksum") or item.get("content_hash"),
                    ref.get("checksum") or ref.get("content_hash"),
                    metadata.get("checksum") or metadata.get("content_hash"),
                ),
                "artifact checksum",
            )
            byte_size = _coalesced_non_negative_int(
                (
                    item.get("size_bytes"),
                    ref.get("size_bytes"),
                    metadata.get("size_bytes"),
                ),
                "artifact size_bytes",
            )
            required_for_replay = _coalesced_boolean(
                (
                    item.get("required_for_replay"),
                    ref.get("required_for_replay"),
                    metadata.get("required_for_replay"),
                ),
                "required_for_replay",
                default=True,
            )
            required_for_publication = _coalesced_boolean(
                (
                    item.get("required_for_publication"),
                    ref.get("required_for_publication"),
                    metadata.get("required_for_publication"),
                ),
                "required_for_publication",
                default=False,
            )
            converted.append(
                {
                    "artifact_key": artifact_key,
                    "artifact_id": artifact_id,
                    "ref": f"artifact://{run_mapping.run_id}/{artifact_id}",
                    "relative_path": path,
                    "content_checksum": content_checksum,
                    "byte_size": byte_size,
                    "media_type": media_type,
                    "node_id": binding.node_id,
                    "attempt_id": binding.attempt_id,
                    "required_for_replay": required_for_replay,
                    "required_for_publication": required_for_publication,
                    "metadata": {
                        "node_instance_id": binding.node_instance_id,
                        "source_record_kind": "historical_artifact",
                        "eligibility_policy": "explicit_or_conservative_v1",
                    },
                }
            )
        except MigrationContractError:
            raise
        except (TypeError, ValueError) as exc:
            raise MigrationContractError(
                QuarantineReasonCode.MISSING_TERMINAL_EVIDENCE,
                "artifact metadata cannot satisfy Graph terminal membership",
            ) from exc
    return tuple(sorted(converted, key=lambda item: item["artifact_key"]))


def _artifact_records_by_path(
    values: Sequence[Any],
    *,
    reverse_paths: Mapping[str, str],
    record_name: str,
) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    for raw_value in values:
        value = mapping(raw_value, record_name)
        path = _relative_artifact_path(
            value.get("path") or value.get("uri"),
            f"{record_name} path",
        )
        if path not in reverse_paths:
            raise MigrationContractError(
                QuarantineReasonCode.ILLEGAL_ARTIFACT_PATH,
                f"{record_name} path is not contained in manifest membership",
            )
        if path in records:
            raise MigrationContractError(
                QuarantineReasonCode.AMBIGUOUS_RECORD,
                f"manifest artifact path has multiple {record_name} records",
            )
        records[path] = value
    return records


def _terminal_manifest_payload(
    *,
    run_mapping: RunGraphMapping,
    started_at_raw: str,
    completed_at_raw: str,
    graph_checkpoint_ref: str,
    artifacts: tuple[dict[str, Any], ...],
    publication: Mapping[str, Any] | None,
) -> dict[str, Any]:
    started_at = aware_datetime(started_at_raw, "started_at")
    completed_at = aware_datetime(completed_at_raw, "completed_at")
    if completed_at < started_at:
        raise ValueError("terminal completion precedes start")
    publication_payload = (
        _publication_evidence_payload(
            publication,
            started_at_raw=started_at_raw,
            completed_at_raw=completed_at_raw,
        )
        if publication is not None
        else None
    )
    projection = {
        "schema_version": GRAPH_TERMINAL_MANIFEST_SCHEMA,
        "tenant_id": run_mapping.tenant_id,
        "run_id": run_mapping.run_id,
        "graph_id": run_mapping.graph_ref.graph_id,
        "graph_version": run_mapping.graph_ref.graph_version,
        "graph_schema_version": run_mapping.graph_ref.graph_schema_version,
        "compiler_version": run_mapping.graph_ref.compiler_version,
        "normalized_graph_checksum": (
            run_mapping.graph_ref.normalized_graph_checksum
        ),
        "status": run_mapping.terminal_status,
        "started_at": started_at_raw,
        "completed_at": completed_at_raw,
        "terminal_state_ref": required_checksum(
            run_mapping.terminal_state_ref,
            "terminal_state_ref",
        ),
        "checkpoint_ref": required_reference(
            graph_checkpoint_ref,
            "checkpoint_ref",
        ),
        "terminal_node_ids": list(run_mapping.terminal_node_ids),
        "gate_evidence_refs": list(run_mapping.gate_evidence_refs),
        "artifacts": [dict(item) for item in artifacts],
        "publication": publication_payload,
    }
    return {**projection, "manifest_hash": checksum_for(projection)}


def _publication_evidence_payload(
    value: Mapping[str, Any],
    *,
    started_at_raw: str,
    completed_at_raw: str,
) -> dict[str, Any]:
    required = {
        "identity_scope_ref",
        "subject_scope_ref",
        "publication_authority_ref",
        "terminal_side_effect_outcome_ref",
        "artifact_evidence_ref",
        "artifact_member_evidence_ref",
        "committed_at",
        "metadata",
    }
    if set(value) != required:
        raise ValueError("publication evidence has missing or unknown fields")
    result = dict(value)
    for field_name in required - {"committed_at", "metadata"}:
        result[field_name] = required_checksum(result[field_name], field_name)
    committed_at = required_text(result["committed_at"], "publication.committed_at")
    committed = aware_datetime(committed_at, "publication.committed_at")
    if not (
        aware_datetime(started_at_raw, "started_at")
        <= committed
        <= aware_datetime(completed_at_raw, "completed_at")
    ):
        raise ValueError("publication evidence is outside the run interval")
    result["committed_at"] = committed_at
    result["metadata"] = _redacted_json(mapping(result["metadata"], "metadata"))
    return result


def _artifact_index_payload(
    value: Mapping[str, Any],
    run_mapping: RunGraphMapping,
) -> dict[str, Any]:
    artifact_id = required_identifier(value.get("artifact_id"), "artifact_id")
    raw_run_id = required_identifier(value.get("run_id"), "run_id")
    if raw_run_id != run_mapping.run_id:
        raise MigrationContractError(
            QuarantineReasonCode.AMBIGUOUS_RECORD,
            "artifact index run identity conflicts with its Graph mapping",
        )
    step_id = required_identifier(value.get("step_id"), "step_id")
    binding = run_mapping.node_binding(step_id)
    path = _relative_artifact_path(value.get("path"), "artifact path")
    return {
        "artifact_id": artifact_id,
        "artifact_ref": f"artifact://{run_mapping.run_id}/{artifact_id}",
        "artifact_type": required_text(value.get("artifact_type"), "artifact_type"),
        "relative_path": path,
        "content_checksum": normalize_checksum(value.get("checksum"), "checksum"),
        "byte_size": _non_negative_int(value.get("size_bytes"), "size_bytes"),
        "media_type": required_text(value.get("content_type"), "content_type"),
        "node_id": binding.node_id,
        "node_instance_id": binding.node_instance_id,
        "attempt_id": binding.attempt_id,
        "redacted": _required_boolean(value.get("redacted", True), "redacted"),
        "created_at": _validated_optional_datetime(value.get("created_at")),
        "metadata": _redacted_json(value.get("metadata", {})),
    }


def _cursor_graph_fields(
    value: Mapping[str, Any],
    run_mapping: RunGraphMapping | None,
) -> dict[str, Any]:
    raw_run_id = _optional_text(value.get("run_id"))
    raw_step_id = _optional_text(value.get("step_id"))
    raw_checkpoint_id = _optional_text(value.get("workflow_checkpoint_id"))
    if raw_run_id is None:
        if raw_step_id is not None or raw_checkpoint_id is not None:
            raise MigrationContractError(
                QuarantineReasonCode.AMBIGUOUS_RECORD,
                "cursor has node/checkpoint identity without a run identity",
            )
        return {
            "run_id": None,
            "graph_ref": None,
            "node_id": None,
            "node_instance_id": None,
            "graph_checkpoint_ref": None,
        }
    current = _required_run_mapping(run_mapping)
    if raw_step_id is None:
        raise MigrationContractError(
            QuarantineReasonCode.MISSING_GRAPH_IDENTITY,
            "cursor run identity has no node mapping source",
        )
    binding = current.node_binding(raw_step_id)
    checkpoint_ref = (
        current.checkpoint_ref(raw_checkpoint_id)
        if raw_checkpoint_id is not None
        else None
    )
    return {
        "run_id": current.run_id,
        "graph_ref": current.graph_ref.to_dict(),
        "node_id": binding.node_id,
        "node_instance_id": binding.node_instance_id,
        "graph_checkpoint_ref": checkpoint_ref,
    }


def _replay_event_reference(
    raw_event: Any,
    run_mapping: RunGraphMapping,
) -> tuple[str, int]:
    event = mapping(raw_event, "replay event")
    event_id = required_identifier(event.get("event_id"), "event_id")
    run_id = required_identifier(event.get("run_id"), "event.run_id")
    if run_id != run_mapping.run_id:
        raise MigrationContractError(
            QuarantineReasonCode.AMBIGUOUS_RECORD,
            "replay event run identity conflicts with its bundle",
        )
    stream_sequence = _positive_int(
        event.get("stream_sequence"),
        "event.stream_sequence",
    )
    return f"graph://runs/{run_mapping.run_id}/events/{event_id}", stream_sequence


def _validate_contiguous_sequences(
    values: tuple[int, ...],
    *,
    first_sequence: int,
) -> None:
    ordered = sorted(values)
    expected = list(range(first_sequence, first_sequence + len(ordered)))
    if ordered != expected:
        raise MigrationContractError(
            QuarantineReasonCode.EVENT_SEQUENCE_GAP,
            "event sequence is duplicated, missing, or does not start at the reviewed boundary",
        )


def _verify_legacy_checkpoint_integrity(record: LegacyRecord) -> None:
    value = record.value
    raw_checksum = _optional_text(value.get("checksum"))
    is_v2 = record.source.source_schema_version.endswith("/v2")
    if raw_checksum is None:
        if is_v2:
            raise MigrationContractError(
                QuarantineReasonCode.INCOMPATIBLE_CHECKPOINT,
                "durable checkpoint has no embedded checksum",
            )
        return
    if is_v2:
        projection = {key: thaw_json(item) for key, item in value.items() if key != "checksum"}
    else:
        protected: dict[str, Any] = {}
        metadata = value.get("metadata")
        if isinstance(metadata, Mapping) and isinstance(metadata.get("protected"), Mapping):
            protected["protected"] = thaw_json(metadata["protected"])
        projection = {
            "checkpoint_id": value.get("checkpoint_id"),
            "schema_version": value.get("schema_version"),
            "run_id": value.get("run_id"),
            "workflow_id": value.get("workflow_id"),
            "workflow_version": value.get("workflow_version"),
            "current_step_ids": thaw_json(value.get("current_step_ids", ())),
            "data_buffer_snapshot": thaw_json(value.get("data_buffer_snapshot", {})),
            "step_results": thaw_json(value.get("step_results", {})),
            "path": thaw_json(value.get("path", ())),
            "manifest_hash": value.get("manifest_hash"),
            "created_at": value.get("created_at"),
            "metadata": protected,
        }
    expected = sha256(canonical_json_bytes(projection)).hexdigest()
    supplied = raw_checksum.removeprefix("sha256:").lower()
    if len(supplied) != 64 or not compare_digest(supplied, expected):
        raise MigrationContractError(
            QuarantineReasonCode.CHECKSUM_MISMATCH,
            "checkpoint embedded checksum does not match its canonical content",
        )


def _checkpoint_sequence(value: Mapping[str, Any]) -> int | None:
    raw = value.get("last_durable_stream_sequence")
    if raw is None:
        raw = value.get("event_offset")
    if raw is None:
        metadata = value.get("metadata")
        if isinstance(metadata, Mapping):
            raw = metadata.get("event_offset")
    if raw is None:
        return None
    return _non_negative_int(raw, "checkpoint event sequence")


def _map_control_identity(value: Any, run_mapping: RunGraphMapping) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"workflow_id", "workflow_version", "workflow_ref"}:
                continue
            if key == "step_id" and item is not None:
                binding = run_mapping.node_binding(required_identifier(item, key))
                result["node_id"] = binding.node_id
                result["node_instance_id"] = binding.node_instance_id
                continue
            if key == "target_step_id" and item is not None:
                result["target_node_id"] = run_mapping.node_binding(
                    required_identifier(item, key)
                ).node_id
                continue
            if key in {"step_ids", "current_step_ids", "target_step_ids"}:
                result[key.replace("step", "node")] = [
                    run_mapping.node_binding(required_identifier(child, key)).node_id
                    for child in sequence(item, key)
                ]
                continue
            result[str(key)] = _map_control_identity(item, run_mapping)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_map_control_identity(item, run_mapping) for item in value]
    return value


def _attach_record_checksum(payload: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    projection = thaw_json(payload)
    checksum = checksum_for(projection)
    return {**projection, "record_checksum": checksum}, checksum


def _relative_artifact_path(value: Any, field_name: str) -> str:
    try:
        raw = required_text(value, field_name)
        normalized = raw.replace("\\", "/")
        windows = PureWindowsPath(raw)
        posix = PurePosixPath(normalized)
        if windows.is_absolute() or windows.drive or posix.is_absolute():
            raise ValueError("path must be relative")
        if not posix.parts or any(part in {"", ".", ".."} for part in posix.parts):
            raise ValueError("path contains an unsafe component")
        for part in posix.parts:
            if any(character in _WINDOWS_RESERVED_CHARACTERS for character in part):
                raise ValueError("path contains a reserved character")
            if part.endswith((".", " ")) or part.upper() in _DOS_DEVICE_NAMES:
                raise ValueError("path contains a reserved segment")
        return posix.as_posix()
    except (TypeError, ValueError) as exc:
        raise MigrationContractError(
            QuarantineReasonCode.ILLEGAL_ARTIFACT_PATH,
            "artifact path is absolute, traversing, linked, or ambiguous",
        ) from exc


def _redacted_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            lowered = key.lower()
            if lowered in _SENSITIVE_KEYS or lowered.endswith(_SENSITIVE_SUFFIXES):
                result[key] = "[REDACTED]"
            else:
                result[key] = _redacted_json(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_redacted_json(item) for item in value]
    return value


def _first_text(value: Mapping[str, Any], *field_names: str) -> str | None:
    for field_name in field_names:
        result = _optional_text(value.get(field_name))
        if result is not None:
            return result
    return None


def _coalesced_identifier(
    values: Sequence[Any],
    field_name: str,
    *,
    prefer_last_default: bool = False,
) -> str:
    candidates = tuple(values)
    if prefer_last_default:
        explicit = tuple(item for item in candidates[:-1] if item is not None)
        candidates = explicit or candidates[-1:]
    result = _coalesced_values(
        candidates,
        field_name,
        normalizer=required_identifier,
    )
    if result is None:
        raise ValueError(f"{field_name} is required")
    return result


def _coalesced_optional_identifier(
    values: Sequence[Any],
    field_name: str,
) -> str | None:
    return _coalesced_values(
        values,
        field_name,
        normalizer=required_identifier,
    )


def _coalesced_text(values: Sequence[Any], field_name: str) -> str:
    result = _coalesced_values(values, field_name, normalizer=required_text)
    if result is None:
        raise ValueError(f"{field_name} is required")
    return result


def _coalesced_checksum(values: Sequence[Any], field_name: str) -> str:
    normalized = tuple(
        normalize_checksum(item, field_name)
        for item in values
        if item is not None
    )
    if not normalized:
        raise ValueError(f"{field_name} is required")
    if len(set(normalized)) != 1:
        raise MigrationContractError(
            QuarantineReasonCode.CHECKSUM_MISMATCH,
            f"{field_name} conflicts across manifest evidence",
        )
    return normalized[0]


def _coalesced_non_negative_int(
    values: Sequence[Any],
    field_name: str,
) -> int:
    normalized = tuple(
        _non_negative_int(item, field_name)
        for item in values
        if item is not None
    )
    if not normalized:
        raise ValueError(f"{field_name} is required")
    if len(set(normalized)) != 1:
        raise MigrationContractError(
            QuarantineReasonCode.AMBIGUOUS_RECORD,
            f"{field_name} conflicts across manifest evidence",
        )
    return normalized[0]


def _coalesced_boolean(
    values: Sequence[Any],
    field_name: str,
    *,
    default: bool,
) -> bool:
    normalized: list[bool] = []
    for item in values:
        if item is None:
            continue
        if not isinstance(item, bool):
            raise ValueError(f"{field_name} must be a boolean")
        normalized.append(item)
    if not normalized:
        return default
    if len(set(normalized)) != 1:
        raise MigrationContractError(
            QuarantineReasonCode.AMBIGUOUS_RECORD,
            f"{field_name} conflicts across manifest evidence",
        )
    return normalized[0]


def _coalesced_values(
    values: Sequence[Any],
    field_name: str,
    *,
    normalizer: Any,
) -> Any:
    normalized = tuple(
        normalizer(item, field_name)
        for item in values
        if item is not None
    )
    if not normalized:
        return None
    if len(set(normalized)) != 1:
        raise MigrationContractError(
            QuarantineReasonCode.AMBIGUOUS_RECORD,
            f"{field_name} conflicts across manifest evidence",
        )
    return normalized[0]


def _validate_artifact_run_identity(
    *values: Mapping[str, Any],
    run_mapping: RunGraphMapping,
) -> None:
    run_ids = tuple(
        required_identifier(raw_run_id, "artifact run_id")
        for value in values
        if (raw_run_id := value.get("run_id")) is not None
    )
    if any(run_id != run_mapping.run_id for run_id in run_ids):
        raise MigrationContractError(
            QuarantineReasonCode.AMBIGUOUS_RECORD,
            "artifact run identity conflicts with its manifest",
        )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return required_text(value, "optional_text")


def _positive_int(value: Any, field_name: str) -> int:
    result = _non_negative_int(value, field_name)
    if result < 1:
        raise ValueError(f"{field_name} must be positive")
    return result


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _required_boolean(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _validated_optional_datetime(value: Any) -> str | None:
    if value is None:
        return None
    text = required_text(value, "created_at")
    aware_datetime(text, "created_at")
    return text


__all__ = ["GraphHistoryTransformer", "record_run_id"]
