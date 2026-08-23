from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.agent.models.action import AgentAction
from framework.agent.models.status import AgentLoopDiagnosticSeverity, AgentLoopStatus, AgentLoopStopReason, JudgeDecision
from framework.llm.models import TokenUsage
from framework.shared.result import ErrorDetail


@dataclass(frozen=True)
class JudgeVerdict:
    decision: JudgeDecision
    confidence: float = 0.0
    feedback: str | None = None
    missing_output_keys: list[str] = field(default_factory=list)
    schema_errors: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    policy_violations: list[str] = field(default_factory=list)
    structured_output_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    structured_output_contract: dict[str, Any] | None = None
    response_fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "confidence": self.confidence,
            "feedback": self.feedback,
            "missing_output_keys": list(self.missing_output_keys),
            "schema_errors": list(self.schema_errors),
            "validation_errors": list(self.validation_errors),
            "policy_violations": list(self.policy_violations),
            "structured_output_diagnostics": [
                dict(item) for item in self.structured_output_diagnostics
            ],
            "structured_output_contract": (
                dict(self.structured_output_contract)
                if self.structured_output_contract is not None
                else None
            ),
            "response_fingerprint": self.response_fingerprint,
        }


@dataclass(frozen=True)
class AgentLoopIssue:
    code: str
    message: str
    severity: AgentLoopDiagnosticSeverity = AgentLoopDiagnosticSeverity.INFO
    iteration: int | None = None
    tool_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "iteration": self.iteration,
            "tool_name": self.tool_name,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AgentLoopDiagnostics:
    agent_id: str
    status: AgentLoopStatus
    stop_reason: AgentLoopStopReason
    summary: str
    healthy: bool
    severity: AgentLoopDiagnosticSeverity
    iterations: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    parser_errors: int = 0
    judge_retries: int = 0
    tool_failures: int = 0
    tool_blocks: int = 0
    approval_requests: int = 0
    repeated_tool_calls: int = 0
    issues: list[AgentLoopIssue] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    trace_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "status": self.status.value,
            "stop_reason": self.stop_reason.value,
            "summary": self.summary,
            "healthy": self.healthy,
            "severity": self.severity.value,
            "iterations": self.iterations,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "parser_errors": self.parser_errors,
            "judge_retries": self.judge_retries,
            "tool_failures": self.tool_failures,
            "tool_blocks": self.tool_blocks,
            "approval_requests": self.approval_requests,
            "repeated_tool_calls": self.repeated_tool_calls,
            "issues": [issue.to_dict() for issue in self.issues],
            "suggestions": list(self.suggestions),
            "trace_summary": dict(self.trace_summary),
        }


@dataclass
class AgentLoopMetrics:
    iterations: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    parser_errors: int = 0
    judge_retries: int = 0
    judge_accepts: int = 0
    judge_blocks: int = 0
    tool_successes: int = 0
    tool_failures: int = 0
    tool_blocks: int = 0
    tool_timeouts: int = 0
    tool_approval_requests: int = 0
    repeated_tool_calls: int = 0
    stalled_iterations: int = 0
    llm_error_count: int = 0
    llm_stream_event_count: int = 0
    structured_output_repairs: int = 0
    structured_output_validation_accepts: int = 0
    structured_output_repair_budget_exhausted: int = 0
    total_tool_elapsed_ms: float = 0.0
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    global_budget_check: dict[str, Any] | None = None
    global_budget_usage: dict[str, Any] | None = None

    def add_usage(self, usage: TokenUsage) -> None:
        self.token_usage = TokenUsage(
            input_tokens=self.token_usage.input_tokens + usage.input_tokens,
            output_tokens=self.token_usage.output_tokens + usage.output_tokens,
        )

    def record_tool_status(self, status: Any, *, elapsed_ms: float = 0.0) -> None:
        status_value = getattr(status, "value", str(status))
        if status_value == "succeeded":
            self.tool_successes += 1
        elif status_value == "failed":
            self.tool_failures += 1
        elif status_value == "blocked":
            self.tool_blocks += 1
        elif status_value == "timeout":
            self.tool_timeouts += 1
        elif status_value == "approval_required":
            self.tool_approval_requests += 1
        self.total_tool_elapsed_ms += elapsed_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "iterations": self.iterations,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "parser_errors": self.parser_errors,
            "judge_retries": self.judge_retries,
            "judge_accepts": self.judge_accepts,
            "judge_blocks": self.judge_blocks,
            "tool_successes": self.tool_successes,
            "tool_failures": self.tool_failures,
            "tool_blocks": self.tool_blocks,
            "tool_timeouts": self.tool_timeouts,
            "tool_approval_requests": self.tool_approval_requests,
            "repeated_tool_calls": self.repeated_tool_calls,
            "stalled_iterations": self.stalled_iterations,
            "llm_error_count": self.llm_error_count,
            "llm_stream_event_count": self.llm_stream_event_count,
            "structured_output_repairs": self.structured_output_repairs,
            "structured_output_validation_accepts": (
                self.structured_output_validation_accepts
            ),
            "structured_output_repair_budget_exhausted": (
                self.structured_output_repair_budget_exhausted
            ),
            "total_tool_elapsed_ms": self.total_tool_elapsed_ms,
            "token_usage": self.token_usage.to_dict(),
            "global_budget_check": self.global_budget_check,
            "global_budget_usage": self.global_budget_usage,
        }


