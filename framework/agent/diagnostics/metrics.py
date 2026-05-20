from __future__ import annotations

from typing import Any

from framework.agent.models import AgentLoopMetrics
from framework.agent.runtime.llm import TokenUsage


def metrics_from_trace(trace: Any) -> AgentLoopMetrics:
    payload = trace.to_dict() if hasattr(trace, "to_dict") else trace
    if not isinstance(payload, dict):
        return AgentLoopMetrics()
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    metrics = AgentLoopMetrics(
        iterations=int(summary.get("iterations") or 0),
        llm_calls=int(summary.get("llm_calls") or 0),
        tool_calls=int(summary.get("tool_calls") or 0),
        parser_errors=int(summary.get("parser_errors") or 0),
        judge_retries=int(summary.get("judge_retry_count") or summary.get("judge_retries") or 0),
    )
    token_usage = summary.get("token_usage")
    if isinstance(token_usage, dict):
        metrics.token_usage = TokenUsage.from_any(token_usage)
    return metrics


AgentLoopMetrics.from_trace = staticmethod(metrics_from_trace)  # type: ignore[attr-defined]

__all__ = ["AgentLoopMetrics", "metrics_from_trace"]
