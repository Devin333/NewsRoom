from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from framework.artifacts.paths import validate_artifact_path_segment
from framework.events.canonical import (
    BusinessContext,
    ProducerIdentity,
    StoredEvent,
    checksum_for,
    thaw_canonical_json,
)
from framework.events.ports import EventRuntimePort
from framework.events.runtime.publisher import EventPublishRequest
from framework.events.schema.security import SecurityClassification
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.event import HarnessEvent
from framework.harness.control_plane.event_log import (
    HarnessEventLogEntry,
    event_log_entry_from_stored_event,
)
from framework.shared.time import parse_datetime


HARNESS_DATA_SCHEMA = "newsroom.harness-event/v1"
HARNESS_EVENT_SOURCE = "io.newsroom.harness.control-plane"
HARNESS_SAFE_PROJECTION = "harness-safe-summary/v1"
_LEGACY_TRACE_ID_PATTERN = re.compile(
    r"(?:[0-9a-fA-F]{16}|[0-9a-fA-F]{32}|"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\Z"
)
_HARNESS_STATUS_VALUES = frozenset(
    {
        "blocked",
        "cancelled",
        "created",
        "executing",
        "failed",
        "halted",
        "pending",
        "plan_verified",
        "planning",
        "replanning",
        "retrying",
        "running",
        "skipped",
        "succeeded",
        "verifying",
        "waiting_approval",
    }
)
_HARNESS_TRANSITION_KINDS = frozenset(
    {
        "approval_cancel",
        "approval_resume",
        "budget_exhaustion",
        "cancel",
        "execute_entry",
        "failure",
        "halt",
        "plan_entry",
        "plan_exit",
        "replan",
        "retry",
        "retry_execute_entry",
        "route_to_repair",
        "route_to_step",
        "run_start",
        "step_success",
        "success",
        "verify_complete",
        "verify_entry",
        "wait",
        "wait_for_approval",
    }
)


@dataclass(frozen=True, slots=True)
class HarnessEventCanonicalAdapter:
    """Maps typed Harness facts to and from the canonical durable boundary."""

    producer: ProducerIdentity = ProducerIdentity(
        component="framework.harness.control_plane",
        version="1",
    )
    tenant_id: str | None = None
    security_classification: SecurityClassification | str = SecurityClassification.INTERNAL

    def to_publish_request(self, event: HarnessEvent) -> EventPublishRequest:
        if not isinstance(event, HarnessEvent):
            raise TypeError("event must be HarnessEvent")
        run_id = validate_artifact_path_segment(event.run_id, field="run_id")
        _validate_payload_context(
            event.payload,
            run_id=run_id,
            step_id=event.step_id,
            event_type=event.event_type.value,
            occurred_at=event.occurred_at,
        )
        canonical_payload = _canonical_harness_payload(event)
        harness_extension: dict[str, Any] = {
            "metadata": _harness_metadata_projection(event.metadata)
        }
        if event.trace_id is not None:
            # A legacy trace id without a span id is correlation data only and
            # must never be injected as canonical W3C trace context.
            harness_extension["legacy_trace_id"] = _legacy_trace_id(event.trace_id)
        return EventPublishRequest(
            event_id=str(event.event_id),
            event_type=event.event_type.value,
            data_schema=HARNESS_DATA_SCHEMA,
            source=HARNESS_EVENT_SOURCE,
            subject=event.step_id or run_id,
            occurred_at=event.occurred_at,
            stream_id=f"run:{run_id}",
            correlation_id=run_id,
            business_context=BusinessContext(
                run_id=run_id,
                workflow_id=_optional_metadata_text(event.metadata, "workflow_id"),
                step_id=event.step_id,
            ),
            producer=self.producer,
            tenant_id=self.tenant_id,
            security_classification=self.security_classification,
            payload=canonical_payload,
            extensions={"harness": harness_extension},
        )

    def from_stored_event(self, event: StoredEvent) -> HarnessEvent:
        _validate_stored_harness_event(event)
        payload = thaw_canonical_json(event.payload or {})
        if not isinstance(payload, dict):
            raise HarnessValidationError("stored Harness payload must be an object")
        run_id = event.business_context.run_id
        if run_id is None:
            raise HarnessValidationError("stored Harness event requires business_context.run_id")
        step_id = event.business_context.step_id
        _validate_payload_context(
            payload,
            run_id=run_id,
            step_id=step_id,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
        )
        extension = thaw_canonical_json(event.extensions.get("harness", {}))
        if not isinstance(extension, dict):
            raise HarnessValidationError("stored Harness extension must be an object")
        metadata = extension.get("metadata", {})
        if not isinstance(metadata, dict):
            raise HarnessValidationError("stored Harness metadata must be an object")
        legacy_trace_id = extension.get("legacy_trace_id")
        return HarnessEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            run_id=run_id,
            step_id=step_id,
            payload=payload,
            metadata=metadata,
            occurred_at=event.occurred_at,
            trace_id=str(legacy_trace_id) if legacy_trace_id is not None else None,
        )


