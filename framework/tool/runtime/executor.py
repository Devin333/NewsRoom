from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from hashlib import sha256
from pathlib import Path
from typing import Any

from framework.shared.attempts import (
    AttemptBudget,
    AttemptBudgetExhaustedError,
    AttemptCancelledError,
    AttemptContext,
    AttemptState,
    AttemptSupervisor,
    current_attempt_context,
)
from framework.shared.json import to_jsonable
from framework.events.propagation import (
    W3CSpanContext,
    current_trace_context,
    trace_context_scope,
)
from framework.events.trace import TraceContext
from framework.governance import CompositeAndGate, GateCheckResult
from framework.tool.governance.approval import ToolApprovalRequest
from framework.tool.governance.boundary import is_external_fetch_tool, is_restricted_agent_id
from framework.tool.governance.redaction import (
    contains_redacted_value,
    redact_sensitive_values,
    restore_redacted_booleans,
)
from framework.tool.governance.secrets import SecretProvider
from framework.tool.inspection.metrics import ToolEvent, ToolExecutionRecord, ToolMetrics
from framework.tool.models import (
    ArtifactRef,
    ToolCall,
    ToolObservation,
    ToolPermissionError,
    ToolPolicy,
    ToolPolicyTrace,
    ToolResult,
    ToolRuntimeError,
    ToolSecretError,
    ToolStatus,
    ToolTimeoutError,
    is_default_dangerous_tool_name,
    timed_tool_call,
)
from framework.tool.registry.registry import ToolRegistry
from framework.tool.schema.validation import normalize_tool_arguments


