from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
import re

import pytest

from framework.events import (
    Event,
    EventEnvelope,
    TraceContext,
    TraceEvent,
    TraceRedactionPolicy,
    trace_fields,
)
from framework.events.trace import REDACTED_TRACE_VALUE, redact_trace_payload


def test_new_trace_context_uses_nonzero_w3c_identifiers() -> None:
    root = TraceContext.root(run_id="run-w3c", workflow_id="wf-w3c")
    child = root.child(step_id="step-1")

    assert re.fullmatch(r"[0-9a-f]{32}", root.trace_id)
    assert re.fullmatch(r"[0-9a-f]{16}", root.span_id)
    assert int(root.trace_id, 16) != 0
    assert int(root.span_id, 16) != 0
    assert re.fullmatch(r"[0-9a-f]{16}", child.span_id)
    assert int(child.span_id, 16) != 0
    assert child.trace_id == root.trace_id
    assert child.parent_span_id == root.span_id
    assert root.is_injectable is True
    assert child.is_injectable is True


def test_trace_context_root_child_and_round_trip() -> None:
    root = TraceContext.root(
        run_id="run-1",
        workflow_id="wf-1",
        trace_id="trace-1",
        span_id="workflow:run-1",
        metadata={"api_key": "secret", "safe": "visible"},
    )
    child = root.child(span_id="step:s1", step_id="s1")

    assert child.trace_id == "trace-1"
    assert child.parent_span_id == "workflow:run-1"
    assert child.step_id == "s1"
    assert child.to_dict()["metadata"]["api_key"] == "[REDACTED]"
    assert TraceContext.from_dict(child.to_dict()).span_id == "step:s1"
    assert root.has_legacy_identifiers is True
    assert root.is_injectable is False


def test_trace_context_round_trip_preserves_w3c_state() -> None:
    context = TraceContext.root(
        run_id="run-remote",
        workflow_id="wf-remote",
        trace_id="1" * 32,
        span_id="2" * 16,
        trace_flags="01",
        tracestate="vendor=value",
        is_remote=True,
    )

    restored = TraceContext.from_dict(context.to_dict())

    assert restored == context
    assert restored.trace_flags == "01"
    assert restored.tracestate == "vendor=value"
    assert restored.is_remote is True


def test_trace_context_metadata_is_a_deep_immutable_snapshot() -> None:
    source = {
        "nested": {"values": ["accepted"]},
        "api_key": "raw-secret",
    }
    context = TraceContext.root(run_id="run-immutable", metadata=source)
    before = context.to_dict()

    source["nested"]["values"].append("mutated")
    source["api_key"] = "changed-secret"

    assert context.to_dict() == before
    assert context.to_dict(redact=False)["metadata"]["nested"] == {
        "values": ["accepted"]
    }
    with pytest.raises(TypeError):
        context.metadata["nested"]["values"][0] = "changed"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        context.metadata = {}  # type: ignore[misc]


def test_trace_fields_preserves_all_supported_business_ids() -> None:
    context = TraceContext.root(
        run_id="run-fields",
        workflow_id="wf-fields",
        trace_id="1" * 32,
        span_id="2" * 16,
    ).child(
        step_id="step-fields",
        agent_id="agent-fields",
        tool_call_id="tool-fields",
        memory_operation_id="memory-fields",
        artifact_id="artifact-fields",
    )

    fields = trace_fields(context)

    assert fields["run_id"] == "run-fields"
    assert fields["workflow_id"] == "wf-fields"
    assert fields["step_id"] == "step-fields"
    assert fields["agent_id"] == "agent-fields"
    assert fields["tool_call_id"] == "tool-fields"
    assert fields["memory_operation_id"] == "memory-fields"
    assert fields["artifact_id"] == "artifact-fields"
    assert fields["trace_flags"] == "00"
    assert fields["is_remote"] is False


def test_trace_event_round_trip_and_redaction() -> None:
    context = TraceContext.root(run_id="run-1", trace_id="trace-1", span_id="root")
    event = TraceEvent(
        event_id="evt-1",
        event_type="step_started",
        timestamp=datetime(2026, 5, 20, 1, 2, tzinfo=UTC),
        context=context,
        component="workflow",
        operation="step",
        status="started",
        payload={"token": "secret"},
    )

    payload = event.to_dict()
    restored = TraceEvent.from_dict(payload)

    assert payload["payload"]["token"] == "[REDACTED]"
    assert restored.context.trace_id == "trace-1"
    assert restored.timestamp == datetime(2026, 5, 20, 1, 2, tzinfo=UTC)


def test_event_envelope_round_trip_preserves_trace_fields() -> None:
    context = TraceContext.root(
        run_id="run-1",
        workflow_id="wf-1",
        trace_id="trace-1",
        span_id="root",
    ).child(span_id="step:s1", step_id="s1")
    event = Event(
        "step_started",
        run_id=context.run_id,
        trace_id=context.trace_id,
        span_id=context.span_id,
        parent_span_id=context.parent_span_id,
        workflow_id=context.workflow_id,
        step_id=context.step_id,
        component="workflow",
    )
    envelope = EventEnvelope(event=event, event_id="evt-1")

    assert envelope.to_dict()["trace_id"] == "trace-1"
    assert EventEnvelope.from_dict(envelope.to_dict()).span_id == "step:s1"
    assert envelope.to_dict()["parent_span_id"] == "root"
    assert EventEnvelope.from_dict(envelope.to_dict()).trace_id == "trace-1"


def test_redact_trace_payload_redacts_secret_like_keys() -> None:
    payload = {"nested": {"authorization": "Bearer secret"}, "safe": "ok"}

    assert redact_trace_payload(payload) == {
        "nested": {"authorization": "[REDACTED]"},
        "safe": "ok",
    }


def test_trace_redaction_uses_exact_normalized_credential_keys() -> None:
    payload = {
        "apiKey": "api-secret",
        "x-api-key": "header-secret",
        "accessToken": "access-secret",
        "refresh_token": "refresh-secret",
        "client_secret": "client-secret",
        "aws_secret_access_key": "aws-secret",
        "password": "password-secret",
        "secretary": "visible",
        "token_count": 12,
        "authorization_status": "approved",
    }

    projected = redact_trace_payload(payload)

    for field_name in (
        "apiKey",
        "x-api-key",
        "accessToken",
        "refresh_token",
        "client_secret",
        "aws_secret_access_key",
        "password",
    ):
        assert projected[field_name] == REDACTED_TRACE_VALUE
    assert projected["secretary"] == "visible"
    assert projected["token_count"] == 12
    assert projected["authorization_status"] == "approved"


def test_trace_redaction_policy_can_classify_and_allow_exact_schema_paths() -> None:
    policy = TraceRedactionPolicy(
        schema_id="newsroom.test-trace/v1",
        sensitive_paths=frozenset({"/private_note"}),
        allowed_paths=frozenset({"/token"}),
    )

    projected = redact_trace_payload(
        {
            "private_note": "classified-by-schema",
            "token": "registered-business-token",
            "nested": {"password": "credential"},
        },
        policy=policy,
    )

    assert projected == {
        "private_note": REDACTED_TRACE_VALUE,
        "token": "registered-business-token",
        "nested": {"password": REDACTED_TRACE_VALUE},
    }