class DurableHarnessEventPort:
    """Harness sink whose projection advances only after canonical commit."""

    def __init__(
        self,
        runtime: EventRuntimePort,
        *,
        adapter: HarnessEventCanonicalAdapter | None = None,
    ) -> None:
        if runtime is None:
            raise HarnessValidationError("event runtime is required")
        self._runtime = runtime
        self._adapter = adapter or HarnessEventCanonicalAdapter()
        self.events: list[HarnessEvent] = []
        self.event_log_entries: list[HarnessEventLogEntry] = []

    def record(self, event: HarnessEvent) -> HarnessEvent:
        request = self._adapter.to_publish_request(event)
        stored = self._runtime.publish(request)
        _validate_commit_result(stored, request)
        projected = self._adapter.from_stored_event(stored)
        log_entry = event_log_entry_from_stored_event(stored)
        # These are compatibility/read projections. They intentionally advance
        # only after EventRuntime.publish() returned a committed StoredEvent.
        self.events.append(projected)
        self.event_log_entries.append(log_entry)
        return projected

    def entries_for_run(self, run_id: str) -> tuple[HarnessEventLogEntry, ...]:
        return tuple(entry for entry in self.event_log_entries if entry.run_id == run_id)


def _validate_commit_result(stored: StoredEvent, request: EventPublishRequest) -> None:
    if not isinstance(stored, StoredEvent):
        raise HarnessValidationError("event runtime must return StoredEvent after commit")
    stored.verify_integrity()
    if stored.event_id != request.event_id:
        raise HarnessValidationError("event runtime returned a different Harness event_id")
    if stored.event_type != request.event_type or stored.data_schema != request.data_schema:
        raise HarnessValidationError("event runtime returned a different Harness schema identity")
    if stored.stream_id != request.stream_id:
        raise HarnessValidationError("event runtime returned a different Harness stream")


def _validate_stored_harness_event(event: StoredEvent) -> None:
    if not isinstance(event, StoredEvent):
        raise TypeError("event must be StoredEvent")
    event.verify_integrity()
    if event.data_schema != HARNESS_DATA_SCHEMA:
        raise HarnessValidationError("stored event is not a Harness event schema")
    if event.source != HARNESS_EVENT_SOURCE:
        raise HarnessValidationError("stored Harness event has an unexpected producer source")


def _validate_payload_context(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    step_id: str | None,
    event_type: str,
    occurred_at: Any,
) -> None:
    payload_run_id = payload.get("run_id")
    if payload_run_id is not None and payload_run_id != run_id:
        raise HarnessValidationError("Harness payload run_id conflicts with canonical business context")
    payload_step_id = payload.get("step_id")
    if payload_step_id is not None and (
        step_id is None or payload_step_id != step_id
    ):
        raise HarnessValidationError("Harness payload step_id conflicts with canonical business context")
    duplicate_time_field = {
        "phase_recorded": "occurred_at",
        "decision_recorded": "decided_at",
        "step_state_changed": "updated_at",
    }.get(event_type)
    if duplicate_time_field is None or duplicate_time_field not in payload:
        return
    try:
        canonical_time = parse_datetime(occurred_at)
        duplicate_time = parse_datetime(payload.get(duplicate_time_field))
    except (TypeError, ValueError, OverflowError):
        canonical_time = None
        duplicate_time = None
    if canonical_time is None or duplicate_time is None or duplicate_time != canonical_time:
        raise HarnessValidationError(
            f"Harness payload {duplicate_time_field} conflicts with canonical occurred_at"
        )


