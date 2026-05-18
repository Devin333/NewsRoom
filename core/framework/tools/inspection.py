from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from core.framework.tools.boundary import (
    AgentToolBoundaryReport,
    audit_agent_tool_boundary,
)
from core.framework.tools.executor import ToolExecutor
from core.framework.tools.models import (
    ToolDefinition,
    ToolPolicy,
    ToolStatus,
    is_default_dangerous_tool_name,
)
from core.framework.tools.registry import ToolRegistry
from core.framework.tools.telemetry import ToolEvent, ToolExecutionRecord, ToolMetrics


RISK_LEVELS = ("low", "medium", "high", "critical")
SIDE_EFFECT_NONE = {"", "none", "read_only"}
EXTERNAL_TOOL_PREFIXES = ("mcp.", "web.", "github.", "arxiv.")


@dataclass(frozen=True)
class ToolInspectionFinding:
    code: str
    severity: str
    message: str
    tool_name: str | None = None
    namespace: str | None = None
    action: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def blocking(self) -> bool:
        return self.severity == "blocking"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "tool_name": self.tool_name,
            "namespace": self.namespace,
            "action": self.action,
            "blocking": self.blocking,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class ToolRiskSummary:
    low: int = 0
    medium: int = 0
    high: int = 0
    critical: int = 0
    dangerous_tools: int = 0
    approval_required_tools: int = 0
    side_effect_tools: int = 0
    external_tools: int = 0
    tools_requiring_secrets: int = 0
    tools_without_timeout: int = 0
    tools_with_large_inline_limit: int = 0

    @property
    def risk_counts(self) -> dict[str, int]:
        return {
            "low": self.low,
            "medium": self.medium,
            "high": self.high,
            "critical": self.critical,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_counts": self.risk_counts,
            "dangerous_tools": self.dangerous_tools,
            "approval_required_tools": self.approval_required_tools,
            "side_effect_tools": self.side_effect_tools,
            "external_tools": self.external_tools,
            "tools_requiring_secrets": self.tools_requiring_secrets,
            "tools_without_timeout": self.tools_without_timeout,
            "tools_with_large_inline_limit": self.tools_with_large_inline_limit,
        }


@dataclass(frozen=True)
class ToolNamespaceSummary:
    namespace: str
    tool_count: int
    exposed_count: int = 0
    dangerous_count: int = 0
    approval_required_count: int = 0
    side_effect_count: int = 0
    external_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "tool_count": self.tool_count,
            "exposed_count": self.exposed_count,
            "dangerous_count": self.dangerous_count,
            "approval_required_count": self.approval_required_count,
            "side_effect_count": self.side_effect_count,
            "external_count": self.external_count,
        }


@dataclass(frozen=True)
class ToolDefinitionInspection:
    name: str
    namespace: str
    version: str
    tool_id: str
    exposed: bool
    risk_level: str
    side_effect: str
    is_dangerous: bool
    requires_approval: bool
    timeout_seconds: float | None
    max_attempts: int | None
    max_result_bytes: int | None
    concurrency_safe: bool
    required_secret_names: list[str] = field(default_factory=list)
    required_arguments: list[str] = field(default_factory=list)
    finding_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "namespace": self.namespace,
            "version": self.version,
            "tool_id": self.tool_id,
            "exposed": self.exposed,
            "risk_level": self.risk_level,
            "side_effect": self.side_effect,
            "is_dangerous": self.is_dangerous,
            "requires_approval": self.requires_approval,
            "timeout_seconds": self.timeout_seconds,
            "max_attempts": self.max_attempts,
            "max_result_bytes": self.max_result_bytes,
            "concurrency_safe": self.concurrency_safe,
            "required_secret_names": list(self.required_secret_names),
            "required_arguments": list(self.required_arguments),
            "finding_codes": list(self.finding_codes),
        }