@dataclass(frozen=True)
class LLMCallArtifact:
    artifact_id: str
    iteration: int
    request: dict[str, Any]
    response: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "iteration": self.iteration,
            "request": dict(self.request),
            "response": dict(self.response),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AgentLoopResult:
    success: bool
    status: AgentLoopStatus
    output: dict[str, Any] = field(default_factory=dict)
    actions: list[AgentAction] = field(default_factory=list)
    verdict: JudgeVerdict | None = None
    iterations: int = 0
    metrics: AgentLoopMetrics = field(default_factory=AgentLoopMetrics)
    events: list[dict[str, Any]] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)
    diagnostics: AgentLoopDiagnostics | None = None
    llm_call_artifacts: list[LLMCallArtifact] = field(default_factory=list)
    error: str | ErrorDetail | None = None
    trajectory: list[Any] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    memory_ops: list[dict[str, Any]] = field(default_factory=list)
    memory_candidates: list[dict[str, Any]] = field(default_factory=list)
    termination_reason: str | None = None
    max_steps_reached: bool = False
    trace_id: str | None = None
    trace_ref: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def final_output(self) -> str | dict[str, Any] | None:
        if "final_output" in self.output:
            value = self.output["final_output"]
            return value if isinstance(value, (str, dict)) or value is None else str(value)
        return self.output or None

    def to_dict(self) -> dict[str, Any]:
        termination_reason = self.termination_reason
        if termination_reason is None and self.diagnostics is not None:
            termination_reason = self.diagnostics.stop_reason.value
        trace_id = self.trace_id
        if trace_id is None:
            raw_trace_id = self.trace.get("trace_id")
            trace_id = str(raw_trace_id) if raw_trace_id is not None else None
        return {
            "success": self.success,
            "status": self.status.value,
            "output": self.output,
            "final_output": self.final_output,
            "actions": [action.to_dict() for action in self.actions],
            "verdict": self.verdict.to_dict() if self.verdict else None,
            "iterations": self.iterations,
            "metrics": self.metrics.to_dict(),
            "events": [dict(event) for event in self.events],
            "trace": dict(self.trace),
            "diagnostics": self.diagnostics.to_dict() if self.diagnostics else None,
            "llm_call_artifacts": [
                artifact.to_dict() for artifact in self.llm_call_artifacts
            ],
            "error": self.error.to_dict() if isinstance(self.error, ErrorDetail) else self.error,
            "trajectory": [_trace_item_to_dict(item) for item in self.trajectory],
            "tool_calls": [dict(item) for item in self.tool_calls],
            "memory_ops": [dict(item) for item in self.memory_ops],
            "memory_candidates": [dict(item) for item in self.memory_candidates],
            "termination_reason": termination_reason,
            "max_steps_reached": self.max_steps_reached,
            "trace_id": trace_id,
            "trace_ref": self.trace_ref,
            "warnings": list(self.warnings),
        }

    @classmethod
    def success_result(
        cls,
        agent_id: str,
        output: Any,
        actions: list[AgentAction] | None = None,
    ) -> "AgentLoopResult":
        normalized_output = output if isinstance(output, dict) else {"final_output": output}
        return cls(
            success=True,
            status=AgentLoopStatus.SUCCEEDED,
            output=dict(normalized_output),
            actions=list(actions or []),
            diagnostics=AgentLoopDiagnostics(
                agent_id=agent_id,
                status=AgentLoopStatus.SUCCEEDED,
                stop_reason=AgentLoopStopReason.FINAL_ANSWER,
                summary="agent completed successfully",
                healthy=True,
                severity=AgentLoopDiagnosticSeverity.OK,
            ),
        )

    @classmethod
    def failure_result(
        cls,
        agent_id: str,
        error: Exception | ErrorDetail,
    ) -> "AgentLoopResult":
        detail = error if isinstance(error, ErrorDetail) else ErrorDetail.from_exception(error)
        return cls(
            success=False,
            status=AgentLoopStatus.FAILED,
            error=detail,
            diagnostics=AgentLoopDiagnostics(
                agent_id=agent_id,
                status=AgentLoopStatus.FAILED,
                stop_reason=AgentLoopStopReason.UNKNOWN_FAILED,
                summary=detail.message,
                healthy=False,
                severity=AgentLoopDiagnosticSeverity.ERROR,
                issues=[
                    AgentLoopIssue(
                        code=detail.code,
                        message=detail.message,
                        severity=AgentLoopDiagnosticSeverity.ERROR,
                        metadata=dict(detail.details),
                    )
                ],
            ),
        )


def _trace_item_to_dict(item: Any) -> dict[str, Any]:
    to_dict = getattr(item, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
        return dict(value) if isinstance(value, dict) else {"value": value}
    if isinstance(item, dict):
        return dict(item)
    return {"value": item}
