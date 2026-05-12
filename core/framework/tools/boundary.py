from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.framework.tools.models import ToolPolicy


DEFAULT_RESTRICTED_AGENT_IDS = {"writer", "writeragent", "editor", "editoragent"}
DEFAULT_EXTERNAL_FETCH_TOOL_PREFIXES = (
    "source.fetch",
    "source.probe",
    "source.extract",
    "web.search",
    "github.",
    "arxiv.",
)
DEFAULT_EXTERNAL_FETCH_TOOL_NAMES = {
    "source.fetch_url",
    "source.fetch_official_blog",
    "source.probe",
    "web.search",
}


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
            if _is_external_fetch_tool(
                tool_name,
                prefixes=external_fetch_tool_prefixes,
                names=blocked_names,
            ):
                findings.append(
                    AgentToolBoundaryFinding(
                        agent_id=agent_id,
                        tool_name=tool_name,
                        severity="blocking",
                        message="Writer/Editor agents must not fetch or search external sources outside Source Pipeline.",
                        action="remove_tool_from_agent_policy",
                    )
                )
    return AgentToolBoundaryReport(
        finding_count=len(findings),
        blocking_finding_count=sum(1 for finding in findings if finding.severity == "blocking"),
        findings=findings,
    )


def _allowed_tool_names(policy_like: ToolPolicy | dict[str, Any] | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(policy_like, ToolPolicy):
        return list(policy_like.allowed_tools)
    if isinstance(policy_like, dict):
        value = policy_like.get("allowed_tools", [])
        return [str(tool_name) for tool_name in value]
    return [str(tool_name) for tool_name in policy_like]


def _is_external_fetch_tool(
    tool_name: str,
    *,
    prefixes: tuple[str, ...],
    names: set[str],
) -> bool:
    normalized = tool_name.strip()
    if normalized in names:
        return True
    return any(normalized.startswith(prefix) for prefix in prefixes)


def _normalize_agent_id(agent_id: str) -> str:
    return "".join(ch for ch in str(agent_id).casefold() if ch.isalnum())