def _optional_metadata_text(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _canonical_harness_payload(event: HarnessEvent) -> dict[str, Any]:
    payload = thaw_canonical_json(event.payload)
    if not isinstance(payload, dict):
        raise HarnessValidationError("Harness payload must be an object")
    # These values are authoritative in EventPublishRequest/business_context.
    # Equal legacy duplicates are accepted by _validate_payload_context() above,
    # then removed so a new stored envelope has only one canonical owner.
    payload.pop("run_id", None)
    payload.pop("step_id", None)
    payload.pop("occurred_at", None)
    payload.pop("decided_at", None)
    payload["projection_schema"] = HARNESS_SAFE_PROJECTION
    event_type = event.event_type.value
    if event_type == "phase_recorded":
        payload["input_ref_checksums"] = _reference_checksums(
            payload.pop("input_refs", ()),
            field_name="input_refs",
        )
        payload["output_ref_checksums"] = _reference_checksums(
            payload.pop("output_refs", ()),
            field_name="output_refs",
        )
        if "gate_results" in payload:
            payload["gate_results"] = _gate_result_projections(
                payload["gate_results"]
            )
        return payload
    if event_type == "decision_recorded":
        decision_payload = payload.pop("payload", {})
        payload["decision_payload"] = _decision_payload_projection(decision_payload)
        reason = payload.pop("reason", None)
        if reason is not None:
            payload["reason_ref"] = _value_ref(reason)
        return payload
    if event_type == "worker_called":
        inputs = payload.pop("inputs", {})
        metadata = payload.pop("metadata", {})
        payload["input_ref"] = _value_ref(inputs)
        payload["input_count"] = len(inputs) if isinstance(inputs, Mapping) else 0
        payload["metadata_ref"] = _value_ref(metadata)
        return payload
    if event_type == "worker_result_recorded":
        output = payload.pop("output", {})
        artifacts = payload.pop("artifacts", ())
        diagnostics = payload.pop("diagnostics", {})
        metrics = payload.pop("metrics", {})
        error = payload.pop("error", None)
        payload["output_ref"] = _value_ref(output)
        artifact_refs = _reference_checksums(artifacts, field_name="artifacts")
        payload["artifact_count"] = len(artifact_refs)
        payload["artifact_ref_checksums"] = artifact_refs
        payload["diagnostics_ref"] = _value_ref(diagnostics)
        payload["metric_count"] = len(metrics) if isinstance(metrics, Mapping) else 0
        if error is not None:
            payload["error_ref"] = _value_ref(error)
        return payload
    if event_type == "gate_evaluated":
        details = payload.pop("details", {})
        payload["details_ref"] = _value_ref(details)
        reason = payload.pop("reason", None)
        if reason is not None:
            payload["reason_ref"] = _value_ref(reason)
        return payload
    if event_type == "step_state_changed":
        payload.pop("updated_at", None)
        output_ref = payload.pop("output_ref", None)
        if output_ref is not None:
            payload["output_key_ref"] = _value_ref(output_ref)
        metadata = payload.pop("metadata", {})
        payload["metadata"] = _step_metadata_projection(metadata)
        error = payload.pop("error", None)
        if error is not None:
            payload["error_ref"] = _value_ref(error)
        return payload
    return payload


def _decision_payload_projection(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"value_ref": _value_ref(value)}
    projected: dict[str, Any] = {}
    for key in (
        "approval_outcome",
        "backoff_seconds",
        "max_turns",
        "turn_count",
    ):
        if key in value:
            projected[key] = thaw_canonical_json(value[key])
    gate_results = value.get("gate_results")
    if gate_results is not None:
        projected["gate_results"] = _gate_result_projections(gate_results)
    if "quality_verdict" in value:
        projected["quality_verdict_ref"] = _value_ref(value.get("quality_verdict"))
    worker_value = value.get("worker_result", value)
    if any(key in value for key in ("worker_result", "status", "output", "diagnostics", "metrics", "error")):
        projected["worker_result_ref"] = _value_ref(worker_value)
    projected["decision_payload_ref"] = _value_ref(value)
    return projected


def _gate_result_projections(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list | tuple):
        raise HarnessValidationError("Harness gate_results must be an array")
    projected: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise HarnessValidationError("Harness gate result must be an object")
        gate = item.get("gate")
        passed = item.get("passed")
        if not isinstance(gate, str) or not gate.strip():
            raise HarnessValidationError("Harness gate result requires gate")
        if not isinstance(passed, bool):
            raise HarnessValidationError("Harness gate result passed must be a boolean")
        projected.append(
            {
                "gate": gate.strip(),
                "passed": passed,
                "result_ref": _value_ref(item),
            }
        )
    return projected


def _step_metadata_projection(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"metadata_ref": _value_ref(value)}
    projected = {
        str(key): thaw_canonical_json(item)
        for key, item in value.items()
        if key in {"approval_granted", "rerouted"}
    }
    if "worker_result" in value:
        projected["worker_result_ref"] = _value_ref(value["worker_result"])
    if value:
        projected["metadata_ref"] = _value_ref(value)
    return projected


def _harness_metadata_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    omitted: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"phase_index", "replan_count", "turn_count", "worker_call_count"}:
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise HarnessValidationError(
                    f"Harness metadata {key} must be a non-negative integer"
                )
            projected[key] = item
        elif key in {"status_after", "status_before"}:
            if item not in _HARNESS_STATUS_VALUES:
                raise HarnessValidationError(f"Harness metadata {key} is invalid")
            projected[key] = item
        elif key == "transition_kind":
            if item not in _HARNESS_TRANSITION_KINDS:
                raise HarnessValidationError("Harness metadata transition_kind is invalid")
            projected[key] = item
        else:
            omitted[str(key)] = item
    if omitted:
        projected["omitted_metadata_count"] = len(omitted)
        projected["omitted_metadata_ref"] = _value_ref(omitted)
    return projected


def _reference_checksums(value: Any, *, field_name: str) -> list[str]:
    if not isinstance(value, list | tuple):
        raise HarnessValidationError(f"Harness {field_name} must be an array")
    return [_value_ref(item) for item in value]


def _legacy_trace_id(value: Any) -> str:
    if not isinstance(value, str):
        raise HarnessValidationError("legacy Harness trace_id must be a string")
    normalized = value.strip()
    if _LEGACY_TRACE_ID_PATTERN.fullmatch(normalized) is None:
        raise HarnessValidationError("legacy Harness trace_id has an unsafe format")
    return normalized.lower()


def _value_ref(value: Any) -> str:
    return checksum_for(thaw_canonical_json(value))


__all__ = [
    "DurableHarnessEventPort",
    "HARNESS_DATA_SCHEMA",
    "HARNESS_EVENT_SOURCE",
    "HARNESS_SAFE_PROJECTION",
    "HarnessEventCanonicalAdapter",
]