_RUNTIME_SECRETS_ARGUMENT = "_secrets"


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        artifact_manager: Any | None = None,
        run_id: str | None = None,
        approval_store: Any | None = None,
        secret_provider: SecretProvider | None = None,
        trace_context: TraceContext | W3CSpanContext | None = None,
    ) -> None:
        self._registry = registry
        self._artifact_manager = artifact_manager
        self._run_id = run_id
        self._approval_store = approval_store
        self._secret_provider = secret_provider
        self._trace_context = trace_context
        self._events: list[ToolEvent] = []
        self._metrics = ToolMetrics()
        self._records: list[ToolExecutionRecord] = []

    @property
    def metrics(self) -> ToolMetrics:
        return self._metrics.snapshot()

    def list_events(self) -> list[ToolEvent]:
        return list(self._events)

    def list_records(self) -> list[ToolExecutionRecord]:
        return list(self._records)

    def execute(self, call: ToolCall, policy: ToolPolicy | None = None) -> ToolObservation:
        parent_context = self._trace_context or current_trace_context()
        if isinstance(parent_context, TraceContext):
            execution_context: TraceContext | W3CSpanContext = (
                parent_context
                if parent_context.tool_call_id == call.call_id
                else parent_context.child(tool_call_id=call.call_id)
            )
        elif isinstance(parent_context, W3CSpanContext):
            execution_context = parent_context.child()
        else:
            execution_context = W3CSpanContext.root()
        with trace_context_scope(execution_context):
            return self._execute_scoped(call, policy)

    def _execute_scoped(
        self,
        call: ToolCall,
        policy: ToolPolicy | None = None,
    ) -> ToolObservation:
        scoped_context = current_trace_context()
        event_trace_context = (
            scoped_context
            if isinstance(scoped_context, (TraceContext, W3CSpanContext))
            else None
        )
        policy = policy or ToolPolicy(require_explicit_allowlist=False)
        started_at = datetime.now(UTC)
        policy_trace = _ToolPolicyTraceBuilder(call.tool_name)
        attempts_used = 0

        def record_attempt(attempt: int) -> None:
            nonlocal attempts_used
            attempts_used = max(attempts_used, int(attempt))

        def invoke() -> ToolResult:
            nonlocal attempts_used
            registered = self._registry.get(call.tool_name)
            policy_trace.risk_level = _risk_level(registered.definition)
            policy_trace.requires_approval = _requires_approval(registered.definition, policy)
            policy_trace.add("tool.resolve", "compatibility", True, f"tool resolved: {call.tool_name}")

            if not policy.allows(call.tool_name):
                policy_trace.add("tool.permission", "safety", False, f"tool is not allowed: {call.tool_name}")
                raise ToolPermissionError(
                    f"agent {call.requested_by_agent_id} is not allowed to call {call.tool_name}"
                )
            policy_trace.add("tool.permission", "safety", True, "tool allowed by policy")

            restricted_agent_result = _restricted_agent_boundary_gate(call)
            if restricted_agent_result is not None:
                policy_trace.add(
                    "tool.boundary",
                    "safety",
                    False,
                    restricted_agent_result.error_message or "restricted agent boundary blocked",
                )
                return restricted_agent_result
            policy_trace.add("tool.boundary", "safety", True, "agent boundary passed")

            dangerous_result = _dangerous_gate(registered.definition, policy)
            if dangerous_result is not None:
                policy_trace.add(
                    "tool.risk",
                    "safety",
                    False,
                    dangerous_result.error_message or "dangerous tool blocked",
                )
                return dangerous_result
            policy_trace.add("tool.risk", "safety", True, "risk gate passed")

            if _RUNTIME_SECRETS_ARGUMENT in call.arguments:
                policy_trace.add(
                    "tool.arguments.reserved",
                    "safety",
                    False,
                    f"reserved tool argument is not allowed: {_RUNTIME_SECRETS_ARGUMENT}",
                )
                raise ToolRuntimeError(
                    f"reserved tool argument is not allowed: {_RUNTIME_SECRETS_ARGUMENT}"
                )

            arguments = normalize_tool_arguments(registered.definition, call.arguments)
            self._emit("tool_args_validated", call)
            policy_trace.add("tool.arguments", "compatibility", True, "arguments validated")

            approval_result = self._approval_gate(call, registered.definition, policy)
            if approval_result is not None:
                policy_trace.approval_granted = False
                policy_trace.add(
                    "tool.approval",
                    "safety",
                    False,
                    approval_result.output_summary or "tool approval required",
                    severity="warning",
                )
                return approval_result
            if policy_trace.requires_approval:
                policy_trace.approval_granted = True
            policy_trace.add("tool.approval", "safety", True, "approval gate passed")

            arguments = _arguments_with_secrets(
                arguments,
                registered.definition,
                self._secret_provider,
            )
            policy_trace.add("tool.secrets", "safety", True, "secret injection passed")

            self._emit("tool_started", call)
            max_attempts = _max_attempts(registered.definition, policy)
            raw_output, attempts_used = _invoke_with_retry(
                _trace_scoped_executor(registered.executor, scoped_context),
                arguments,
                _timeout_seconds(registered.definition, policy),
                max_attempts,
                call.tool_name,
                record_attempt,
                max_total_attempts=policy.max_total_attempts,
                definition=registered.definition,
                cancellation_grace_seconds=policy.cancellation_grace_seconds,
                idempotency_key=_tool_idempotency_key(call),
            )
            policy_trace.add(
                "tool.retry",
                "resource",
                True,
                "retry policy completed",
                metadata={
                    "max_attempts": max_attempts,
                    "attempts": attempts_used,
                    "retry_count": max(0, attempts_used - 1),
                },
            )
            safe_output = restore_redacted_booleans(
                redact_sensitive_values(raw_output),
                raw_output,
            )
            if contains_redacted_value(safe_output):
                self._emit("tool_result_redacted", call, {"redacted": True})
                policy_trace.add("tool.redaction", "safety", True, "output redacted")
            else:
                policy_trace.add("tool.redaction", "safety", True, "output did not require redaction")
            output_bytes = _json_size_bytes(safe_output)
            output_guardrail_result = self._output_size_guard(
                call,
                registered.definition,
                output_bytes,
            )
            if output_guardrail_result is not None:
                policy_trace.add(
                    "tool.output_size",
                    "resource",
                    False,
                    output_guardrail_result.error_message or "output size gate failed",
                    metadata={"output_bytes": output_bytes},
                )
                return output_guardrail_result
            policy_trace.add(
                "tool.output_size",
                "resource",
                True,
                "output size gate passed",
                metadata={"output_bytes": output_bytes},
            )
            return self._tool_result(call, safe_output, policy, output_bytes)

        self._emit("tool_call_requested", call, {"call": call.to_dict()})
        try:
            result, elapsed_ms = timed_tool_call(invoke)
        except ToolPermissionError as exc:
            policy_trace.add("tool.permission.error", "safety", False, str(exc))
            result = ToolResult(
                status=ToolStatus.BLOCKED,
                error_type=type(exc).__name__,
                error_message=str(exc),
                call_id=call.call_id,
                tool_name=call.tool_name,
            )
            elapsed_ms = 0.0
        except ToolTimeoutError as exc:
            policy_trace.add("tool.timeout", "resource", False, str(exc))
            result = ToolResult(
                status=ToolStatus.TIMEOUT,
                error_type=type(exc).__name__,
                error_message=str(exc),
                call_id=call.call_id,
                tool_name=call.tool_name,
                termination_confirmed=exc.termination_confirmed,
                indeterminate=exc.indeterminate,
                attempt_id=exc.attempt_id,
                idempotency_key=exc.idempotency_key,
                fencing_token=exc.fencing_token,
                metadata={
                    "termination_confirmed": exc.termination_confirmed,
                    "indeterminate": exc.indeterminate,
                },
            )
            elapsed_ms = 0.0
        except Exception as exc:
            policy_trace.add("tool.execution", "compatibility", False, str(exc))
            result = ToolResult(
                status=ToolStatus.FAILED,
                error_type=type(exc).__name__,
                error_message=str(exc),
                call_id=call.call_id,
                tool_name=call.tool_name,
            )
            elapsed_ms = 0.0

        result = _standardize_tool_result(
            _with_tool_gate(_with_duration(_with_call(result, call), elapsed_ms), call),
            call=call,
            policy_trace=policy_trace,
            trace_context=event_trace_context,
            retry_count=max(0, attempts_used - 1),
        )
        observation = ToolObservation(call=call, result=result, elapsed_ms=elapsed_ms)
        self._record_observation(observation)
        self._records.append(
            _execution_record(
                observation,
                self._events,
                started_at,
                trace_context=event_trace_context,
            )
        )
        return observation

    def _tool_result(
        self,
        call: ToolCall,
        safe_output: Any,
        policy: ToolPolicy,
        output_bytes: int | None = None,
    ) -> ToolResult:
        output_bytes = output_bytes if output_bytes is not None else _json_size_bytes(safe_output)
        artifact_spill = "inline"
        if (
            policy.spill_large_results_to_artifact
            and output_bytes > policy.max_result_chars_inline
        ):
            artifact_spill = "missing_context"
            if self._artifact_manager is None or self._run_id is None:
                self._emit(
                    "tool_output_guardrail_failed",
                    call,
                    {
                        "reason": "artifact_context_required",
                        "output_bytes": output_bytes,
                        "max_result_chars_inline": policy.max_result_chars_inline,
                    },
                )
                return ToolResult(
                    status=ToolStatus.FAILED,
                    error_type="ToolRuntimeError",
                    error_message=(
                        "tool output exceeded max_result_chars_inline and no "
                        "artifact context is configured"
                    ),
                    output_bytes=output_bytes,
                    call_id=call.call_id,
                    tool_name=call.tool_name,
                    metadata={"artifact_spill": artifact_spill},
                )
            artifact_spill = "spilled"
            relative_path = f"tool_results/{call.call_id}.json"
            artifact_payload = {
                "call": call.to_dict(),
                "output": safe_output,
                "output_bytes": output_bytes,
            }
            path = _write_json_artifact(self._artifact_manager, self._run_id, relative_path, artifact_payload)
            artifact_bytes = path.read_bytes()
            artifact_ref = ArtifactRef(
                artifact_id=f"tool_result:{call.call_id}",
                relative_path=relative_path,
                size_bytes=len(artifact_bytes),
                checksum=sha256(artifact_bytes).hexdigest(),
            )
            return ToolResult(
                status=ToolStatus.SUCCEEDED,
                output=None,
                output_summary=f"Tool result spilled to artifact: {relative_path}",
                artifact_refs=[artifact_ref],
                artifacts=[artifact_ref],
                output_bytes=output_bytes,
                call_id=call.call_id,
                tool_name=call.tool_name,
                metadata={"artifact_spill": artifact_spill},
            )
        return ToolResult(
            status=ToolStatus.SUCCEEDED,
            output=safe_output,
            output_bytes=output_bytes,
            call_id=call.call_id,
            tool_name=call.tool_name,
            metadata={"artifact_spill": artifact_spill},
        )

    def _output_size_guard(self, call: ToolCall, definition: Any, output_bytes: int) -> ToolResult | None:
        max_result_bytes = getattr(definition, "max_result_bytes", None)
        if max_result_bytes is None or output_bytes <= max_result_bytes:
            return None
        payload = {
            "reason": "max_result_bytes_exceeded",
            "output_bytes": output_bytes,
            "max_result_bytes": max_result_bytes,
        }
        self._emit("tool_output_guardrail_failed", call, payload)
        return ToolResult(
            status=ToolStatus.FAILED,
            error_type="ToolRuntimeError",
            error_message=(
                f"tool output exceeded max_result_bytes for {definition.name}: "
                f"{output_bytes} > {max_result_bytes}"
            ),
            output_bytes=output_bytes,
            call_id=call.call_id,
            tool_name=call.tool_name,
        )

    def _record_observation(self, observation: ToolObservation) -> None:
        self._metrics.record(observation)
        if observation.status == ToolStatus.SUCCEEDED:
            self._emit("tool_succeeded", observation.call, _result_event_payload(observation))
            if observation.result.artifact_refs:
                self._emit("tool_result_spilled", observation.call, _result_event_payload(observation))
        elif observation.status == ToolStatus.FAILED:
            self._emit("tool_failed", observation.call, _result_event_payload(observation))
        elif observation.status in {ToolStatus.BLOCKED, ToolStatus.DENIED}:
            self._emit("tool_call_blocked", observation.call, _result_event_payload(observation))
        elif observation.status == ToolStatus.APPROVAL_REQUIRED:
            self._emit("tool_approval_required", observation.call, _result_event_payload(observation))
        elif observation.status == ToolStatus.TIMEOUT:
            self._emit("tool_timeout", observation.call, _result_event_payload(observation))
        self._emit("tool_observation_created", observation.call, observation.to_dict())

    def _emit(self, event_type: str, call: ToolCall, payload: dict[str, Any] | None = None) -> ToolEvent:
        scoped_context = current_trace_context()
        event = ToolEvent.from_trace(
            event_type=event_type,
            tool_name=call.tool_name,
            tool_call_id=call.call_id,
            payload=payload or {},
            trace_context=(
                scoped_context
                if isinstance(scoped_context, (TraceContext, W3CSpanContext))
                else None
            ),
        )
        self._events.append(event)
        return event

    def _approval_gate(self, call: ToolCall, definition: Any, policy: ToolPolicy) -> ToolResult | None:
        if not (
            policy.require_approval_for_side_effects
            and (definition.requires_approval or _has_side_effects(_side_effect_value(definition)))
        ):
            return None

        reason = f"Tool requires approval before execution: {definition.name}"
        approval_id = None
        if self._approval_store is not None:
            request = ToolApprovalRequest(
                tool_call=call,
                tool_name=definition.name,
                side_effect=_side_effect_value(definition),
                reason=reason,
                risk_level=_risk_level(definition),
                run_id=self._run_id,
                agent_id=call.requested_by_agent_id or None,
            )
            stored = self._approval_store.upsert_approval(request.to_worker_approval_request())
            approval_id = getattr(stored, "approval_id", None)

        return ToolResult(
            status=ToolStatus.APPROVAL_REQUIRED,
            output_summary=reason,
            approval_id=approval_id,
            call_id=call.call_id,
            tool_name=call.tool_name,
        )


