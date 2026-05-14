from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from core.framework.agent_loop.models import JudgeVerdict
from core.framework.llm import LLMResponse, TokenUsage
from core.framework.serialization import to_json_safe
from core.framework.tools import ToolObservation
from core.framework.tools.redaction import redact_sensitive_values


@dataclass(frozen=True)
class ToolCallSignature:
    tool_name: str
    arguments_hash: str
    arguments_preview: dict[str, Any]

    @classmethod
    def from_call(
        cls,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        max_preview_chars: int,
    ) -> ToolCallSignature:
        safe_arguments = redact_sensitive_values(dict(arguments))
        encoded = _stable_json_bytes(safe_arguments)
        return cls(
            tool_name=tool_name,
            arguments_hash=hashlib.sha256(encoded).hexdigest(),
            arguments_preview=_preview_mapping(safe_arguments, max_preview_chars),
        )

    @property
    def key(self) -> str:
        return f"{self.tool_name}:{self.arguments_hash}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments_hash": self.arguments_hash,
            "arguments_preview": dict(self.arguments_preview),
        }


@dataclass(frozen=True)
class LLMCallTrace:
    iteration: int
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    provider: str | None = None
    model: str | None = None
    route_id: str | None = None
    deployment_id: str | None = None
    cache_hit: bool | None = None
    fallback_used: bool | None = None
    fallback_count: int | None = None
    router_event_count: int | None = None
    provider_resolution_trace: list[dict[str, Any]] = field(default_factory=list)
    route_manifest: dict[str, Any] | None = None
    response_chars: int = 0

    @classmethod
    def from_response(cls, iteration: int, response: LLMResponse) -> LLMCallTrace:
        metadata = dict(response.metadata)
        usage = response.usage
        return cls(
            iteration=iteration,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            provider=_optional_text(metadata.get("provider") or metadata.get("llm_provider")),
            model=_optional_text(metadata.get("model") or metadata.get("llm_model")),
            route_id=_optional_text(metadata.get("llm_route_id")),
            deployment_id=_optional_text(metadata.get("llm_deployment_id")),
            cache_hit=_optional_bool(metadata.get("llm_cache_hit")),
            fallback_used=_optional_bool(metadata.get("llm_fallback_used")),
            fallback_count=_optional_int(metadata.get("llm_fallback_count")),
            router_event_count=_optional_int(metadata.get("llm_router_event_count")),
            provider_resolution_trace=[
                dict(item)
                for item in metadata.get("llm_provider_resolution_trace", [])
                if isinstance(item, dict)
            ],
            route_manifest=(
                dict(metadata["llm_route_manifest"])
                if isinstance(metadata.get("llm_route_manifest"), dict)
                else None
            ),
            response_chars=len(response.content or ""),
        )

    def token_usage(self) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "provider": self.provider,
            "model": self.model,
            "route_id": self.route_id,
            "deployment_id": self.deployment_id,
            "cache_hit": self.cache_hit,
            "fallback_used": self.fallback_used,
            "fallback_count": self.fallback_count,
            "router_event_count": self.router_event_count,
            "provider_resolution_trace": [
                dict(item) for item in self.provider_resolution_trace
            ],
            "route_manifest": dict(self.route_manifest) if self.route_manifest else None,
            "response_chars": self.response_chars,
        }


@dataclass(frozen=True)
class LLMErrorTrace:
    iteration: int
    error_type: str
    error_message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


@dataclass(frozen=True)
class ParserErrorTrace:
    iteration: int
    error_type: str
    error_message: str
    content_preview: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "content_preview": self.content_preview,
        }


@dataclass(frozen=True)
class ParsedActionTrace:
    iteration: int
    action_type: str
    tool_name: str | None = None
    output_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "action_type": self.action_type,
            "tool_name": self.tool_name,
            "output_keys": list(self.output_keys),
        }


@dataclass(frozen=True)
class ToolCallTrace:
    iteration: int
    tool_call_id: str
    tool_name: str
    status: str
    summary: str
    elapsed_ms: float
    signature: ToolCallSignature
    error_type: str | None = None
    error_message: str | None = None
    output_bytes: int | None = None
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    safe_for_llm: bool = True

    @classmethod
    def from_observation(
        cls,
        *,
        iteration: int,
        observation: ToolObservation,
        max_preview_chars: int,
    ) -> ToolCallTrace:
        return cls(
            iteration=iteration,
            tool_call_id=observation.call.call_id,
            tool_name=observation.call.tool_name,
            status=observation.status.value,
            summary=observation.summary,
            elapsed_ms=observation.elapsed_ms,
            signature=ToolCallSignature.from_call(
                tool_name=observation.call.tool_name,
                arguments=observation.call.arguments,
                max_preview_chars=max_preview_chars,
            ),
            error_type=observation.result.error_type,
            error_message=observation.result.error_message,
            output_bytes=observation.result.output_bytes,
            artifact_refs=[
                artifact_ref.to_dict()
                for artifact_ref in observation.result.artifact_refs
            ],
            safe_for_llm=observation.safe_for_llm,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "summary": self.summary,
            "elapsed_ms": self.elapsed_ms,
            "signature": self.signature.to_dict(),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "output_bytes": self.output_bytes,
            "artifact_refs": [dict(ref) for ref in self.artifact_refs],
            "safe_for_llm": self.safe_for_llm,
        }


