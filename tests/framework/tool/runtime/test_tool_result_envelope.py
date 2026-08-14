from __future__ import annotations

import base64
import time
from dataclasses import replace

import pytest

from framework.events.canonical import thaw_canonical_json
from framework.shared.json import stable_json_dumps
from framework.tool import (
    ToolCall,
    ToolDefinition,
    ToolDefinitionError,
    ToolExecutor,
    ToolPolicy,
    ToolResultEnvelope,
    ToolResultPersistenceContract,
    ToolRuntimeError,
    ToolStatus,
)
from framework.tool.registry import ToolRegistry


def _execute(
    definition: ToolDefinition,
    executor_fn,
    *,
    policy: ToolPolicy | None = None,
    call_id: str = "call-result-1",
):
    registry = ToolRegistry()
    registry.register(definition, executor_fn)
    executor = ToolExecutor(registry, defer_result_persistence=True)
    observation = executor.execute(
        ToolCall(tool_name=definition.name, call_id=call_id),
        policy
        or ToolPolicy(
            allowed_tools=[definition.name],
            require_explicit_allowlist=True,
            require_approval_for_side_effects=False,
        ),
    )
    return observation, executor


def test_result_persistence_contract_is_strict_and_round_trips() -> None:
    contract = ToolResultPersistenceContract(
        control_fields=("next_cursor", "has_more"),
        artifact_class="intermediate",
        retention_class="run",
        sensitivity="internal",
        context_policy="sample_allowed",
    )
    definition = ToolDefinition(
        name="sample.search",
        output_schema={
            "type": "object",
            "properties": {
                "items": {"type": "array"},
                "next_cursor": {"type": ["string", "null"]},
                "has_more": {"type": "boolean"},
            },
            "required": ["items", "next_cursor", "has_more"],
        },
        result_persistence=contract,
    )

    restored = ToolDefinition.from_dict(definition.to_dict())

    assert restored.result_persistence == contract
    with pytest.raises(ToolDefinitionError, match="unknown fields"):
        ToolResultPersistenceContract.from_any({"unknown": True})
    with pytest.raises(ToolDefinitionError, match="invalid field"):
        ToolResultPersistenceContract(control_fields=("route",))
    with pytest.raises(ToolDefinitionError, match="invalid field"):
        ToolResultPersistenceContract(control_fields=("access_token",))
    with pytest.raises(ToolDefinitionError, match="invalid field"):
        ToolResultPersistenceContract(control_fields=("response_checksum",))
    with pytest.raises(ToolDefinitionError, match="invalid field"):
        ToolResultPersistenceContract(control_fields=("retry_count",))
    with pytest.raises(ToolDefinitionError, match="restricted sensitivity"):
        ToolResultPersistenceContract(media_type="application/pdf")


def test_large_paginated_json_separates_raw_response_and_bounded_controls() -> None:
    secret = "sk-super-secret-material"
    definition = ToolDefinition(
        name="sample.search",
        output_schema={
            "type": "object",
            "properties": {
                "items": {"type": "array"},
                "next_cursor": {"type": "string"},
                "has_more": {"type": "boolean"},
                "api_token": {"type": "string"},
            },
            "required": ["items", "next_cursor", "has_more", "api_token"],
        },
        max_result_bytes=200_000,
        result_persistence={
            "control_fields": ["next_cursor", "has_more"],
        },
    )
    observation, executor = _execute(
        definition,
        lambda _args: {
            "items": [{"id": index, "body": "x" * 80} for index in range(600)],
            "next_cursor": "cursor-2",
            "has_more": True,
            "api_token": secret,
        },
    )

    envelope = ToolResultEnvelope.from_observation(observation, definition)
    rendered = stable_json_dumps(envelope.to_dict())
    events = stable_json_dumps([event.to_dict() for event in executor.list_events()])

    assert envelope.response_bytes > 32 * 1024
    assert envelope.control_projection["next_cursor"] == "cursor-2"
    assert envelope.control_projection["has_more"] is True
    assert "items" not in envelope.control_projection
    assert "api_token" not in thaw_canonical_json(envelope.response)
    assert secret not in rendered
    assert secret not in events
    assert "\"items\"" not in events
    assert ToolResultEnvelope.from_dict(envelope.to_dict()).to_dict() == envelope.to_dict()


def test_binary_response_preserves_exact_bytes_and_base64_round_trip() -> None:
    payload = b"\x00\xffPDF\r\n" + bytes(range(128))
    definition = ToolDefinition(
        name="sample.pdf",
        output_schema=None,
        result_persistence={
            "media_type": "application/pdf",
            "sensitivity": "restricted",
            "required_for_replay": True,
        },
    )
    observation, _executor = _execute(definition, lambda _args: payload)

    envelope = ToolResultEnvelope.from_observation(observation, definition)
    serialized = envelope.to_dict()
    restored = ToolResultEnvelope.from_dict(serialized)

    assert envelope.response == payload
    assert restored.response == payload
    assert serialized["response_encoding"] == "base64"
    assert base64.b64decode(serialized["response"], validate=True) == payload
    assert observation.result.to_dict()["output_encoding"] == "base64"


