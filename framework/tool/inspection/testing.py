from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.tool.governance.boundary import is_external_fetch_tool, is_restricted_agent_id
from framework.tool.runtime.executor import ToolExecutor
from framework.tool.models import (
    ToolCall,
    ToolObservation,
    ToolPolicy,
    ToolResult,
    ToolRuntimeError,
    ToolStatus,
    is_default_dangerous_tool_name,
)
from framework.tool.governance.redaction import contains_redacted_value
from framework.tool.registry import ToolRegistry
from framework.tool.governance.secrets import SecretProvider
from framework.tool.inspection.metrics import ToolEvent, ToolMetrics
from framework.tool.schema.validation import normalize_tool_arguments


@dataclass(frozen=True)
class ToolTestCase:
    name: str
    call: ToolCall | None = None
    policy: ToolPolicy = field(default_factory=ToolPolicy)
    tool_name: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    requested_by_agent_id: str = ""
    expected_status: ToolStatus = ToolStatus.SUCCEEDED
    expected_output_keys: list[str] = field(default_factory=list)
    expected_error_type: str | None = None
    require_artifact_refs: bool = False
    require_redaction: bool = False
    require_approval_required: bool = False
    dry_run: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolTestReport:
    case_name: str
    passed: bool
    errors: list[str]
    observation: ToolObservation
    events: list[ToolEvent]
    metrics: ToolMetrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_name": self.case_name,
            "passed": self.passed,
            "errors": list(self.errors),
            "observation": self.observation.to_dict(),
            "events": [event.to_dict() for event in self.events],
            "metrics": self.metrics.to_dict(),
        }


class ToolTestRunner:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        artifact_manager: Any | None = None,
        run_id: str | None = None,
        secret_provider: SecretProvider | None = None,
    ) -> None:
        self._registry = registry
        self._artifact_manager = artifact_manager
        self._run_id = run_id
        self._secret_provider = secret_provider

    def run_case(self, test_case: ToolTestCase) -> ToolTestReport:
        if test_case.dry_run:
            return self._run_dry_case(test_case)

        executor = ToolExecutor(
            self._registry,
            artifact_manager=self._artifact_manager,
            run_id=self._run_id,
            secret_provider=self._secret_provider,
        )
        observation = executor.execute(_case_call(test_case), test_case.policy)
        errors = _expectation_errors(test_case, observation)
        return ToolTestReport(
            case_name=test_case.name,
            passed=not errors,
            errors=errors,
            observation=observation,
            events=executor.list_events(),
            metrics=executor.metrics,
        )

    def run_cases(self, test_cases: list[ToolTestCase]) -> list[ToolTestReport]:
        return [self.run_case(test_case) for test_case in test_cases]

    def _run_dry_case(self, test_case: ToolTestCase) -> ToolTestReport:
        call = _case_call(test_case)
        try:
            registered = self._registry.get(call.tool_name)
            if not test_case.policy.allows(call.tool_name):
                observation = ToolObservation(
                    call=call,
                    result=ToolResult(
                        status=ToolStatus.BLOCKED,
                        error_type="ToolPermissionError",
                        error_message=(
                            f"agent {call.requested_by_agent_id} is not allowed "
                            f"to call {call.tool_name}"
                        ),
                    ),
                    elapsed_ms=0.0,
                )
            elif _restricted_agent_boundary_blocks(call):
                observation = ToolObservation(
                    call=call,
                    result=ToolResult(
                        status=ToolStatus.BLOCKED,
                        error_type="ToolPermissionError",
                        error_message=(
                            "restricted agent is not allowed to call external fetch/search "
                            f"tool: {call.tool_name}"
                        ),
                    ),
                    elapsed_ms=0.0,
                )
            else:
                normalize_tool_arguments(registered.definition, dict(call.arguments))
                observation = self._dry_run_observation(call, registered.definition, test_case)
        except Exception as exc:
            observation = ToolObservation(
                call=call,
                result=ToolResult(
                    status=ToolStatus.FAILED,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                ),
                elapsed_ms=0.0,
            )
        errors = _expectation_errors(test_case, observation)
        metrics = ToolMetrics()
        metrics.record(observation)
        return ToolTestReport(
            case_name=test_case.name,
            passed=not errors,
            errors=errors,
            observation=observation,
            events=[],
            metrics=metrics,
        )

    def _dry_run_observation(
        self,
        call: ToolCall,
        definition: Any,
        test_case: ToolTestCase,
    ) -> ToolObservation:
        if _is_dangerous_tool(definition) and not test_case.policy.allow_dangerous_tools:
            return ToolObservation(
                call=call,
                result=ToolResult(
                    status=ToolStatus.BLOCKED,
                    error_type="ToolPermissionError",
                    error_message=f"dangerous tool is not allowed: {call.tool_name}",
                ),
                elapsed_ms=0.0,
            )
        if (
            test_case.policy.require_approval_for_side_effects
            and (
                definition.requires_approval
                or definition.side_effect_value not in {"", "none", "read_only"}
            )
        ):
            return ToolObservation(
                call=call,
                result=ToolResult(
                    status=ToolStatus.APPROVAL_REQUIRED,
                    output_summary=(
                        f"Tool requires approval before execution: {call.tool_name}"
                    ),
                ),
                elapsed_ms=0.0,
            )
        return ToolObservation(
            call=call,
            result=ToolResult(
                status=ToolStatus.SUCCEEDED,
                output={"dry_run": True, "tool_name": call.tool_name},
                output_summary="Tool dry-run validation passed",
            ),
            elapsed_ms=0.0,
        )


def _restricted_agent_boundary_blocks(call: ToolCall) -> bool:
    return (
        bool(call.requested_by_agent_id)
        and is_restricted_agent_id(call.requested_by_agent_id)
        and is_external_fetch_tool(call.tool_name)
    )


def _is_dangerous_tool(definition: Any) -> bool:
    if is_default_dangerous_tool_name(definition.name):
        return True
    return bool(definition.is_dangerous)


def _expectation_errors(test_case: ToolTestCase, observation: ToolObservation) -> list[str]:
    errors: list[str] = []
    if observation.status != test_case.expected_status:
        errors.append(
            "expected status "
            f"{test_case.expected_status.value}, got {observation.status.value}"
        )
    if test_case.require_artifact_refs and not observation.result.artifact_refs:
        errors.append("expected at least one artifact ref")
    if test_case.expected_error_type and observation.result.error_type != test_case.expected_error_type:
        errors.append(
            "expected error type "
            f"{test_case.expected_error_type}, got {observation.result.error_type}"
        )
    if test_case.expected_output_keys:
        if not isinstance(observation.result.output, dict):
            errors.append("expected output to be an object")
        else:
            missing = [
                key
                for key in test_case.expected_output_keys
                if key not in observation.result.output
            ]
            if missing:
                errors.append(f"expected output keys missing: {', '.join(missing)}")
    if test_case.require_redaction and not contains_redacted_value(
        observation.result.to_dict()
    ):
        errors.append("expected result to contain redacted values")
    if (
        test_case.require_approval_required
        and observation.status != ToolStatus.APPROVAL_REQUIRED
    ):
        errors.append("expected approval_required observation")
    return errors


def _case_call(test_case: ToolTestCase) -> ToolCall:
    if test_case.call is not None:
        return test_case.call
    if not test_case.tool_name:
        raise ToolRuntimeError("ToolTestCase requires call or tool_name")
    return ToolCall(
        tool_name=test_case.tool_name,
        arguments=dict(test_case.args),
        requested_by_agent_id=test_case.requested_by_agent_id,
    )