@dataclass(frozen=True)
class ToolPolicyInspection:
    agent_id: str | None
    require_explicit_allowlist: bool
    allow_mcp_tools: bool
    allow_dangerous_tools: bool
    require_approval_for_side_effects: bool
    max_tool_calls_per_iteration: int
    max_tool_calls_per_agent: int
    max_result_chars_inline: int
    spill_large_results_to_artifact: bool
    timeout_seconds_default: float | None
    max_attempts_default: int
    allowed_tool_count: int
    blocked_tool_count: int
    exposed_tool_count: int
    blocked_exposed_tool_count: int
    unknown_allowed_tools: list[str] = field(default_factory=list)
    unknown_blocked_tools: list[str] = field(default_factory=list)
    exposed_dangerous_tools: list[str] = field(default_factory=list)
    exposed_side_effect_tools: list[str] = field(default_factory=list)
    exposed_mcp_tools: list[str] = field(default_factory=list)

    @property
    def broad_access(self) -> bool:
        return not self.require_explicit_allowlist

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "require_explicit_allowlist": self.require_explicit_allowlist,
            "allow_mcp_tools": self.allow_mcp_tools,
            "allow_dangerous_tools": self.allow_dangerous_tools,
            "require_approval_for_side_effects": self.require_approval_for_side_effects,
            "max_tool_calls_per_iteration": self.max_tool_calls_per_iteration,
            "max_tool_calls_per_agent": self.max_tool_calls_per_agent,
            "max_result_chars_inline": self.max_result_chars_inline,
            "spill_large_results_to_artifact": self.spill_large_results_to_artifact,
            "timeout_seconds_default": self.timeout_seconds_default,
            "max_attempts_default": self.max_attempts_default,
            "allowed_tool_count": self.allowed_tool_count,
            "blocked_tool_count": self.blocked_tool_count,
            "exposed_tool_count": self.exposed_tool_count,
            "blocked_exposed_tool_count": self.blocked_exposed_tool_count,
            "broad_access": self.broad_access,
            "unknown_allowed_tools": list(self.unknown_allowed_tools),
            "unknown_blocked_tools": list(self.unknown_blocked_tools),
            "exposed_dangerous_tools": list(self.exposed_dangerous_tools),
            "exposed_side_effect_tools": list(self.exposed_side_effect_tools),
            "exposed_mcp_tools": list(self.exposed_mcp_tools),
        }


@dataclass(frozen=True)
class ToolRegistryInspection:
    tool_count: int
    namespace_count: int
    registry_valid: bool
    registry_errors: list[str]
    namespaces: list[ToolNamespaceSummary]
    tools: list[ToolDefinitionInspection]
    risk_summary: ToolRiskSummary
    policy: ToolPolicyInspection | None = None
    findings: list[ToolInspectionFinding] = field(default_factory=list)
    boundary_report: AgentToolBoundaryReport | None = None

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    @property
    def blocking_finding_count(self) -> int:
        blocking = sum(1 for finding in self.findings if finding.blocking)
        if self.boundary_report is not None:
            blocking += self.boundary_report.blocking_finding_count
        return blocking

    @property
    def ok(self) -> bool:
        return self.registry_valid and self.blocking_finding_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "tool_count": self.tool_count,
            "namespace_count": self.namespace_count,
            "registry_valid": self.registry_valid,
            "registry_errors": list(self.registry_errors),
            "namespaces": [namespace.to_dict() for namespace in self.namespaces],
            "tools": [tool.to_dict() for tool in self.tools],
            "risk_summary": self.risk_summary.to_dict(),
            "policy": self.policy.to_dict() if self.policy is not None else None,
            "finding_count": self.finding_count,
            "blocking_finding_count": self.blocking_finding_count,
            "findings": [finding.to_dict() for finding in self.findings],
            "boundary_report": (
                self.boundary_report.to_dict() if self.boundary_report is not None else None
            ),
        }


@dataclass(frozen=True)
class ToolExecutorInspection:
    total_records: int
    total_events: int
    status_counts: dict[str, int]
    event_type_counts: dict[str, int]
    metrics: ToolMetrics
    recent_records: list[ToolExecutionRecord] = field(default_factory=list)
    recent_events: list[ToolEvent] = field(default_factory=list)
    findings: list[ToolInspectionFinding] = field(default_factory=list)

    @property
    def failed_or_blocked_count(self) -> int:
        return (
            self.status_counts.get(ToolStatus.FAILED.value, 0)
            + self.status_counts.get(ToolStatus.BLOCKED.value, 0)
            + self.status_counts.get(ToolStatus.TIMEOUT.value, 0)
        )

    @property
    def approval_required_count(self) -> int:
        return self.status_counts.get(ToolStatus.APPROVAL_REQUIRED.value, 0)

    @property
    def timeout_count(self) -> int:
        return self.status_counts.get(ToolStatus.TIMEOUT.value, 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_records": self.total_records,
            "total_events": self.total_events,
            "status_counts": dict(self.status_counts),
            "event_type_counts": dict(self.event_type_counts),
            "metrics": self.metrics.to_dict(),
            "recent_records": [record.to_dict() for record in self.recent_records],
            "recent_events": [event.to_dict() for event in self.recent_events],
            "failed_or_blocked_count": self.failed_or_blocked_count,
            "approval_required_count": self.approval_required_count,
            "timeout_count": self.timeout_count,
            "finding_count": len(self.findings),
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass(frozen=True)
class ToolRuntimeInspectionReport:
    registry: ToolRegistryInspection
    executor: ToolExecutorInspection | None = None
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        executor_ok = True
        if self.executor is not None:
            executor_ok = not any(finding.blocking for finding in self.executor.findings)
        return self.registry.ok and executor_ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": dict(self.summary),
            "registry": self.registry.to_dict(),
            "executor": self.executor.to_dict() if self.executor is not None else None,
        }