def _result_event_payload(observation: ToolObservation) -> dict[str, Any]:
    return {
        "status": observation.status.value,
        "elapsed_ms": observation.elapsed_ms,
        "error_type": observation.result.error_type,
        "error_message": observation.result.error_message,
        "output_bytes": observation.result.output_bytes,
        "artifact_refs": [artifact_ref.to_dict() for artifact_ref in observation.result.artifact_refs],
        "termination_confirmed": observation.result.termination_confirmed,
        "indeterminate": observation.result.indeterminate,
        "attempt_id": observation.result.attempt_id,
        "fencing_token": observation.result.fencing_token,
    }


def _execution_record(
    observation: ToolObservation,
    events: list[ToolEvent],
    started_at: datetime,
    *,
    trace_context: TraceContext | W3CSpanContext | None = None,
) -> ToolExecutionRecord:
    call_events = [
        event.event_type
        for event in events
        if event.tool_call_id == observation.call.call_id
    ]
    return ToolExecutionRecord(
        tool_call=observation.call,
        tool_result=observation.result,
        validation_passed="tool_args_validated" in call_events,
        guardrails_passed=observation.status not in {ToolStatus.BLOCKED, ToolStatus.DENIED},
        approval_required=observation.status == ToolStatus.APPROVAL_REQUIRED,
        approval_id=observation.result.approval_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        events=call_events,
        trace_id=trace_context.trace_id if trace_context is not None else None,
        span_id=trace_context.span_id if trace_context is not None else None,
        parent_span_id=(
            trace_context.parent_span_id if trace_context is not None else None
        ),
        gate_result=observation.result.gate_result,
        policy_trace=_tool_policy_trace_to_dict(observation.result.policy_trace),
        error_envelope=observation.result.error_envelope,
        retry_count=observation.result.retry_count,
        timeout=observation.result.timeout,
)


