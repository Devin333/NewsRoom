from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.subagents.models import (
    FORBIDDEN_SUBAGENT_CONTEXT_KEYS,
    FORBIDDEN_SUBAGENT_RESULT_KEYS,
    SubAgentContextEnvelope,
    SubAgentHandoff,
    SubAgentInvocation,
    SubAgentResult,
    SubAgentSpec,
)
from framework.harness.subagents.transcript import (
    SubAgentAttemptIdentity,
    SubAgentTranscriptStorePort,
)


@dataclass(frozen=True)
class SubAgentGateResult:
    gate_name: str
    input_checksum: str
    passed: bool
    reason_code: str
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    gate_version: str = "1"
    evidence_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.gate_name or not self.gate_name.strip():
            raise HarnessValidationError("subagent gate name is required")
        if not self.input_checksum.startswith("sha256:") or len(self.input_checksum) != 71:
            raise HarnessValidationError("subagent gate input checksum is invalid")
        if not self.reason_code or not self.reason_code.strip():
            raise HarnessValidationError("subagent gate reason code is required")
        if self.gate_version != "1":
            raise HarnessValidationError("subagent gate version is unsupported")
        object.__setattr__(self, "details", dict(self.details))
        object.__setattr__(self, "evidence_checksum", checksum_for(self.evidence_projection()))

    def evidence_projection(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_name,
            "gate_version": self.gate_version,
            "input_checksum": self.input_checksum,
            "passed": self.passed,
            "reason_code": self.reason_code,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate_name,
            "gate_version": self.gate_version,
            "input_checksum": self.input_checksum,
            "passed": self.passed,
            "reason_code": self.reason_code,
            "evidence_checksum": self.evidence_checksum,
            "reason": self.reason,
            "details": self.details,
        }


class SubAgentContextBoundaryGate:
    gate_name = "subagent_context_boundary"

    def evaluate(self, envelope: SubAgentContextEnvelope) -> SubAgentGateResult:
        payload = envelope.to_dict()["context_pack"]
        forbidden = sorted(_find_forbidden_keys(payload, FORBIDDEN_SUBAGENT_CONTEXT_KEYS))
        return _gate_result(
            self.gate_name,
            input_payload={"context_envelope": envelope.to_dict()},
            passed=not forbidden,
            reason_code=(
                "subagent_context_boundary_passed"
                if not forbidden
                else "subagent_context_private_content"
            ),
            reason=None if not forbidden else "context envelope contains forbidden private fields",
            details={"forbidden": forbidden},
        )


class SubAgentInputSchemaGate:
    gate_name = "subagent_input_schema"

    def evaluate(self, spec: SubAgentSpec, payload: dict[str, Any]) -> SubAgentGateResult:
        return _schema_result(self.gate_name, spec.input_schema, payload)


class SubAgentOutputSchemaGate:
    gate_name = "subagent_output_schema"

    def evaluate(self, spec: SubAgentSpec, result: SubAgentResult) -> SubAgentGateResult:
        forbidden = sorted(FORBIDDEN_SUBAGENT_RESULT_KEYS.intersection(result.output))
        if forbidden:
            return _gate_result(
                self.gate_name,
                input_payload={"schema": spec.output_schema, "output": result.output},
                passed=False,
                reason_code="subagent_output_flow_control_forbidden",
                reason="subagent output contains forbidden flow-control fields",
                details={"forbidden": forbidden},
            )
        return _schema_result(self.gate_name, spec.output_schema, result.output)


class SubAgentToolAllowlistGate:
    gate_name = "subagent_tool_allowlist"

    def evaluate(self, spec: SubAgentSpec, requested_tools: tuple[str, ...]) -> SubAgentGateResult:
        denied = sorted(set(requested_tools) - set(spec.allowed_tools))
        return _gate_result(
            self.gate_name,
            input_payload={"allowed_tools": list(spec.allowed_tools), "requested_tools": list(requested_tools)},
            passed=not denied,
            reason_code="subagent_tool_allowlist_passed" if not denied else "subagent_tool_not_allowed",
            reason=None if not denied else "subagent requested unauthorized tools",
            details={"denied": denied, "allowed_tools": list(spec.allowed_tools)},
        )


class SubAgentMemoryNamespaceGate:
    gate_name = "subagent_memory_namespace"

    def evaluate(self, spec: SubAgentSpec, namespaces: tuple[str, ...]) -> SubAgentGateResult:
        denied = sorted(set(namespaces) - set(spec.allowed_memory_namespaces))
        return _gate_result(
            self.gate_name,
            input_payload={
                "allowed_namespaces": list(spec.allowed_memory_namespaces),
                "requested_namespaces": list(namespaces),
            },
            passed=not denied,
            reason_code=(
                "subagent_memory_namespace_passed"
                if not denied
                else "subagent_memory_namespace_not_allowed"
            ),
            reason=None if not denied else "subagent requested unauthorized memory namespaces",
            details={"denied": denied, "allowed_namespaces": list(spec.allowed_memory_namespaces)},
        )