def inspect_tool_registry(
    registry: ToolRegistry,
    *,
    policy: ToolPolicy | None = None,
    agent_id: str | None = None,
    agent_tool_policies: dict[str, ToolPolicy | dict[str, Any] | list[str] | tuple[str, ...]]
    | None = None,
) -> ToolRegistryInspection:
    definitions = sorted(registry.list_tools(), key=lambda item: (item.namespace, item.name))
    validation = registry.validate_no_conflicts()
    policy_inspection = (
        inspect_tool_policy(registry, policy, agent_id=agent_id) if policy is not None else None
    )
    exposed_names = set()
    if policy is not None:
        exposed_names = {
            definition.name
            for definition in registry.list_tools_for_agent(agent_id or "", policy)
        }
    else:
        exposed_names = {definition.name for definition in definitions}

    findings: list[ToolInspectionFinding] = []
    tool_inspections: list[ToolDefinitionInspection] = []
    risk_counts = {level: 0 for level in RISK_LEVELS}
    dangerous_tools = 0
    approval_required_tools = 0
    side_effect_tools = 0
    external_tools = 0
    tools_requiring_secrets = 0
    tools_without_timeout = 0
    tools_with_large_inline_limit = 0
    namespace_mutable: dict[str, dict[str, int]] = {}

    for definition in definitions:
        risk_level = classify_tool_risk(definition)
        risk_counts[risk_level] += 1
        definition_findings = _definition_findings(definition)
        findings.extend(definition_findings)
        finding_codes = [finding.code for finding in definition_findings]
        has_side_effects = _has_side_effects(definition)
        is_external = _is_external_tool(definition.name)

        is_dangerous = _is_dangerous_tool(definition)
        dangerous_tools += int(is_dangerous)
        approval_required_tools += int(definition.requires_approval)
        side_effect_tools += int(has_side_effects)
        external_tools += int(is_external)
        tools_requiring_secrets += int(bool(definition.required_secret_names))
        tools_without_timeout += int(definition.timeout_seconds is None)
        tools_with_large_inline_limit += int(
            definition.max_result_bytes is None or definition.max_result_bytes > 1_000_000
        )

        namespace_counts = namespace_mutable.setdefault(
            definition.namespace,
            {
                "tool_count": 0,
                "exposed_count": 0,
                "dangerous_count": 0,
                "approval_required_count": 0,
                "side_effect_count": 0,
                "external_count": 0,
            },
        )
        namespace_counts["tool_count"] += 1
        namespace_counts["exposed_count"] += int(definition.name in exposed_names)
        namespace_counts["dangerous_count"] += int(is_dangerous)
        namespace_counts["approval_required_count"] += int(definition.requires_approval)
        namespace_counts["side_effect_count"] += int(has_side_effects)
        namespace_counts["external_count"] += int(is_external)

        tool_inspections.append(
            ToolDefinitionInspection(
                name=definition.name,
                namespace=definition.namespace,
                version=definition.version,
                tool_id=definition.tool_id,
                exposed=definition.name in exposed_names,
                risk_level=risk_level,
                side_effect=definition.side_effect,
                is_dangerous=is_dangerous,
                requires_approval=definition.requires_approval,
                timeout_seconds=definition.timeout_seconds,
                max_attempts=definition.max_attempts,
                max_result_bytes=definition.max_result_bytes,
                concurrency_safe=definition.concurrency_safe,
                required_secret_names=list(definition.required_secret_names),
                required_arguments=definition.required_arguments,
                finding_codes=finding_codes,
            )
        )

    for error in validation.errors:
        findings.append(
            ToolInspectionFinding(
                code="registry_validation_error",
                severity="blocking",
                message=error,
                action="fix_registry_definition_or_executor",
            )
        )

    if policy_inspection is not None:
        findings.extend(_policy_findings(policy_inspection))

    boundary_report = None
    if agent_tool_policies is not None:
        boundary_report = audit_agent_tool_boundary(agent_tool_policies)
        for finding in boundary_report.findings:
            findings.append(
                ToolInspectionFinding(
                    code="agent_tool_boundary_violation",
                    severity=finding.severity,
                    message=finding.message,
                    tool_name=finding.tool_name,
                    action=finding.action,
                    details={"agent_id": finding.agent_id},
                )
            )

    namespaces = [
        ToolNamespaceSummary(
            namespace=namespace,
            tool_count=counts["tool_count"],
            exposed_count=counts["exposed_count"],
            dangerous_count=counts["dangerous_count"],
            approval_required_count=counts["approval_required_count"],
            side_effect_count=counts["side_effect_count"],
            external_count=counts["external_count"],
        )
        for namespace, counts in sorted(namespace_mutable.items())
    ]
    risk_summary = ToolRiskSummary(
        low=risk_counts["low"],
        medium=risk_counts["medium"],
        high=risk_counts["high"],
        critical=risk_counts["critical"],
        dangerous_tools=dangerous_tools,
        approval_required_tools=approval_required_tools,
        side_effect_tools=side_effect_tools,
        external_tools=external_tools,
        tools_requiring_secrets=tools_requiring_secrets,
        tools_without_timeout=tools_without_timeout,
        tools_with_large_inline_limit=tools_with_large_inline_limit,
    )
    return ToolRegistryInspection(
        tool_count=len(definitions),
        namespace_count=len(namespaces),
        registry_valid=validation.ok,
        registry_errors=list(validation.errors),
        namespaces=namespaces,
        tools=tool_inspections,
        risk_summary=risk_summary,
        policy=policy_inspection,
        findings=findings,
        boundary_report=boundary_report,
    )