def _tool_policy_trace_to_dict(policy_trace: Any) -> dict[str, Any] | None:
    if policy_trace is None:
        return None
    to_dict = getattr(policy_trace, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, Mapping):
            return {str(key): value for key, value in payload.items()}
    if isinstance(policy_trace, Mapping):
        return {str(key): value for key, value in policy_trace.items()}
    return None


def _dangerous_gate(definition: Any, policy: ToolPolicy) -> ToolResult | None:
    if _is_dangerous_tool(definition) and not policy.allow_dangerous_tools:
        return ToolResult(
            status=ToolStatus.BLOCKED,
            error_type="ToolPermissionError",
            error_message=f"dangerous tool is not allowed: {definition.name}",
            tool_name=definition.name,
        )
    return None


def _restricted_agent_boundary_gate(call: ToolCall) -> ToolResult | None:
    if (
        call.requested_by_agent_id
        and is_restricted_agent_id(call.requested_by_agent_id)
        and is_external_fetch_tool(call.tool_name)
    ):
        return ToolResult(
            status=ToolStatus.BLOCKED,
            error_type="ToolPermissionError",
            error_message=(
                "restricted agent is not allowed to call configured boundary "
                f"tool: {call.tool_name}"
            ),
            call_id=call.call_id,
            tool_name=call.tool_name,
        )
    return None