def test_unauthorized_result_cannot_be_materialized() -> None:
    definition = ToolDefinition(name="sample.private")
    observation, _executor = _execute(
        definition,
        lambda _args: {"ok": True},
        policy=ToolPolicy(
            allowed_tools=[],
            require_explicit_allowlist=True,
        ),
    )

    assert observation.status is ToolStatus.BLOCKED
    with pytest.raises(ToolRuntimeError, match="cannot be materialized"):
        ToolResultEnvelope.from_observation(observation, definition)


def test_resolved_tool_version_is_bound_to_result_identity() -> None:
    definition = ToolDefinition(name="sample.versioned", version="1.0.0")
    observation, _executor = _execute(
        definition,
        lambda _args: {"ok": True},
    )

    with pytest.raises(ToolRuntimeError, match="identity conflicts"):
        ToolResultEnvelope.from_observation(
            observation,
            ToolDefinition(name="sample.versioned", version="2.0.0"),
        )


def test_forged_or_malformed_gate_cannot_enter_result_envelope() -> None:
    definition = ToolDefinition(name="sample.gated")
    observation, _executor = _execute(
        definition,
        lambda _args: {"ok": True},
    )
    forged_result = replace(
        observation.result,
        gate_result={"passed": True},
    )

    with pytest.raises(ToolRuntimeError, match="deterministic gate"):
        ToolResultEnvelope.from_observation(
            replace(observation, result=forged_result),
            definition,
        )


def test_side_effect_result_has_deterministic_physical_attempt_receipt() -> None:
    definition = ToolDefinition(
        name="sample.write",
        side_effect="writes_external_state",
        metadata={"idempotent": True, "reconciliation_supported": True},
    )
    observation, _executor = _execute(
        definition,
        lambda _args: {"external_id": "record-1"},
    )

    envelope = ToolResultEnvelope.from_observation(observation, definition)
    receipt = envelope.side_effect_receipt

    assert receipt is not None
    assert receipt.attempt_id == observation.result.attempt_id
    assert receipt.idempotency_key == observation.result.idempotency_key
    assert receipt.operation_id == observation.result.operation_id
    assert receipt.local_attempt_no == 1
    assert receipt.response_checksum == envelope.response_checksum
    assert receipt.gate_checksum == envelope.gate_checksum
    assert receipt.effect_determinate is True
    assert ToolResultEnvelope.from_dict(envelope.to_dict()).side_effect_receipt == receipt


def test_side_effect_failure_after_physical_start_still_has_receipt() -> None:
    definition = ToolDefinition(
        name="sample.write.invalid",
        side_effect="writes_external_state",
        output_schema={
            "type": "object",
            "properties": {"external_id": {"type": "string"}},
            "required": ["external_id"],
        },
        metadata={"idempotent": True, "reconciliation_supported": True},
    )
    observation, _executor = _execute(
        definition,
        lambda _args: {"unexpected": "already-written"},
    )

    envelope = ToolResultEnvelope.from_observation(observation, definition)

    assert observation.status is ToolStatus.FAILED
    assert observation.result.gate_result["decision"] == "block"
    assert envelope.side_effect_receipt is not None
    assert envelope.side_effect_receipt.attempt_id == observation.result.attempt_id
    assert envelope.side_effect_receipt.effect_determinate is True
    assert envelope.error_code == "ToolRuntimeError"


def test_side_effect_failure_before_physical_start_has_explicit_no_start_receipt() -> None:
    definition = ToolDefinition(
        name="sample.write.secret",
        side_effect="writes_external_state",
        required_secret_names=["REMOTE_API_KEY"],
        metadata={"idempotent": True, "reconciliation_supported": True},
    )
    observation, _executor = _execute(
        definition,
        lambda _args: {"should_not_run": True},
    )

    envelope = ToolResultEnvelope.from_observation(observation, definition)
    receipt = envelope.side_effect_receipt

    assert observation.status is ToolStatus.FAILED
    assert observation.result.gate_result["decision"] == "block"
    assert receipt is not None
    assert receipt.physical_attempt_started is False
    assert receipt.attempt_id is None
    assert receipt.local_attempt_no is None
    assert receipt.effect_determinate is True


def test_timeout_response_is_bounded_and_retains_attempt_outcome() -> None:
    definition = ToolDefinition(
        name="sample.timeout",
        timeout_seconds=0.01,
    )

    def slow(_args):
        time.sleep(0.1)
        return {"late": True}

    observation, _executor = _execute(
        definition,
        slow,
        policy=ToolPolicy(
            allowed_tools=[definition.name],
            require_explicit_allowlist=True,
            cancellation_grace_seconds=0.01,
        ),
    )
    envelope = ToolResultEnvelope.from_observation(observation, definition)

    assert observation.status is ToolStatus.TIMEOUT
    assert observation.result.gate_result["decision"] == "block"
    assert envelope.timeout is True
    assert envelope.status == ToolStatus.TIMEOUT.value
    assert set(thaw_canonical_json(envelope.response)) == {
        "error_code",
        "error_message",
        "indeterminate",
        "termination_confirmed",
    }
    assert "late" not in stable_json_dumps(envelope.to_dict())