def inspect_tool_policy(
    registry: ToolRegistry,
    policy: ToolPolicy,
    *,
    agent_id: str | None = None,
) -> ToolPolicyInspection:
    definitions = registry.list_tools()
    known_tools = {definition.name for definition in definitions}
    exposed_definitions = registry.list_tools_for_agent(agent_id or "", policy)
    exposed_names = {definition.name for definition in exposed_definitions}
    blocked_exposed = sorted(name for name in exposed_names if name in policy.blocked_tools)
    return ToolPolicyInspection(
        agent_id=agent_id,
        require_explicit_allowlist=policy.require_explicit_allowlist,
        allow_mcp_tools=policy.allow_mcp_tools,
        allow_dangerous_tools=policy.allow_dangerous_tools,
        require_approval_for_side_effects=policy.require_approval_for_side_effects,
        max_tool_calls_per_iteration=policy.max_tool_calls_per_iteration,
        max_tool_calls_per_agent=policy.max_tool_calls_per_agent,
        max_result_chars_inline=policy.max_result_chars_inline,
        spill_large_results_to_artifact=policy.spill_large_results_to_artifact,
        timeout_seconds_default=policy.timeout_seconds_default,
        max_attempts_default=policy.max_attempts_default,
        allowed_tool_count=len(policy.allowed_tools),
        blocked_tool_count=len(policy.blocked_tools),
        exposed_tool_count=len(exposed_names),
        blocked_exposed_tool_count=len(blocked_exposed),
        unknown_allowed_tools=sorted(set(policy.allowed_tools) - known_tools),
        unknown_blocked_tools=sorted(set(policy.blocked_tools) - known_tools),
        exposed_dangerous_tools=sorted(
            definition.name for definition in exposed_definitions if _is_dangerous_tool(definition)
        ),
        exposed_side_effect_tools=sorted(
            definition.name for definition in exposed_definitions if _has_side_effects(definition)
        ),
        exposed_mcp_tools=sorted(
            definition.name for definition in exposed_definitions if definition.name.startswith("mcp.")
        ),
    )


