from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.framework.llm import TokenUsage
from core.framework.tools import ToolPolicy


class AgentLoopStatus(str, Enum):
    ACCEPTED = "accepted"
    RETRY_EXHAUSTED = "retry_exhausted"
    BLOCKED = "blocked"
    FAILED = "failed"


class JudgeDecision(str, Enum):
    ACCEPT = "accept"
    RETRY = "retry"
    BLOCK = "block"


@dataclass(frozen=True)
class AgentLoopPolicy:
    max_iterations: int = 5
    max_judge_retries: int = 2
    stop_on_first_valid_output: bool = True


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    name: str
    role: str
    goal: str
    instructions: str
    input_keys: list[str]
    output_key: str
    allowed_tools: list[str] = field(default_factory=list)
    loop_policy: AgentLoopPolicy = field(default_factory=AgentLoopPolicy)
    tool_policy: ToolPolicy | None = None
    system_prompt_template: str = "{role}\n{instructions}"
    task_prompt_template: str = "Goal: {goal}\nInputs: {inputs}"
    allowed_sources: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def resolved_tool_policy(self) -> ToolPolicy:
        if self.tool_policy:
            return self.tool_policy
        return ToolPolicy(allowed_tools=list(self.allowed_tools), require_explicit_allowlist=True)


@dataclass(frozen=True)
class AgentAction:
    action_type: str
    output: dict[str, Any] | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "output": self.output,
            "tool_name": self.tool_name,
            "tool_args": dict(self.tool_args),
        }


@dataclass(frozen=True)
class JudgeVerdict:
    decision: JudgeDecision
    confidence: float = 0.0
    feedback: str | None = None
    missing_output_keys: list[str] = field(default_factory=list)
    schema_errors: list[str] = field(default_factory=list)
    quality_errors: list[str] = field(default_factory=list)
    policy_violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "confidence": self.confidence,
            "feedback": self.feedback,
            "missing_output_keys": list(self.missing_output_keys),
            "schema_errors": list(self.schema_errors),
            "quality_errors": list(self.quality_errors),
            "policy_violations": list(self.policy_violations),
        }


@dataclass
class AgentLoopMetrics:
    llm_calls: int = 0
    tool_calls: int = 0
    token_usage: TokenUsage = field(default_factory=TokenUsage)

    def add_usage(self, usage: TokenUsage) -> None:
        self.token_usage = TokenUsage(
            input_tokens=self.token_usage.input_tokens + usage.input_tokens,
            output_tokens=self.token_usage.output_tokens + usage.output_tokens,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "token_usage": self.token_usage.to_dict(),
        }


@dataclass(frozen=True)
class AgentLoopResult:
    success: bool
    status: AgentLoopStatus
    output: dict[str, Any] = field(default_factory=dict)
    verdict: JudgeVerdict | None = None
    iterations: int = 0
    metrics: AgentLoopMetrics = field(default_factory=AgentLoopMetrics)
    events: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status.value,
            "output": self.output,
            "verdict": self.verdict.to_dict() if self.verdict else None,
            "iterations": self.iterations,
            "metrics": self.metrics.to_dict(),
            "events": [dict(event) for event in self.events],
            "error": self.error,
        }
