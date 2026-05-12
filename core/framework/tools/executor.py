from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from core.framework.artifacts import ArtifactManager
from core.framework.tools.approval import ToolApprovalRequest
from core.framework.tools.models import (
    ArtifactRef,
    ToolCall,
    ToolObservation,
    ToolPermissionError,
    ToolPolicy,
    ToolResult,
    ToolRuntimeError,
    ToolSecretError,
    ToolStatus,
    ToolTimeoutError,
    timed_tool_call,
)
from core.framework.tools.redaction import redact_sensitive_values
from core.framework.tools.registry import ToolRegistry
from core.framework.tools.secrets import SecretProvider
from core.framework.tools.telemetry import ToolEvent, ToolExecutionRecord, ToolMetrics
from core.framework.tools.validation import validate_tool_arguments
from core.framework.workers.approval import ApprovalStore


_RUNTIME_SECRETS_ARGUMENT = "_secrets"


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        artifact_manager: ArtifactManager | None = None,
        run_id: str | None = None,
        approval_store: ApprovalStore | None = None,
        secret_provider: SecretProvider | None = None,
    ) -> None:
        self._registry = registry
        self._artifact_manager = artifact_manager
        self._run_id = run_id
        self._approval_store = approval_store
        self._secret_provider = secret_provider
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

    def execute(self, call: ToolCall, policy: ToolPolicy) -> ToolObservation:
        started_at = datetime.now(UTC)

        def invoke() -> ToolResult:
            registered = self._registry.get(call.tool_name)

            if not policy.allows(call.tool_name):
                raise ToolPermissionError(
                    f"agent {call.requested_by_agent_id} is not allowed to call {call.tool_name}"
                )

            dangerous_result = _dangerous_gate(registered.definition, policy)
            if dangerous_result is not None:
                return dangerous_result

            if _RUNTIME_SECRETS_ARGUMENT in call.arguments:
                raise ToolRuntimeError(
                    f"reserved tool argument is not allowed: {_RUNTIME_SECRETS_ARGUMENT}"
                )

            validate_tool_arguments(registered.definition, call.arguments)
            self._emit("tool_args_validated", call)

            approval_result = self._approval_gate(call, registered.definition, policy)
            if approval_result is not None:
                return approval_result

            arguments = _arguments_with_secrets(
                call.arguments,
                registered.definition,
                self._secret_provider,
            )

            self._emit("tool_started", call)
            raw_output = _invoke_with_retry(
                registered.executor,
                arguments,
                _timeout_seconds(registered.definition, policy),
                _max_attempts(registered.definition, policy),
                call.tool_name,
            )
            safe_output = redact_sensitive_values(raw_output)
            return self._tool_result(call, safe_output, policy)

        self._emit("tool_call_requested", call, {"call": call.to_dict()})
        try:
            result, elapsed_ms = timed_tool_call(invoke)
        except ToolPermissionError as exc:
            result = ToolResult(
                status=ToolStatus.BLOCKED,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            elapsed_ms = 0.0
        except ToolTimeoutError as exc:
            result = ToolResult(
                status=ToolStatus.TIMEOUT,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            elapsed_ms = 0.0
        except Exception as exc:
            result = ToolResult(
                status=ToolStatus.FAILED,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            elapsed_ms = 0.0

        observation = ToolObservation(call=call, result=result, elapsed_ms=elapsed_ms)
        self._record_observation(observation)
        self._records.append(_execution_record(observation, self._events, started_at))
        return observation

    def _tool_result(
        self,
        call: ToolCall,
        safe_output: Any,
        policy: ToolPolicy,
    ) -> ToolResult:
        output_bytes = _json_size_bytes(safe_output)
        if (
            policy.spill_large_results_to_artifact
            and output_bytes > policy.max_result_chars_inline
            and self._artifact_manager is not None
            and self._run_id is not None
        ):
            relative_path = f"tool_results/{call.call_id}.json"
            artifact_payload = {
                "call": call.to_dict(),
                "output": safe_output,
                "output_bytes": output_bytes,
            }
            path = self._artifact_manager.write_json(self._run_id, relative_path, artifact_payload)
            artifact_ref = ArtifactRef(
                artifact_id=f"tool_result:{call.call_id}",
                relative_path=relative_path,
                size_bytes=path.stat().st_size,
            )
            return ToolResult(
                status=ToolStatus.SUCCEEDED,
                output=None,
                output_summary=f"Tool result spilled to artifact: {relative_path}",
                artifact_refs=[artifact_ref],
                output_bytes=output_bytes,
            )
        return ToolResult(
            status=ToolStatus.SUCCEEDED,
            output=safe_output,
            output_bytes=output_bytes,
        )

    def _record_observation(self, observation: ToolObservation) -> None:
        self._metrics.record(observation)
        if observation.status == ToolStatus.SUCCEEDED:
            self._emit("tool_succeeded", observation.call, _result_event_payload(observation))
            if observation.result.artifact_refs:
                self._emit("tool_result_spilled", observation.call, _result_event_payload(observation))
        elif observation.status == ToolStatus.FAILED:
            self._emit("tool_failed", observation.call, _result_event_payload(observation))
        elif observation.status == ToolStatus.BLOCKED:
            self._emit("tool_call_blocked", observation.call, _result_event_payload(observation))
        elif observation.status == ToolStatus.APPROVAL_REQUIRED:
            self._emit("tool_approval_required", observation.call, _result_event_payload(observation))
        elif observation.status == ToolStatus.TIMEOUT:
            self._emit("tool_timeout", observation.call, _result_event_payload(observation))
        self._emit("tool_observation_created", observation.call, observation.to_dict())

    def _emit(
        self,
        event_type: str,
        call: ToolCall,
        payload: dict[str, Any] | None = None,
    ) -> ToolEvent:
        event = ToolEvent(
            event_type=event_type,
            tool_name=call.tool_name,
            tool_call_id=call.call_id,
            payload=payload or {},
        )
        self._events.append(event)
        return event

    def _approval_gate(
        self,
        call: ToolCall,
        definition: Any,
        policy: ToolPolicy,
    ) -> ToolResult | None:
        if not (
            policy.require_approval_for_side_effects
            and (definition.requires_approval or _has_side_effects(definition.side_effect))
        ):
            return None

        reason = f"Tool requires approval before execution: {definition.name}"
        approval_id = None
        if self._approval_store is not None:
            request = ToolApprovalRequest(
                tool_call=call,
                tool_name=definition.name,
                side_effect=definition.side_effect,
                reason=reason,
                risk_level=_risk_level(definition),
                run_id=self._run_id,
                agent_id=call.requested_by_agent_id or None,
            )
            approval_id = self._approval_store.upsert_approval(
                request.to_worker_approval_request()
            ).approval_id

        return ToolResult(
            status=ToolStatus.APPROVAL_REQUIRED,
            output_summary=reason,
            approval_id=approval_id,
        )


def _result_event_payload(observation: ToolObservation) -> dict[str, Any]:
    return {
        "status": observation.status.value,
        "elapsed_ms": observation.elapsed_ms,
        "error_type": observation.result.error_type,
        "error_message": observation.result.error_message,
        "output_bytes": observation.result.output_bytes,
        "artifact_refs": [artifact_ref.to_dict() for artifact_ref in observation.result.artifact_refs],
    }


def _execution_record(
    observation: ToolObservation,
    events: list[ToolEvent],
    started_at: datetime,
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
        guardrails_passed=observation.status != ToolStatus.BLOCKED,
        approval_required=observation.status == ToolStatus.APPROVAL_REQUIRED,
        approval_id=observation.result.approval_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        events=call_events,
    )


def _dangerous_gate(definition: Any, policy: ToolPolicy) -> ToolResult | None:
    if definition.is_dangerous and not policy.allow_dangerous_tools:
        return ToolResult(
            status=ToolStatus.BLOCKED,
            error_type="ToolPermissionError",
            error_message=f"dangerous tool is not allowed: {definition.name}",
        )
    return None


def _has_side_effects(side_effect: str) -> bool:
    return side_effect not in {"", "none", "read_only"}


def _risk_level(definition: Any) -> str:
    if definition.is_dangerous or definition.side_effect == "destructive":
        return "critical"
    if definition.side_effect in {"publishing", "writes_external_state", "external_write"}:
        return "high"
    if definition.side_effect in {"writes_local_state", "local_write"}:
        return "medium"
    if definition.requires_approval:
        return "medium"
    return "low"


def _timeout_seconds(definition: Any, policy: ToolPolicy) -> float | None:
    if definition.timeout_seconds is not None:
        return definition.timeout_seconds
    return policy.timeout_seconds_default


def _max_attempts(definition: Any, policy: ToolPolicy) -> int:
    attempts = definition.max_attempts
    if attempts is None:
        attempts = policy.max_attempts_default
    return max(1, int(attempts))


def _arguments_with_secrets(
    arguments: dict[str, Any],
    definition: Any,
    secret_provider: SecretProvider | None,
) -> dict[str, Any]:
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
) -> Any:
    for attempt in range(1, max_attempts + 1):
        try:
            return _invoke_with_timeout(executor, arguments, timeout_seconds, tool_name)
        except Exception:
            if attempt == max_attempts:
                raise
    raise RuntimeError(f"tool {tool_name} retry loop exited unexpectedly")


def _invoke_with_timeout(
    executor: Any,
    arguments: dict[str, Any],
    timeout_seconds: float | None,
    tool_name: str,
) -> Any:
    if timeout_seconds is None or timeout_seconds <= 0:
        return executor(arguments)

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="news-tool")
    future = pool.submit(executor, arguments)
    timed_out = False
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        timed_out = True
        future.cancel()
        raise ToolTimeoutError(
            f"tool {tool_name} exceeded timeout of {timeout_seconds:g} seconds"
        ) from exc
    finally:
        pool.shutdown(wait=not timed_out, cancel_futures=True)


def _json_size_bytes(value: Any) -> int:
    return len(json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value