def _is_dangerous_tool(definition: Any) -> bool:
    name = str(getattr(definition, "name", ""))
    if is_default_dangerous_tool_name(name):
        return True
    return bool(getattr(definition, "is_dangerous", False))


def _with_duration(result: ToolResult, elapsed_ms: float) -> ToolResult:
    return result.with_duration(elapsed_ms)


def _with_call(result: ToolResult, call: ToolCall) -> ToolResult:
    if result.call_id == call.call_id and result.tool_name == call.tool_name:
        return result
    return _copy_tool_result(
        result,
        call_id=result.call_id or call.call_id,
        tool_name=result.tool_name or call.tool_name,
    )


def _with_tool_gate(result: ToolResult, call: ToolCall) -> ToolResult:
    if result.gate_result is not None:
        return result
    checks = [
        GateCheckResult(
            check_id="tool.status",
            dimension="safety" if result.status in {ToolStatus.BLOCKED, ToolStatus.DENIED} else "compatibility",
            passed=result.status not in {ToolStatus.BLOCKED, ToolStatus.DENIED},
            reason=result.error_message or "",
        )
    ]
    if result.status == ToolStatus.APPROVAL_REQUIRED:
        checks.append(
            GateCheckResult(
                check_id="tool.approval",
                dimension="safety",
                passed=False,
                severity="warning",
                reason=result.output_summary or "tool approval required",
            )
        )
    if result.status == ToolStatus.FAILED and result.error_type == "ToolRuntimeError":
        checks.append(
            GateCheckResult(
                check_id="tool.output",
                dimension="resource",
                passed=False,
                reason=result.error_message or "tool output gate failed",
                metadata={"output_bytes": result.output_bytes},
            )
        )
    gate = CompositeAndGate(f"tool:{call.call_id}:gate").evaluate(
        checks,
        metadata={"tool_name": call.tool_name, "call_id": call.call_id},
    )
    return _copy_tool_result(
        result,
        gate_result=gate.to_dict(),
    )