@dataclass(frozen=True)
class JudgeTrace:
    iteration: int
    decision: str
    confidence: float
    feedback: str | None = None
    missing_output_keys: list[str] = field(default_factory=list)
    schema_errors: list[str] = field(default_factory=list)
    quality_errors: list[str] = field(default_factory=list)
    policy_violations: list[str] = field(default_factory=list)

    @classmethod
    def from_verdict(cls, iteration: int, verdict: JudgeVerdict) -> JudgeTrace:
        return cls(
            iteration=iteration,
            decision=verdict.decision.value,
            confidence=verdict.confidence,
            feedback=verdict.feedback,
            missing_output_keys=list(verdict.missing_output_keys),
            schema_errors=list(verdict.schema_errors),
            quality_errors=list(verdict.quality_errors),
            policy_violations=list(verdict.policy_violations),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "decision": self.decision,
            "confidence": self.confidence,
            "feedback": self.feedback,
            "missing_output_keys": list(self.missing_output_keys),
            "schema_errors": list(self.schema_errors),
            "quality_errors": list(self.quality_errors),
            "policy_violations": list(self.policy_violations),
        }


@dataclass
class IterationTrace:
    iteration: int
    feedback: str | None = None
    tool_observation_count_before: int = 0
    tools_available: list[str] = field(default_factory=list)
    llm_call: LLMCallTrace | None = None
    llm_error: LLMErrorTrace | None = None
    parser_error: ParserErrorTrace | None = None
    parsed_action: ParsedActionTrace | None = None
    tool_call: ToolCallTrace | None = None
    judge: JudgeTrace | None = None
    stop_candidate: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "feedback": self.feedback,
            "tool_observation_count_before": self.tool_observation_count_before,
            "tools_available": list(self.tools_available),
            "llm_call": self.llm_call.to_dict() if self.llm_call else None,
            "llm_error": self.llm_error.to_dict() if self.llm_error else None,
            "parser_error": self.parser_error.to_dict() if self.parser_error else None,
            "parsed_action": self.parsed_action.to_dict() if self.parsed_action else None,
            "tool_call": self.tool_call.to_dict() if self.tool_call else None,
            "judge": self.judge.to_dict() if self.judge else None,
            "stop_candidate": self.stop_candidate,
        }


