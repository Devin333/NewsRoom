from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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


@dataclass(frozen=True)
class SubAgentGateResult:
    gate_name: str
    passed: bool
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate_name,
            "passed": self.passed,
            "reason": self.reason,
            "details": self.details,
        }


class SubAgentContextBoundaryGate:
    gate_name = "subagent_context_boundary"

    def evaluate(self, envelope: SubAgentContextEnvelope) -> SubAgentGateResult:
        payload = envelope.to_dict()["context_pack"]
        forbidden = sorted(_find_forbidden_keys(payload, FORBIDDEN_SUBAGENT_CONTEXT_KEYS))
        return SubAgentGateResult(
            gate_name=self.gate_name,
            passed=not forbidden,
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
            return SubAgentGateResult(
                gate_name=self.gate_name,
                passed=False,
                reason="subagent output contains forbidden flow-control fields",
                details={"forbidden": forbidden},
            )
        return _schema_result(self.gate_name, spec.output_schema, result.output)


class SubAgentToolAllowlistGate:
    gate_name = "subagent_tool_allowlist"

    def evaluate(self, spec: SubAgentSpec, requested_tools: tuple[str, ...]) -> SubAgentGateResult:
        denied = sorted(set(requested_tools) - set(spec.allowed_tools))
        return SubAgentGateResult(
            gate_name=self.gate_name,
            passed=not denied,
            reason=None if not denied else "subagent requested unauthorized tools",
            details={"denied": denied, "allowed_tools": list(spec.allowed_tools)},
        )


class SubAgentMemoryNamespaceGate:
    gate_name = "subagent_memory_namespace"

    def evaluate(self, spec: SubAgentSpec, namespaces: tuple[str, ...]) -> SubAgentGateResult:
        denied = sorted(set(namespaces) - set(spec.allowed_memory_namespaces))
        return SubAgentGateResult(
            gate_name=self.gate_name,
            passed=not denied,
            reason=None if not denied else "subagent requested unauthorized memory namespaces",
            details={"denied": denied, "allowed_namespaces": list(spec.allowed_memory_namespaces)},
        )


class SubAgentHandoffSchemaGate:
    gate_name = "subagent_handoff_schema"

    def evaluate(self, handoff: SubAgentHandoff) -> SubAgentGateResult:
        forbidden = sorted(FORBIDDEN_SUBAGENT_CONTEXT_KEYS.intersection(handoff.payload))
        if forbidden:
            return SubAgentGateResult(
                gate_name=self.gate_name,
                passed=False,
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
        return SubAgentGateResult(
            gate_name=self.gate_name,
            passed=not violations,
            reason=None if not violations else "subagent budget exceeded",
            details={"violations": violations},
        )


class SubAgentTranscriptGate:
    gate_name = "subagent_transcript"

    def evaluate(self, result: SubAgentResult) -> SubAgentGateResult:
        passed = bool(result.transcript_ref)
        return SubAgentGateResult(
            gate_name=self.gate_name,
            passed=passed,
            reason=None if passed else "subagent transcript is missing",
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
        return SubAgentGateResult(gate_name=gate_name, passed=True, reason="no schema configured")
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
    return SubAgentGateResult(
        gate_name=gate_name,
        passed=passed,
        reason=None if passed else "payload does not match schema",
        details={"missing": missing, "invalid_types": invalid_types},
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