def _standardize_tool_result(
    result: ToolResult,
    *,
    call: ToolCall,
    policy_trace: "_ToolPolicyTraceBuilder",
    trace_context: TraceContext | W3CSpanContext | None,
    retry_count: int,
) -> ToolResult:
    artifact_spill = result.metadata.get("artifact_spill")
    if artifact_spill == "spilled":
        policy_trace.add(
            "tool.artifact_spill",
            "artifact",
            True,
            "tool output spilled to artifact",
            metadata={"artifact_refs": [ref.to_dict() for ref in result.artifact_refs]},
        )
    elif artifact_spill == "missing_context":
        policy_trace.add(
            "tool.artifact_spill",
            "artifact",
            False,
            result.error_message or "artifact context required",
        )
    else:
        policy_trace.add("tool.artifact_spill", "artifact", True, "inline output retained")
    return _copy_tool_result(
        result,
        policy_trace=policy_trace.to_trace(result),
        retry_count=retry_count,
        timeout=result.status == ToolStatus.TIMEOUT,
        trace_id=trace_context.trace_id if trace_context is not None else None,
        span_id=trace_context.span_id if trace_context is not None else None,
        parent_span_id=(
            trace_context.parent_span_id if trace_context is not None else None
        ),
        redacted_output=redact_sensitive_values(result.output),
    )


def _copy_tool_result(result: ToolResult, **overrides: Any) -> ToolResult:
    values = {
        "status": result.status,
        "output": result.output,
        "output_summary": result.output_summary,
        "artifact_refs": list(result.artifact_refs),
        "artifacts": list(result.artifacts),
        "error_type": result.error_type,
        "error_message": result.error_message,
        "approval_id": result.approval_id,
        "redacted": result.redacted,
        "output_bytes": result.output_bytes,
        "duration_ms": result.duration_ms,
        "metadata": dict(result.metadata),
        "call_id": result.call_id,
        "tool_name": result.tool_name,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "gate_result": result.gate_result,
        "redacted_output": result.redacted_output,
        "policy_trace": result.policy_trace,
        "retry_count": result.retry_count,
        "timeout": result.timeout,
        "termination_confirmed": result.termination_confirmed,
        "indeterminate": result.indeterminate,
        "attempt_id": result.attempt_id,
        "idempotency_key": result.idempotency_key,
        "fencing_token": result.fencing_token,
        "trace_id": result.trace_id,
        "span_id": result.span_id,
        "parent_span_id": result.parent_span_id,
        "error_envelope": result.error_envelope,
    }
    values.update(overrides)
    return ToolResult(**values)


def _has_side_effects(side_effect: str) -> bool:
    return side_effect not in {"", "none", "read_only"}


def _side_effect_value(definition: Any) -> str:
    value = getattr(definition, "side_effect_value", None)
    if value is not None:
        return str(value)
    side_effect = getattr(definition, "side_effect", "")
    return getattr(side_effect, "value", side_effect)


def _risk_level(definition: Any) -> str:
    side_effect = _side_effect_value(definition)
    if definition.is_dangerous or side_effect == "destructive":
        return "critical"
    if side_effect in {"publishing", "writes_external_state", "external_write"}:
        return "high"
    if side_effect in {"writes_local_state", "local_write"}:
        return "medium"
    if definition.requires_approval:
        return "medium"
    return "low"


def _requires_approval(definition: Any, policy: ToolPolicy) -> bool:
    return bool(
        policy.require_approval_for_side_effects
        and (
            getattr(definition, "requires_approval", False)
            or _has_side_effects(_side_effect_value(definition))
        )
    )