def inspect_tool_executor(
    executor: ToolExecutor,
    *,
    recent_limit: int = 20,
) -> ToolExecutorInspection:
    records = executor.list_records()
    events = executor.list_events()
    metrics = executor.metrics
    status_counts = _status_counts(record.tool_result.status for record in records)
    event_type_counts = _string_counts(event.event_type for event in events)
    findings = _executor_findings(records, events)
    return ToolExecutorInspection(
        total_records=len(records),
        total_events=len(events),
        status_counts=status_counts,
        event_type_counts=event_type_counts,
        metrics=metrics,
        recent_records=records[-recent_limit:] if recent_limit > 0 else [],
        recent_events=events[-recent_limit:] if recent_limit > 0 else [],
        findings=findings,
    )


def inspect_tool_runtime(
    registry: ToolRegistry,
    *,
    policy: ToolPolicy | None = None,
    executor: ToolExecutor | None = None,
    agent_id: str | None = None,
    agent_tool_policies: dict[str, ToolPolicy | dict[str, Any] | list[str] | tuple[str, ...]]
    | None = None,
    recent_limit: int = 20,
) -> ToolRuntimeInspectionReport:
    registry_report = inspect_tool_registry(
        registry,
        policy=policy,
        agent_id=agent_id,
        agent_tool_policies=agent_tool_policies,
    )
    executor_report = (
        inspect_tool_executor(executor, recent_limit=recent_limit)
        if executor is not None
        else None
    )
    summary = {
        "tool_count": registry_report.tool_count,
        "namespace_count": registry_report.namespace_count,
        "registry_ok": registry_report.ok,
        "risk_counts": registry_report.risk_summary.risk_counts,
        "finding_count": registry_report.finding_count,
        "blocking_finding_count": registry_report.blocking_finding_count,
    }
    if executor_report is not None:
        summary.update(
            {
                "executor_total_records": executor_report.total_records,
                "executor_total_events": executor_report.total_events,
                "executor_status_counts": dict(executor_report.status_counts),
                "executor_failed_or_blocked_count": executor_report.failed_or_blocked_count,
            }
        )
    return ToolRuntimeInspectionReport(
        registry=registry_report,
        executor=executor_report,
        summary=summary,
    )


def classify_tool_risk(definition: ToolDefinition) -> str:
    if _is_dangerous_tool(definition) or definition.side_effect == "destructive":
        return "critical"
    if definition.side_effect in {
        "publishing",
        "writes_external_state",
        "external_write",
        "network_write",
    }:
        return "high"
    if (
        definition.requires_approval
        or _has_side_effects(definition)
        or definition.required_secret_names
    ):
        return "medium"
    return "low"


def _definition_findings(definition: ToolDefinition) -> list[ToolInspectionFinding]:
    findings: list[ToolInspectionFinding] = []
    if _is_dangerous_tool(definition):
        findings.append(
            ToolInspectionFinding(
                code="dangerous_tool_defined",
                severity="warning",
                message=f"Dangerous tool is registered: {definition.name}",
                tool_name=definition.name,
                namespace=definition.namespace,
                action="require explicit policy allowlist and approval",
            )
        )
    if _has_side_effects(definition) and not definition.requires_approval:
        findings.append(
            ToolInspectionFinding(
                code="side_effect_without_tool_approval_flag",
                severity="warning",
                message=f"Side-effecting tool does not set requires_approval: {definition.name}",
                tool_name=definition.name,
                namespace=definition.namespace,
                action="set requires_approval=True or document why policy gate is enough",
            )
        )
    if definition.timeout_seconds is None:
        findings.append(
            ToolInspectionFinding(
                code="tool_timeout_inherited",
                severity="info",
                message=f"Tool inherits policy timeout: {definition.name}",
                tool_name=definition.name,
                namespace=definition.namespace,
                action="set tool-specific timeout for slow or external tools",
            )
        )
    if definition.max_result_bytes is None:
        findings.append(
            ToolInspectionFinding(
                code="tool_output_limit_disabled",
                severity="warning",
                message=f"Tool output byte limit is disabled: {definition.name}",
                tool_name=definition.name,
                namespace=definition.namespace,
                action="set max_result_bytes unless the tool always returns artifact pointers",
            )
        )
    elif definition.max_result_bytes > 1_000_000:
        findings.append(
            ToolInspectionFinding(
                code="tool_output_limit_large",
                severity="info",
                message=f"Tool output byte limit is large: {definition.name}",
                tool_name=definition.name,
                namespace=definition.namespace,
                action="verify large outputs spill to artifact",
                details={"max_result_bytes": definition.max_result_bytes},
            )
        )
    return findings


