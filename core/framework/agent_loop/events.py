from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.framework.agent_loop.models import AgentLoopEventType


@dataclass(frozen=True)
class AgentLoopEvent:
    event_type: AgentLoopEventType
    agent_id: str
    iteration: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "event_type": self.event_type.value,
            "agent_id": self.agent_id,
        }
        if self.iteration is not None:
            result["iteration"] = self.iteration
        result.update(dict(self.payload))
        return result


class AgentLoopEventRecorder:
    def __init__(self, *, agent_id: str) -> None:
        self.agent_id = agent_id
        self._events: list[AgentLoopEvent] = []

    def emit(
        self,
        event_type: AgentLoopEventType,
        *,
        iteration: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = AgentLoopEvent(
            event_type=event_type,
            agent_id=self.agent_id,
            iteration=iteration,
            payload=dict(payload or {}),
        )
        self._events.append(event)
        return event.to_dict()

    def started(self) -> None:
        self.emit(AgentLoopEventType.AGENT_STARTED)

    def iteration_started(
        self,
        *,
        iteration: int,
        feedback: str | None,
        tool_observation_count: int,
        tools_available: list[str],
    ) -> None:
        self.emit(
            AgentLoopEventType.ITERATION_STARTED,
            iteration=iteration,
            payload={
                "feedback": feedback,
                "tool_observation_count": tool_observation_count,
                "tools_available": list(tools_available),
            },
        )

    def llm_call(
        self,
        *,
        iteration: int,
        token_usage: dict[str, Any],
        response_chars: int,
        provider: str | None = None,
        model: str | None = None,
        route_id: str | None = None,
        deployment_id: str | None = None,
        fallback_used: bool | None = None,
        fallback_count: int | None = None,
        router_event_count: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "token_usage": dict(token_usage),
            "response_chars": response_chars,
        }
        if provider:
            payload["provider"] = provider
        if model:
            payload["model"] = model
        if route_id:
            payload["route_id"] = route_id
        if deployment_id:
            payload["deployment_id"] = deployment_id
        if fallback_used is not None:
            payload["fallback_used"] = fallback_used
        if fallback_count is not None:
            payload["fallback_count"] = fallback_count
        if router_event_count is not None:
            payload["router_event_count"] = router_event_count
        self.emit(AgentLoopEventType.LLM_CALL, iteration=iteration, payload=payload)

    def llm_stream_event(
        self,
        *,
        iteration: int,
        stream_event: dict[str, Any],
        sequence: int,
    ) -> None:
        event_type = str(stream_event.get("event_type") or "")
        payload: dict[str, Any] = {
            "sequence": sequence,
            "stream_event_type": event_type,
            "stream_event": dict(stream_event),
        }
        text_delta = stream_event.get("text_delta")
        if isinstance(text_delta, str):
            payload["text_delta_chars"] = len(text_delta)
        self.emit(AgentLoopEventType.LLM_STREAM_EVENT, iteration=iteration, payload=payload)

    def llm_failed(self, *, iteration: int, exc: Exception) -> None:
        self.emit(
            AgentLoopEventType.LLM_CALL_FAILED,
            iteration=iteration,
            payload={
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )

    def action_parsed(
        self,
        *,
        iteration: int,
        action_type: str,
        tool_name: str | None = None,
        output_keys: list[str] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "action_type": action_type,
            "output_keys": list(output_keys or []),
        }
        if tool_name:
            payload["tool_name"] = tool_name
        self.emit(AgentLoopEventType.ACTION_PARSED, iteration=iteration, payload=payload)

    def parser_error(
        self,
        *,
        iteration: int,
        error_type: str,
        error_message: str,
        parser_errors: int,
        max_parser_errors: int,
    ) -> None:
        self.emit(
            AgentLoopEventType.PARSER_ERROR,
            iteration=iteration,
            payload={
                "error_type": error_type,
                "error_message": error_message,
                "parser_errors": parser_errors,
                "max_parser_errors": max_parser_errors,
            },
        )

    def tool_call(self, *, iteration: int, tool_name: str, call_id: str) -> None:
        self.emit(
            AgentLoopEventType.TOOL_CALL,
            iteration=iteration,
            payload={
                "tool_name": tool_name,
                "call_id": call_id,
            },
        )

    def tool_observation(
        self,
        *,
        iteration: int,
        observation: dict[str, Any],
    ) -> None:
        self.emit(
            AgentLoopEventType.TOOL_OBSERVATION,
            iteration=iteration,
            payload={"observation": dict(observation)},
        )

    def tool_budget_blocked(
        self,
        *,
        iteration: int,
        tool_name: str,
        max_tool_calls: int,
    ) -> None:
        self.emit(
            AgentLoopEventType.TOOL_BUDGET_BLOCKED,
            iteration=iteration,
            payload={
                "tool_name": tool_name,
                "max_tool_calls_per_agent": max_tool_calls,
            },
        )

    def tool_approval_required(
        self,
        *,
        iteration: int,
        tool_name: str,
        approval_id: str | None,
    ) -> None:
        self.emit(
            AgentLoopEventType.TOOL_APPROVAL_REQUIRED,
            iteration=iteration,
            payload={
                "tool_name": tool_name,
                "approval_id": approval_id,
            },
        )

    def repeated_tool_call_detected(
        self,
        *,
        iteration: int,
        tool_name: str,
        signature: str,
        count: int,
        limit: int,
    ) -> None:
        self.emit(
            AgentLoopEventType.REPEATED_TOOL_CALL_DETECTED,
            iteration=iteration,
            payload={
                "tool_name": tool_name,
                "signature": signature,
                "count": count,
                "limit": limit,
            },
        )

    def judge_accept(self, *, iteration: int, verdict: dict[str, Any]) -> None:
        self.emit(
            AgentLoopEventType.JUDGE_ACCEPT,
            iteration=iteration,
            payload={"verdict": dict(verdict)},
        )

    def judge_retry(
        self,
        *,
        iteration: int,
        feedback: str,
        verdict: dict[str, Any],
        via_tool: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "feedback": feedback,
            "verdict": dict(verdict),
        }
        if via_tool:
            payload["via_tool"] = via_tool
        self.emit(AgentLoopEventType.JUDGE_RETRY, iteration=iteration, payload=payload)

    def judge_block(
        self,
        *,
        iteration: int,
        verdict: dict[str, Any],
        via_tool: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"verdict": dict(verdict)}
        if via_tool:
            payload["via_tool"] = via_tool
        self.emit(AgentLoopEventType.JUDGE_BLOCK, iteration=iteration, payload=payload)

    def final_output(
        self,
        *,
        iteration: int,
        output_keys: list[str],
        via_tool: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"output_keys": sorted(output_keys)}
        if via_tool:
            payload["via_tool"] = via_tool
        self.emit(AgentLoopEventType.FINAL_OUTPUT, iteration=iteration, payload=payload)

    def completed(
        self,
        *,
        iteration: int,
        status: str,
        stop_reason: str,
    ) -> None:
        self.emit(
            AgentLoopEventType.AGENT_COMPLETED,
            iteration=iteration,
            payload={"status": status, "stop_reason": stop_reason},
        )

    def waiting_for_approval(
        self,
        *,
        iteration: int,
        stop_reason: str,
        approval_id: str | None,
        approval_kind: str = "tool_approval",
        tool_name: str | None = None,
        control_action: str | None = None,
        escalation_type: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "stop_reason": stop_reason,
            "approval_id": approval_id,
            "approval_kind": approval_kind,
        }
        if tool_name:
            payload["tool_name"] = tool_name
        if control_action:
            payload["control_action"] = control_action
        if escalation_type:
            payload["escalation_type"] = escalation_type
        self.emit(
            AgentLoopEventType.AGENT_WAITING_FOR_APPROVAL,
            iteration=iteration,
            payload=payload,
        )

    def blocked(self, *, iteration: int, stop_reason: str, verdict: dict[str, Any] | None) -> None:
        self.emit(
            AgentLoopEventType.AGENT_BLOCKED,
            iteration=iteration,
            payload={"stop_reason": stop_reason, "verdict": verdict},
        )

    def stalled(self, *, iteration: int, stop_reason: str, summary: str) -> None:
        self.emit(
            AgentLoopEventType.AGENT_STALLED,
            iteration=iteration,
            payload={"stop_reason": stop_reason, "summary": summary},
        )

    def retry_exhausted(
        self,
        *,
        iteration: int,
        stop_reason: str,
        verdict: dict[str, Any] | None,
    ) -> None:
        self.emit(
            AgentLoopEventType.AGENT_RETRY_EXHAUSTED,
            iteration=iteration,
            payload={"stop_reason": stop_reason, "verdict": verdict},
        )

    def failed(self, *, iteration: int, stop_reason: str, error: str) -> None:
        self.emit(
            AgentLoopEventType.AGENT_FAILED,
            iteration=iteration,
            payload={"stop_reason": stop_reason, "error": error},
        )

    def to_dicts(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self._events]


def event_type_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        event_type = str(event.get("event_type") or "")
        counts[event_type] = counts.get(event_type, 0) + 1
    return counts
