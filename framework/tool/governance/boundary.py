from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from framework.tool.models.policy import ToolPolicy


DEFAULT_RESTRICTED_AGENT_IDS: set[str] = set()
DEFAULT_EXTERNAL_FETCH_TOOL_PREFIXES: tuple[str, ...] = ()
DEFAULT_EXTERNAL_FETCH_TOOL_NAMES: set[str] = set()


@dataclass(frozen=True)
class AgentToolBoundaryFinding:
    agent_id: str
    tool_name: str
    severity: str
    message: str
    action: str

    def to_dict(self) -> dict[str, str]:
        return {
            "agent_id": self.agent_id,
            "tool_name": self.tool_name,
            "severity": self.severity,
            "message": self.message,
            "action": self.action,
        }


@dataclass(frozen=True)
class AgentToolBoundaryReport:
    finding_count: int
    blocking_finding_count: int
    findings: list[AgentToolBoundaryFinding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.blocking_finding_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "finding_count": self.finding_count,
            "blocking_finding_count": self.blocking_finding_count,
            "findings": [finding.to_dict() for finding in self.findings],
        }


def audit_agent_tool_boundary(
    agent_tool_policies: dict[str, ToolPolicy | dict[str, Any] | list[str] | tuple[str, ...]],
    *,
    restricted_agent_ids: set[str] | None = None,
    external_fetch_tool_prefixes: tuple[str, ...] = DEFAULT_EXTERNAL_FETCH_TOOL_PREFIXES,
    external_fetch_tool_names: set[str] | None = None,
) -> AgentToolBoundaryReport:
    restricted = {
        _normalize_agent_id(agent_id)
        for agent_id in (restricted_agent_ids or DEFAULT_RESTRICTED_AGENT_IDS)
    }
    blocked_names = external_fetch_tool_names or DEFAULT_EXTERNAL_FETCH_TOOL_NAMES
    findings: list[AgentToolBoundaryFinding] = []
    for agent_id, policy_like in agent_tool_policies.items():
        if _normalize_agent_id(agent_id) not in restricted:
            continue
        for tool_name in _allowed_tool_names(policy_like):
            if is_external_fetch_tool(
                tool_name,
                external_fetch_tool_prefixes=external_fetch_tool_prefixes,
                external_fetch_tool_names=blocked_names,
            ):
                findings.append(
                    AgentToolBoundaryFinding(
                        agent_id=agent_id,
                        tool_name=tool_name,
                        severity="blocking",
                        message="agent is not allowed to call this tool by configured boundary",
                        action="remove_tool_from_agent_policy",
                    )
                )
    return AgentToolBoundaryReport(
        finding_count=len(findings),
        blocking_finding_count=sum(1 for finding in findings if finding.severity == "blocking"),
        findings=findings,
    )


def audit_agent_spec_tool_boundary(
    agent_specs: Iterable[Any],
    *,
    restricted_agent_ids: set[str] | None = None,
    external_fetch_tool_prefixes: tuple[str, ...] = DEFAULT_EXTERNAL_FETCH_TOOL_PREFIXES,
    external_fetch_tool_names: set[str] | None = None,
) -> AgentToolBoundaryReport:
    return audit_agent_tool_boundary(
        {
            str(getattr(agent_spec, "agent_id")): _agent_spec_policy(agent_spec)
            for agent_spec in agent_specs
        },
        restricted_agent_ids=restricted_agent_ids,
        external_fetch_tool_prefixes=external_fetch_tool_prefixes,
        external_fetch_tool_names=external_fetch_tool_names,
    )


def is_restricted_agent_id(agent_id: str, *, restricted_agent_ids: set[str] | None = None) -> bool:
    restricted = {
        _normalize_agent_id(item)
        for item in (restricted_agent_ids or DEFAULT_RESTRICTED_AGENT_IDS)
    }
    return _normalize_agent_id(agent_id) in restricted


def is_external_fetch_tool(
    tool_name: str,
    *,
    external_fetch_tool_prefixes: tuple[str, ...] = DEFAULT_EXTERNAL_FETCH_TOOL_PREFIXES,
    external_fetch_tool_names: set[str] | None = None,
) -> bool:
    normalized = tool_name.strip()
    names = external_fetch_tool_names or DEFAULT_EXTERNAL_FETCH_TOOL_NAMES
    if normalized in names:
        return True
    return any(normalized.startswith(prefix) for prefix in external_fetch_tool_prefixes)


def harden_restricted_agent_tool_policy(
    agent_id: str,
    policy: ToolPolicy,
    *,
    restricted_agent_ids: set[str] | None = None,
    external_fetch_tool_prefixes: tuple[str, ...] = DEFAULT_EXTERNAL_FETCH_TOOL_PREFIXES,
    external_fetch_tool_names: set[str] | None = None,
) -> ToolPolicy:
    if not is_restricted_agent_id(agent_id, restricted_agent_ids=restricted_agent_ids):
        return policy
    blocked_names = external_fetch_tool_names or DEFAULT_EXTERNAL_FETCH_TOOL_NAMES
    blocked_allowed_tools = [
        tool_name
        for tool_name in policy.allowed_tools
        if is_external_fetch_tool(
            tool_name,
            external_fetch_tool_prefixes=external_fetch_tool_prefixes,
            external_fetch_tool_names=blocked_names,
        )
    ]
    blocked_allowed_set = set(blocked_allowed_tools)
    return ToolPolicy(
        allowed_tools=[tool_name for tool_name in policy.allowed_tools if tool_name not in blocked_allowed_set],
        blocked_tools=sorted({*policy.blocked_tools, *blocked_allowed_set, *blocked_names}),
        allow_mcp_tools=policy.allow_mcp_tools,
        max_tool_calls_per_iteration=policy.max_tool_calls_per_iteration,
        max_tool_calls_per_agent=policy.max_tool_calls_per_agent,
        require_explicit_allowlist=True,
        allow_dangerous_tools=policy.allow_dangerous_tools,
        require_approval_for_side_effects=policy.require_approval_for_side_effects,
        max_result_chars_inline=policy.max_result_chars_inline,
        spill_large_results_to_artifact=policy.spill_large_results_to_artifact,
        timeout_seconds_default=policy.timeout_seconds_default,
        max_attempts_default=policy.max_attempts_default,
    )


def _allowed_tool_names(policy_like: ToolPolicy | dict[str, Any] | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(policy_like, ToolPolicy):
        return list(policy_like.allowed_tools)
    if isinstance(policy_like, dict):
        return [str(tool_name) for tool_name in policy_like.get("allowed_tools", [])]
    return [str(tool_name) for tool_name in policy_like]


def _agent_spec_policy(agent_spec: Any) -> ToolPolicy | dict[str, Any] | list[str]:
    tool_policy = getattr(agent_spec, "tool_policy", None)
    if tool_policy is not None:
        return tool_policy
    return [str(tool_name) for tool_name in getattr(agent_spec, "allowed_tools", [])]


def _normalize_agent_id(agent_id: str) -> str:
    return "".join(ch for ch in str(agent_id).casefold() if ch.isalnum())
