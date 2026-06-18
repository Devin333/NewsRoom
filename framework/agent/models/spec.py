from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.agent.models.policy import AgentLoopPolicy
from framework.tool import ToolPolicy


@dataclass(frozen=True)
class AgentSessionContextPolicy:
    """Controls whether AgentLoop injects shared session context into prompts."""

    enabled: bool = False
    roles: tuple[str, ...] = ()
    max_context_chars: int = 12000
    include_content: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "roles", tuple(str(role) for role in self.roles))
        object.__setattr__(self, "max_context_chars", max(1, int(self.max_context_chars or 12000)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "roles": list(self.roles),
            "max_context_chars": self.max_context_chars,
            "include_content": self.include_content,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "AgentSessionContextPolicy | None":
        if payload is None:
            return None
        return cls(
            enabled=bool(payload.get("enabled", False)),
            roles=tuple(str(item) for item in payload.get("roles", []) or []),
            max_context_chars=int(payload.get("max_context_chars") or 12000),
            include_content=bool(payload.get("include_content", True)),
        )


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    name: str
    instructions: str
    role: str = ""
    goal: str = ""
    input_keys: list[str] = field(default_factory=list)
    output_key: str = "output"
    output_schema: dict[str, Any] | None = None
    allowed_tools: list[str] = field(default_factory=list)
    loop_policy: AgentLoopPolicy = field(default_factory=AgentLoopPolicy)
    tool_policy: ToolPolicy | None = None
    model_route: str | None = None
    tool_names: list[str] = field(default_factory=list)
    memory_enabled: bool = True
    max_iterations: int = 8
    model_policy: dict[str, Any] = field(default_factory=dict)
    validation_policy: dict[str, Any] = field(default_factory=dict)
    system_prompt_template: str = "{role}\n{instructions}"
    task_prompt_template: str = "Goal: {goal}\nInputs: {inputs}"
    allowed_references: list[str] = field(default_factory=list)
    allowed_subagents: list[str] = field(default_factory=list)
    session_context_policy: AgentSessionContextPolicy | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.agent_id, str) or not self.agent_id.strip():
            raise ValueError("agent_id is required")
        if not self.role:
            object.__setattr__(self, "role", self.name)
        if not self.goal:
            object.__setattr__(self, "goal", self.instructions)
        if self.tool_names and not self.allowed_tools:
            object.__setattr__(self, "allowed_tools", list(self.tool_names))
        elif self.allowed_tools and not self.tool_names:
            object.__setattr__(self, "tool_names", list(self.allowed_tools))
        if self.model_route and "route_id" not in self.model_policy:
            object.__setattr__(self, "model_policy", {**dict(self.model_policy), "route_id": self.model_route})
        if self.max_iterations != 8 and self.loop_policy.max_iterations == AgentLoopPolicy().max_iterations:
            object.__setattr__(
                self,
                "loop_policy",
                AgentLoopPolicy(
                    max_iterations=self.max_iterations,
                    max_tool_calls=self.loop_policy.max_tool_calls,
                    allow_parallel_tool_calls=self.loop_policy.allow_parallel_tool_calls,
                    require_final_answer=self.loop_policy.require_final_answer,
                    stop_on_tool_error=self.loop_policy.stop_on_tool_error,
                    memory_recall_enabled=self.loop_policy.memory_recall_enabled,
                    memory_write_enabled=self.loop_policy.memory_write_enabled,
                    max_judge_retries=self.loop_policy.max_judge_retries,
                    max_parser_errors=self.loop_policy.max_parser_errors,
                    max_repeated_tool_calls=self.loop_policy.max_repeated_tool_calls,
                    max_consecutive_tool_failures=self.loop_policy.max_consecutive_tool_failures,
                    stop_on_first_valid_output=self.loop_policy.stop_on_first_valid_output,
                    stall_detection_enabled=self.loop_policy.stall_detection_enabled,
                    trace_enabled=self.loop_policy.trace_enabled,
                    max_trace_preview_chars=self.loop_policy.max_trace_preview_chars,
                    llm_streaming_enabled=self.loop_policy.llm_streaming_enabled,
                    conversation_compaction_enabled=self.loop_policy.conversation_compaction_enabled,
                    conversation_compaction_max_messages=self.loop_policy.conversation_compaction_max_messages,
                    conversation_compaction_keep_last=self.loop_policy.conversation_compaction_keep_last,
                    allow_subagents=self.loop_policy.allow_subagents,
                ),
            )

    def resolved_tool_policy(self) -> ToolPolicy:
        if self.tool_policy:
            return self.tool_policy
        return ToolPolicy(
            allowed_tools=list(self.allowed_tools),
            require_explicit_allowlist=True,
        )

    @property
    def allow_subagents(self) -> bool:
        return bool(self.loop_policy.allow_subagents)

    def allows_subagent(self, child_agent_id: str) -> bool:
        return self.allow_subagents and child_agent_id in set(self.allowed_subagents)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "role": self.role,
            "goal": self.goal,
            "instructions": self.instructions,
            "input_keys": list(self.input_keys),
            "output_key": self.output_key,
            "output_schema": _copy_mapping(self.output_schema),
            "allowed_tools": list(self.allowed_tools),
            "loop_policy": _agent_loop_policy_to_dict(self.loop_policy),
            "tool_policy": (
                _tool_policy_to_dict(self.tool_policy)
                if self.tool_policy is not None
                else None
            ),
            "model_route": self.model_route,
            "tool_names": list(self.tool_names),
            "memory_enabled": self.memory_enabled,
            "max_iterations": self.max_iterations,
            "model_policy": dict(self.model_policy),
            "validation_policy": dict(self.validation_policy),
            "system_prompt_template": self.system_prompt_template,
            "task_prompt_template": self.task_prompt_template,
            "allowed_references": list(self.allowed_references),
            "allowed_subagents": list(self.allowed_subagents),
            "session_context_policy": self.session_context_policy.to_dict() if self.session_context_policy else None,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AgentSpec:
        return cls(
            agent_id=str(payload.get("agent_id") or ""),
            name=str(payload.get("name") or ""),
            role=str(payload.get("role") or ""),
            goal=str(payload.get("goal") or ""),
            instructions=str(payload.get("instructions") or ""),
            input_keys=[str(item) for item in payload.get("input_keys", [])],
            output_key=str(payload.get("output_key") or "output"),
            output_schema=_optional_mapping(payload.get("output_schema")),
            allowed_tools=_string_list(
                payload.get("allowed_tools")
                if payload.get("allowed_tools") is not None
                else payload.get("tool_names", [])
            ),
            loop_policy=_agent_loop_policy_from_dict(payload.get("loop_policy")),
            tool_policy=_tool_policy_from_dict(payload.get("tool_policy")),
            model_route=_optional_str(payload.get("model_route")),
            tool_names=[str(item) for item in payload.get("tool_names", [])],
            memory_enabled=bool(payload.get("memory_enabled", True)),
            max_iterations=int(payload.get("max_iterations") or 8),
            model_policy=dict(payload.get("model_policy") or {}),
            validation_policy=dict(payload.get("validation_policy") or {}),
            system_prompt_template=str(
                payload.get("system_prompt_template") or "{role}\n{instructions}"
            ),
            task_prompt_template=str(
                payload.get("task_prompt_template") or "Goal: {goal}\nInputs: {inputs}"
            ),
            allowed_references=_string_list(payload.get("allowed_references", [])),
            allowed_subagents=_string_list(payload.get("allowed_subagents", [])),
            session_context_policy=AgentSessionContextPolicy.from_dict(payload.get("session_context_policy")),
            metadata=dict(payload.get("metadata") or {}),
        )


def _agent_loop_policy_to_dict(policy: AgentLoopPolicy) -> dict[str, Any]:
    return dict(policy.to_dict())


def _agent_loop_policy_from_dict(value: Any) -> AgentLoopPolicy:
    if not isinstance(value, dict):
        return AgentLoopPolicy()
    supported = _agent_loop_policy_to_dict(AgentLoopPolicy()).keys()
    return AgentLoopPolicy(**{key: value[key] for key in supported if key in value})


def _tool_policy_to_dict(policy: ToolPolicy) -> dict[str, Any]:
    return {
        "allowed_tools": list(policy.allowed_tools),
        "blocked_tools": list(policy.blocked_tools),
        "allow_mcp_tools": policy.allow_mcp_tools,
        "max_tool_calls_per_iteration": policy.max_tool_calls_per_iteration,
        "max_tool_calls_per_agent": policy.max_tool_calls_per_agent,
        "require_explicit_allowlist": policy.require_explicit_allowlist,
        "allow_dangerous_tools": policy.allow_dangerous_tools,
        "require_approval_for_side_effects": policy.require_approval_for_side_effects,
        "max_result_chars_inline": policy.max_result_chars_inline,
        "spill_large_results_to_artifact": policy.spill_large_results_to_artifact,
        "timeout_seconds_default": policy.timeout_seconds_default,
        "max_attempts_default": policy.max_attempts_default,
    }


def _tool_policy_from_dict(value: Any) -> ToolPolicy | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("tool_policy must be an object")
    supported = _tool_policy_to_dict(ToolPolicy()).keys()
    return ToolPolicy(**{key: value[key] for key in supported if key in value})


def _copy_mapping(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return dict(value)


def _optional_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("output_schema must be an object")
    return dict(value)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