class SubAgentHandoffSchemaGate:
    gate_name = "subagent_handoff_schema"

    def evaluate(self, handoff: SubAgentHandoff) -> SubAgentGateResult:
        forbidden = sorted(FORBIDDEN_SUBAGENT_CONTEXT_KEYS.intersection(handoff.payload))
        if forbidden:
            return _gate_result(
                self.gate_name,
                input_payload={"schema": handoff.payload_schema, "payload": handoff.payload},
                passed=False,
                reason_code="subagent_handoff_private_content",
                reason="handoff payload contains private fields",
                details={"forbidden": forbidden},
            )
        return _schema_result(self.gate_name, handoff.payload_schema, handoff.payload)


class SubAgentBudgetGate:
    gate_name = "subagent_budget"

    def evaluate(self, invocation: SubAgentInvocation, usage: dict[str, int]) -> SubAgentGateResult:
        budget = invocation.subagent_spec.budget
        limits = {
            "turns": int(budget.get("max_turns", invocation.budget_snapshot.max_turns)),
            "tool_calls": int(budget.get("max_tool_calls", invocation.budget_snapshot.max_worker_calls)),
            "memory_ops": int(budget.get("max_memory_ops", invocation.budget_snapshot.max_worker_calls)),
        }
        violations = {
            name: {"used": int(usage.get(name, 0)), "max": limit}
            for name, limit in limits.items()
            if int(usage.get(name, 0)) > limit
        }
        return _gate_result(
            self.gate_name,
            input_payload={
                "identity": {
                    "invocation_id": invocation.invocation_id,
                    "task_instance_id": invocation.task_instance_id,
                    "attempt": invocation.attempt,
                },
                "limits": limits,
                "usage": usage,
            },
            passed=not violations,
            reason_code="subagent_budget_passed" if not violations else "subagent_budget_exceeded",
            reason=None if not violations else "subagent budget exceeded",
            details={"violations": violations},
        )


class SubAgentTranscriptGate:
    gate_name = "subagent_transcript"

    def evaluate(
        self,
        result: SubAgentResult,
        *,
        store: SubAgentTranscriptStorePort | None = None,
        identity: SubAgentAttemptIdentity | None = None,
    ) -> SubAgentGateResult:
        receipt = result.transcript_receipt
        input_payload = {
            "result": {
                "invocation_id": result.invocation_id,
                "child_run_id": result.child_run_id,
                "subagent_id": result.subagent_id,
                "status": result.status.value,
                "output_checksum": checksum_for(result.output),
                "artifact_refs": list(result.artifact_refs),
            },
            "receipt": receipt.to_dict() if receipt is not None else None,
            "expected_identity": identity.to_dict() if identity is not None else None,
        }
        if receipt is None:
            return _gate_result(
                self.gate_name,
                input_payload=input_payload,
                passed=False,
                reason_code="subagent_transcript_missing",
                reason="subagent transcript receipt is missing",
                details={"reason_code": "subagent_transcript_missing"},
            )
        if store is None:
            return _gate_result(
                self.gate_name,
                input_payload=input_payload,
                passed=False,
                reason_code="subagent_transcript_store_unavailable",
                reason="subagent transcript store is unavailable",
                details={"reason_code": "subagent_transcript_store_unavailable"},
            )
        try:
            verified = store.verify(receipt)
            output = store.read_output(receipt.output_ref)
            transcript = store.read(receipt.transcript_ref)
        except Exception as exc:
            reason_code = getattr(exc, "code", "subagent_transcript_verify_failed")
            return _gate_result(
                self.gate_name,
                input_payload=input_payload,
                passed=False,
                reason_code=reason_code,
                reason="subagent transcript verification failed",
                details={"reason_code": reason_code},
            )
        if verified != receipt:
            return _gate_result(
                self.gate_name,
                input_payload=input_payload,
                passed=False,
                reason_code="subagent_transcript_identity_mismatch",
                reason="subagent transcript receipt changed during verification",
                details={"reason_code": "subagent_transcript_identity_mismatch"},
            )
        if (
            output.status != result.status.value
            or output.artifact_refs != result.artifact_refs
            or checksum_for(output.output) != checksum_for(result.output)
            or transcript.output_checksum != output.output_checksum
        ):
            return _gate_result(
                self.gate_name,
                input_payload=input_payload,
                passed=False,
                reason_code="subagent_output_identity_mismatch",
                reason="subagent durable outcome does not match result",
                details={"reason_code": "subagent_output_identity_mismatch"},
            )
        if identity is not None:
            if (
                transcript.identity != identity
                or output.identity != identity
                or receipt.invocation_id != identity.invocation_id
                or receipt.parent_run_id != identity.parent_run_id
                or receipt.child_run_id != identity.child_run_id
                or receipt.task_instance_id != identity.task_instance_id
                or receipt.attempt != identity.attempt
                or receipt.transcript_id != identity.transcript_id
            ):
                return _gate_result(
                    self.gate_name,
                    input_payload=input_payload,
                    passed=False,
                    reason_code="subagent_transcript_identity_mismatch",
                    reason="subagent transcript identity does not match invocation",
                    details={"reason_code": "subagent_transcript_identity_mismatch"},
                )
        return _gate_result(
            self.gate_name,
            input_payload=input_payload,
            passed=True,
            reason_code="subagent_transcript_verified",
            reason=None,
            details={
                "reason_code": "subagent_transcript_verified",
                "transcript_checksum": receipt.transcript_checksum,
                "output_checksum": receipt.output_checksum,
            },
        )