@dataclass
class AgentLoopTrace:
    agent_id: str
    iterations: list[IterationTrace] = field(default_factory=list)
    llm_calls: list[LLMCallTrace] = field(default_factory=list)
    llm_errors: list[LLMErrorTrace] = field(default_factory=list)
    parser_errors: list[ParserErrorTrace] = field(default_factory=list)
    actions: list[ParsedActionTrace] = field(default_factory=list)
    tool_calls: list[ToolCallTrace] = field(default_factory=list)
    judges: list[JudgeTrace] = field(default_factory=list)

    def start_iteration(
        self,
        iteration: int,
        *,
        feedback: str | None,
        tool_observation_count_before: int,
        tools_available: list[str],
    ) -> IterationTrace:
        item = IterationTrace(
            iteration=iteration,
            feedback=feedback,
            tool_observation_count_before=tool_observation_count_before,
            tools_available=list(tools_available),
        )
        self.iterations.append(item)
        return item

    def record_llm_call(self, iteration: IterationTrace, response: LLMResponse) -> LLMCallTrace:
        trace = LLMCallTrace.from_response(iteration.iteration, response)
        iteration.llm_call = trace
        self.llm_calls.append(trace)
        return trace

    def record_llm_error(self, iteration: IterationTrace, exc: Exception) -> LLMErrorTrace:
        trace = LLMErrorTrace(
            iteration=iteration.iteration,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        iteration.llm_error = trace
        self.llm_errors.append(trace)
        return trace

    def record_parser_error(
        self,
        iteration: IterationTrace,
        *,
        exc: Exception,
        content: str,
        max_preview_chars: int,
    ) -> ParserErrorTrace:
        trace = ParserErrorTrace(
            iteration=iteration.iteration,
            error_type=type(exc).__name__,
            error_message=str(exc),
            content_preview=_preview_text(content, max_preview_chars),
        )
        iteration.parser_error = trace
        self.parser_errors.append(trace)
        return trace

    def record_action(
        self,
        iteration: IterationTrace,
        *,
        action_type: str,
        tool_name: str | None = None,
        output: dict[str, Any] | None = None,
    ) -> ParsedActionTrace:
        trace = ParsedActionTrace(
            iteration=iteration.iteration,
            action_type=action_type,
            tool_name=tool_name,
            output_keys=sorted((output or {}).keys()),
        )
        iteration.parsed_action = trace
        self.actions.append(trace)
        return trace

    def record_tool_call(
        self,
        iteration: IterationTrace,
        observation: ToolObservation,
        *,
        max_preview_chars: int,
    ) -> ToolCallTrace:
        trace = ToolCallTrace.from_observation(
            iteration=iteration.iteration,
            observation=observation,
            max_preview_chars=max_preview_chars,
        )
        iteration.tool_call = trace
        self.tool_calls.append(trace)
        return trace

    def record_judge(self, iteration: IterationTrace, verdict: JudgeVerdict) -> JudgeTrace:
        trace = JudgeTrace.from_verdict(iteration.iteration, verdict)
        iteration.judge = trace
        self.judges.append(trace)
        return trace

    def mark_stop_candidate(self, iteration: IterationTrace, reason: str) -> None:
        iteration.stop_candidate = reason

    def count_tool_signature(self, signature_key: str) -> int:
        return sum(1 for call in self.tool_calls if call.signature.key == signature_key)

    def consecutive_parser_errors(self) -> int:
        count = 0
        for iteration in reversed(self.iterations):
            if iteration.parser_error is None:
                break
            count += 1
        return count

    def consecutive_tool_failures(self) -> int:
        count = 0
        for call in reversed(self.tool_calls):
            if call.status not in {"failed", "timeout", "blocked"}:
                break
            count += 1
        return count

    def consecutive_judge_retries(self) -> int:
        count = 0
        for judge in reversed(self.judges):
            if judge.decision != "retry":
                break
            count += 1
        return count

    def summary(self) -> dict[str, Any]:
        repeated_signatures = {}
        for call in self.tool_calls:
            repeated_signatures[call.signature.key] = repeated_signatures.get(call.signature.key, 0) + 1
        repeated_tool_calls = [
            {
                "signature": signature,
                "count": count,
            }
            for signature, count in sorted(repeated_signatures.items())
            if count > 1
        ]
        return {
            "agent_id": self.agent_id,
            "iteration_count": len(self.iterations),
            "llm_call_count": len(self.llm_calls),
            "llm_error_count": len(self.llm_errors),
            "parser_error_count": len(self.parser_errors),
            "action_count": len(self.actions),
            "tool_call_count": len(self.tool_calls),
            "judge_count": len(self.judges),
            "judge_retry_count": sum(1 for judge in self.judges if judge.decision == "retry"),
            "tool_status_counts": self.tool_status_counts(),
            "repeated_tool_calls": repeated_tool_calls,
        }

    def tool_status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for call in self.tool_calls:
            counts[call.status] = counts.get(call.status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "iterations": [iteration.to_dict() for iteration in self.iterations],
            "summary": self.summary(),
        }


def _stable_json_bytes(value: Any) -> bytes:
    return json.dumps(
        to_json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _preview_mapping(value: Any, max_chars: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"value": _preview_text(str(value), max_chars)}
    preview: dict[str, Any] = {}
    remaining = max(0, max_chars)
    for key, item in value.items():
        if remaining <= 0:
            preview[str(key)] = "...truncated..."
            break
        preview_value = _preview_value(item, remaining)
        preview[str(key)] = preview_value
        remaining -= len(str(preview_value))
    return preview


def _preview_value(value: Any, max_chars: int) -> Any:
    safe_value = redact_sensitive_values(value)
    if isinstance(safe_value, dict):
        return _preview_mapping(safe_value, max_chars)
    if isinstance(safe_value, list):
        items = []
        remaining = max_chars
        for item in safe_value[:5]:
            if remaining <= 0:
                items.append("...truncated...")
                break
            preview = _preview_value(item, remaining)
            items.append(preview)
            remaining -= len(str(preview))
        if len(safe_value) > len(items):
            items.append(f"...{len(safe_value) - len(items)} more item(s)")
        return items
    return _preview_text(str(safe_value), max_chars)


def _preview_text(value: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    if max_chars <= 3:
        return value[:max_chars]
    return f"{value[: max_chars - 3]}..."


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