def _policy_findings(policy: ToolPolicyInspection) -> list[ToolInspectionFinding]:
    findings: list[ToolInspectionFinding] = []
    if policy.broad_access:
        findings.append(
            ToolInspectionFinding(
                code="policy_broad_access",
                severity="warning",
                message="ToolPolicy does not require an explicit allowlist.",
                action="use explicit allowlists for agent-facing policies",
                details={"agent_id": policy.agent_id},
            )
        )
    for tool_name in policy.unknown_allowed_tools:
        findings.append(
            ToolInspectionFinding(
                code="policy_unknown_allowed_tool",
                severity="warning",
                message=f"Policy allowlist references an unknown tool: {tool_name}",
                tool_name=tool_name,
                action="remove or register the tool before exposing it",
            )
        )
    for tool_name in policy.unknown_blocked_tools:
        findings.append(
            ToolInspectionFinding(
                code="policy_unknown_blocked_tool",
                severity="info",
                message=f"Policy blocklist references an unknown tool: {tool_name}",
                tool_name=tool_name,
                action="remove stale blocklist entry if no longer needed",
            )
        )
    for tool_name in policy.exposed_dangerous_tools:
        findings.append(
            ToolInspectionFinding(
                code="policy_exposes_dangerous_tool",
                severity="blocking",
                message=f"Policy exposes dangerous tool: {tool_name}",
                tool_name=tool_name,
                action="remove dangerous tool from agent policy unless explicitly approved",
            )
        )
    for tool_name in policy.exposed_side_effect_tools:
        if tool_name in policy.exposed_dangerous_tools:
            continue
        findings.append(
            ToolInspectionFinding(
                code="policy_exposes_side_effect_tool",
                severity="warning",
                message=f"Policy exposes side-effecting tool: {tool_name}",
                tool_name=tool_name,
                action="ensure approval and audit path are configured",
            )
        )
    if policy.exposed_mcp_tools and not policy.allow_mcp_tools:
        findings.append(
            ToolInspectionFinding(
                code="policy_mcp_exposure_inconsistent",
                severity="blocking",
                message="Policy exposes MCP tools while allow_mcp_tools is false.",
                action="enable allow_mcp_tools or remove MCP tools from allowlist",
                details={"tools": list(policy.exposed_mcp_tools)},
            )
        )
    return findings


def _executor_findings(
    records: list[ToolExecutionRecord],
    events: list[ToolEvent],
) -> list[ToolInspectionFinding]:
    findings: list[ToolInspectionFinding] = []
    if not records and events:
        findings.append(
            ToolInspectionFinding(
                code="executor_events_without_records",
                severity="warning",
                message="ToolExecutor has events but no execution records.",
                action="verify record persistence and executor lifecycle",
            )
        )
    for record in records:
        if record.tool_result.status == ToolStatus.SUCCEEDED and not record.validation_passed:
            findings.append(
                ToolInspectionFinding(
                    code="record_success_without_validation",
                    severity="blocking",
                    message=f"Successful tool call did not record argument validation: {record.tool_call.tool_name}",
                    tool_name=record.tool_call.tool_name,
                    action="ensure ToolExecutor validates arguments before execution",
                )
            )
        if record.tool_result.status == ToolStatus.APPROVAL_REQUIRED and not record.approval_required:
            findings.append(
                ToolInspectionFinding(
                    code="record_approval_status_inconsistent",
                    severity="blocking",
                    message=f"Approval status is inconsistent for {record.tool_call.tool_name}",
                    tool_name=record.tool_call.tool_name,
                    action="verify approval gate record generation",
                )
            )
    return findings


def _status_counts(statuses: Iterable[ToolStatus]) -> dict[str, int]:
    counts = {status.value: 0 for status in ToolStatus}
    for status in statuses:
        counts[status.value] = counts.get(status.value, 0) + 1
    return counts


def _string_counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _has_side_effects(definition: ToolDefinition) -> bool:
    return definition.side_effect not in SIDE_EFFECT_NONE


def _is_dangerous_tool(definition: ToolDefinition) -> bool:
    return definition.is_dangerous or is_default_dangerous_tool_name(definition.name)


def _is_external_tool(tool_name: str) -> bool:
    return tool_name.startswith(EXTERNAL_TOOL_PREFIXES)