class _ToolPolicyTraceBuilder:
    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        self.risk_level = "unknown"
        self.requires_approval = False
        self.approval_granted: bool | None = None
        self.checks: list[GateCheckResult] = []

    def add(
        self,
        check_id: str,
        dimension: str,
        passed: bool,
        reason: str,
        *,
        severity: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.checks.append(
            GateCheckResult(
                check_id=check_id,
                dimension=dimension,
                passed=passed,
                severity=severity or ("info" if passed else "error"),
                reason=reason,
                metadata=dict(metadata or {}),
            )
        )

    def to_trace(self, result: ToolResult) -> ToolPolicyTrace:
        allowed = result.status not in {ToolStatus.BLOCKED, ToolStatus.DENIED}
        failed_reasons = [check.reason for check in self.checks if not check.passed]
        return ToolPolicyTrace(
            tool_name=result.tool_name or self.tool_name,
            allowed=allowed,
            risk_level=self.risk_level,
            requires_approval=self.requires_approval,
            approval_granted=self.approval_granted,
            checks=[check.to_dict() for check in self.checks],
            reason="; ".join(reason for reason in failed_reasons if reason)
            or result.error_message
            or result.output_summary
            or "tool execution completed",
        )


def _timeout_seconds(definition: Any, policy: ToolPolicy) -> float | None:
    if definition.timeout_seconds is not None:
        return definition.timeout_seconds
    return policy.timeout_seconds_default


def _max_attempts(definition: Any, policy: ToolPolicy) -> int:
    attempts = definition.max_attempts
    if attempts is None:
        attempts = policy.max_attempts_default
    return max(1, int(attempts))


def _arguments_with_secrets(arguments: dict[str, Any], definition: Any, secret_provider: SecretProvider | None) -> dict[str, Any]:
    required_secret_names = list(getattr(definition, "required_secret_names", []))
    if not required_secret_names:
        return arguments
    if secret_provider is None:
        raise ToolSecretError(
            f"missing secret provider for tool {definition.name}; "
            f"required secrets: {', '.join(required_secret_names)}"
        )
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for secret_name in required_secret_names:
        value = secret_provider.get_secret(secret_name)
        if value:
            resolved[secret_name] = value
        else:
            missing.append(secret_name)
    if missing:
        raise ToolSecretError(
            f"missing required secrets for tool {definition.name}: {', '.join(missing)}"
        )
    return {**arguments, _RUNTIME_SECRETS_ARGUMENT: resolved}


def _invoke_with_retry(
    executor: Any,
    arguments: dict[str, Any],
    timeout_seconds: float | None,
    max_attempts: int,
    tool_name: str,
    attempt_callback: Any | None = None,
    *,
    max_total_attempts: int | None = None,
    definition: Any | None = None,
    cancellation_grace_seconds: float = 0.1,
    idempotency_key: str | None = None,
) -> tuple[Any, int]:
    # Keep one total budget when a Tool executes inside a Workflow attempt.
    effective_max = min(max_attempts, max_total_attempts) if max_total_attempts else max_attempts
    parent_context = current_attempt_context()
    logical_idempotency_key = (
        parent_context.idempotency_key
        if parent_context is not None
        else idempotency_key or f"tool:{tool_name}"
    )
    budget = parent_context.budget if parent_context is not None else None
    if budget is None:
        budget = AttemptBudget(max_attempts=effective_max)
    elif parent_context is not None:
        if max_total_attempts is not None:
            budget.cap_at(max_total_attempts)
        budget.expand_to(budget.used + max(0, effective_max - 1))
        effective_max = min(effective_max, 1 + budget.remaining)
    supervisor = AttemptSupervisor(
        cancellation_grace_seconds=cancellation_grace_seconds
    )
    for attempt in range(1, effective_max + 1):
        if parent_context is not None:
            parent_context.raise_if_cancelled()
        if callable(attempt_callback):
            attempt_callback(attempt)
        try:
            supervised = supervisor.run(
                lambda: executor(arguments),
                timeout_seconds=_bounded_timeout(timeout_seconds, parent_context),
                idempotency_key=logical_idempotency_key,
                fencing_token=(
                    parent_context.fencing_token
                    if parent_context is not None
                    else attempt
                ),
                budget=budget,
                parent_cancel_event=(
                    parent_context.cancel_event
                    if parent_context is not None
                    else None
                ),
                parent_context=parent_context,
                claim_budget=not (parent_context is not None and attempt == 1),
            )
        except AttemptBudgetExhaustedError:
            raise ToolRuntimeError("tool attempt budget exhausted") from None

        if supervised.state is AttemptState.SUCCEEDED:
            return supervised.value, attempt
        if supervised.state is AttemptState.FAILED:
            error = supervised.error
            if isinstance(error, AttemptCancelledError):
                raise _tool_timeout_error(
                    tool_name=tool_name,
                    timeout_seconds=timeout_seconds,
                    context=supervised.context,
                    termination_confirmed=True,
                    indeterminate=False,
                ) from None
            if error is None:
                raise ToolRuntimeError("tool attempt failed without an error")
            if attempt == effective_max:
                raise error
            continue

        timeout_is_safe = _timeout_retry_is_safe(definition)
        indeterminate = supervised.indeterminate or not timeout_is_safe
        if parent_context is not None:
            if not supervised.termination_confirmed:
                parent_context.mark_descendant_unconfirmed()
            elif indeterminate:
                parent_context.mark_descendant_indeterminate()
        timeout_error = _tool_timeout_error(
            tool_name=tool_name,
            timeout_seconds=timeout_seconds,
            context=supervised.context,
            termination_confirmed=supervised.termination_confirmed,
            indeterminate=indeterminate,
        )
        if (
            attempt == effective_max
            or not supervised.termination_confirmed
            or indeterminate
        ):
            raise timeout_error
    raise RuntimeError(f"tool {tool_name} retry loop exited unexpectedly")


def _invoke_with_timeout(
    executor: Any,
    arguments: dict[str, Any],
    timeout_seconds: float | None,
    tool_name: str,
) -> Any:
    supervised = AttemptSupervisor().run(
        lambda: executor(arguments),
        timeout_seconds=timeout_seconds,
        idempotency_key=f"tool:{tool_name}",
    )
    if supervised.state is AttemptState.SUCCEEDED:
        return supervised.value
    if supervised.state is AttemptState.FAILED:
        if supervised.error is None:
            raise ToolRuntimeError("tool attempt failed without an error")
        raise supervised.error
    raise _tool_timeout_error(
        tool_name=tool_name,
        timeout_seconds=timeout_seconds,
        context=supervised.context,
        termination_confirmed=supervised.termination_confirmed,
        indeterminate=supervised.indeterminate,
    )


def _tool_idempotency_key(call: ToolCall) -> str:
    parent_context = current_attempt_context()
    if parent_context is not None:
        return parent_context.idempotency_key
    configured = call.metadata.get("idempotency_key")
    return str(configured or f"tool:{call.call_id}")


def _trace_scoped_executor(
    executor: Any,
    context: TraceContext | W3CSpanContext | None,
) -> Any:
    def execute(arguments: dict[str, Any]) -> Any:
        with trace_context_scope(context):
            return executor(arguments)

    return execute


def _bounded_timeout(
    timeout_seconds: float | None,
    parent_context: AttemptContext | None,
) -> float | None:
    parent_remaining = (
        parent_context.remaining_seconds if parent_context is not None else None
    )
    if parent_remaining is None:
        return timeout_seconds
    if timeout_seconds is None or timeout_seconds <= 0:
        return parent_remaining
    return min(float(timeout_seconds), parent_remaining)


def _timeout_retry_is_safe(definition: Any | None) -> bool:
    if definition is None:
        return True
    side_effect = _side_effect_value(definition).casefold()
    if side_effect in {"", "none", "read_only"}:
        return True
    metadata = dict(getattr(definition, "metadata", {}) or {})
    return bool(
        metadata.get("idempotent") is True
        and metadata.get("reconciliation_supported") is True
    )


def _tool_timeout_error(
    *,
    tool_name: str,
    timeout_seconds: float | None,
    context: AttemptContext,
    termination_confirmed: bool,
    indeterminate: bool,
) -> ToolTimeoutError:
    timeout_text = (
        f"{float(timeout_seconds):g} seconds"
        if timeout_seconds is not None
        else "its deadline"
    )
    return ToolTimeoutError(
        f"tool {tool_name} exceeded timeout of {timeout_text}",
        attempt_id=context.attempt_id,
        idempotency_key=context.idempotency_key,
        fencing_token=context.fencing_token,
        termination_confirmed=termination_confirmed,
        indeterminate=indeterminate,
    )


def _json_size_bytes(value: Any) -> int:
    return len(json.dumps(to_jsonable(value), ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _write_json_artifact(artifact_manager: Any, run_id: str, relative_path: str, payload: dict[str, Any]) -> Path:
    path = artifact_manager.write_json(run_id, relative_path, payload)
    if isinstance(path, Path):
        return path
    return Path(path)