class FakeSubAgentGateSuite:
    def __init__(self) -> None:
        self.context_boundary = SubAgentContextBoundaryGate()
        self.input_schema = SubAgentInputSchemaGate()
        self.tool_allowlist = SubAgentToolAllowlistGate()
        self.memory_namespace = SubAgentMemoryNamespaceGate()
        self.handoff_schema = SubAgentHandoffSchemaGate()
        self.output_schema = SubAgentOutputSchemaGate()
        self.budget = SubAgentBudgetGate()
        self.transcript = SubAgentTranscriptGate()


def all_subagent_gates_passed(results: tuple[SubAgentGateResult, ...]) -> bool:
    return all(result.passed for result in results)


def _schema_result(gate_name: str, schema: dict[str, Any], payload: dict[str, Any]) -> SubAgentGateResult:
    if not schema:
        return _gate_result(
            gate_name,
            input_payload={"schema": {}, "payload": payload},
            passed=True,
            reason_code=f"{gate_name}_passed",
            reason="no schema configured",
        )
    required = tuple(str(item) for item in schema.get("required", ()))
    missing = sorted(item for item in required if item not in payload)
    invalid_types: list[str] = []
    properties = schema.get("properties", {})
    if properties and not isinstance(properties, dict):
        raise HarnessValidationError("schema.properties must be a dict")
    for name, definition in properties.items():
        if name not in payload or not isinstance(definition, dict):
            continue
        expected_type = definition.get("type")
        if expected_type and not _matches_json_type(payload[name], str(expected_type)):
            invalid_types.append(str(name))
    passed = not missing and not invalid_types
    return _gate_result(
        gate_name,
        input_payload={"schema": schema, "payload": payload},
        passed=passed,
        reason_code=f"{gate_name}_passed" if passed else f"{gate_name}_invalid",
        reason=None if passed else "payload does not match schema",
        details={"missing": missing, "invalid_types": invalid_types},
    )


def _gate_result(
    gate_name: str,
    *,
    input_payload: dict[str, Any],
    passed: bool,
    reason_code: str,
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> SubAgentGateResult:
    return SubAgentGateResult(
        gate_name=gate_name,
        input_checksum=checksum_for(input_payload),
        passed=passed,
        reason_code=reason_code,
        reason=reason,
        details=dict(details or {}),
    )


def _matches_json_type(value: Any, expected_type: str) -> bool:
    mapping = {
        "object": dict,
        "array": list,
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "null": type(None),
    }
    expected = mapping.get(expected_type)
    if expected is None:
        raise HarnessValidationError("unsupported schema type", details={"type": expected_type})
    if expected_type in {"number", "integer"} and isinstance(value, bool):
        return False
    return isinstance(value, expected)


def _find_forbidden_keys(payload: Any, forbidden_keys: frozenset[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in forbidden_keys:
                found.add(str(key))
            found.update(_find_forbidden_keys(value, forbidden_keys))
    elif isinstance(payload, list | tuple):
        for item in payload:
            found.update(_find_forbidden_keys(item, forbidden_keys))
    return found


__all__ = [
    "FakeSubAgentGateSuite",
    "SubAgentBudgetGate",
    "SubAgentContextBoundaryGate",
    "SubAgentGateResult",
    "SubAgentHandoffSchemaGate",
    "SubAgentInputSchemaGate",
    "SubAgentMemoryNamespaceGate",
    "SubAgentOutputSchemaGate",
    "SubAgentToolAllowlistGate",
    "SubAgentTranscriptGate",
    "all_subagent_gates_passed",
]
