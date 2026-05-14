from __future__ import annotations

import re
from typing import Any

from core.framework.llm import (
    LLMStructuredOutputValidationError,
    validate_structured_output,
)
from core.framework.agent_loop.models import AgentAction, AgentSpec, JudgeDecision, JudgeVerdict
from evidence.models import EvidenceBundle, EvidenceItem, VerifiedFindings
from quality.citation_checker import CitationChecker


SECRET_PREFIX = "sk" + "-"
SECRET_PATTERNS = [
    re.compile(rf"{SECRET_PREFIX}[A-Za-z0-9_-]{{12,}}"),
    re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+[A-Za-z0-9._-]+"),
]


class OutputJudge:
    def judge(
        self,
        *,
        agent: AgentSpec,
        action: AgentAction,
        called_tools: list[str],
        inputs: dict[str, Any] | None = None,
    ) -> JudgeVerdict:
        if action.action_type == "delegate_to_subagent":
            child_agent_id = action.subagent_id or ""
            if not agent.allows_subagent(child_agent_id):
                return JudgeVerdict(
                    decision=JudgeDecision.BLOCK,
                    confidence=1.0,
                    feedback=f"subagent delegation is not allowed: {child_agent_id}",
                    policy_violations=["subagent delegation not allowed"],
                )
            return JudgeVerdict(
                decision=JudgeDecision.ESCALATE,
                confidence=1.0,
                feedback="subagent delegation accepted by policy but orchestration is deferred",
                quality_errors=[
                    (
                        "delegation handoff: "
                        f"parent_agent_id={agent.agent_id}; "
                        f"child_agent_id={child_agent_id}; "
                        f"handoff_reason={action.handoff_reason or 'subagent delegation requested'}"
                    )
                ],
            )

        if action.action_type != "final_output":
            return JudgeVerdict(
                decision=JudgeDecision.RETRY,
                confidence=0.0,
                feedback="expected final_output action",
                schema_errors=["expected final_output action"],
            )

        output = action.output or {}
        missing_output_keys = []
        if agent.output_key not in output:
            missing_output_keys.append(agent.output_key)

        schema_errors = self._schema_errors(output, agent.output_schema)
        quality_errors = self._evidence_boundary_errors(output, agent, inputs or {})
        tool_policy = agent.resolved_tool_policy()
        policy_violations = [
            f"tool not allowed: {tool_name}"
            for tool_name in called_tools
            if not tool_policy.allows(tool_name)
        ]
        policy_violations.extend(self._source_violations(output, agent.allowed_sources))
        policy_violations.extend(self._evidence_id_violations(output, inputs or {}))

        if self._contains_secret(output):
            return JudgeVerdict(
                decision=JudgeDecision.BLOCK,
                confidence=1.0,
                feedback="output contains secret-like content",
                policy_violations=["secret-like content detected"],
            )

        if policy_violations and any(
            violation.startswith("evidence id outside boundary:")
            for violation in policy_violations
        ):
            return JudgeVerdict(
                decision=JudgeDecision.BLOCK,
                confidence=1.0,
                feedback="unsupported evidence id referenced",
                missing_output_keys=missing_output_keys,
                schema_errors=schema_errors,
                quality_errors=quality_errors,
                policy_violations=policy_violations,
            )

        if missing_output_keys or schema_errors or quality_errors or policy_violations:
            feedback_parts = []
            if missing_output_keys:
                feedback_parts.append(f"missing output keys: {', '.join(missing_output_keys)}")
            if schema_errors:
                feedback_parts.append(f"schema errors: {', '.join(schema_errors)}")
            if quality_errors:
                feedback_parts.append(f"quality errors: {', '.join(quality_errors)}")
            if policy_violations:
                feedback_parts.append(f"policy violations: {', '.join(policy_violations)}")
            return JudgeVerdict(
                decision=JudgeDecision.RETRY,
                confidence=0.3,
                feedback="; ".join(feedback_parts),
                missing_output_keys=missing_output_keys,
                schema_errors=schema_errors,
                quality_errors=quality_errors,
                policy_violations=policy_violations,
            )

        return JudgeVerdict(
            decision=JudgeDecision.ACCEPT,
            confidence=1.0,
            feedback="accepted",
        )

    def _schema_errors(
        self,
        output: dict[str, Any],
        output_schema: dict[str, Any] | None,
    ) -> list[str]:
        if output_schema is None:
            return []
        try:
            validate_structured_output(output, output_schema)
        except LLMStructuredOutputValidationError as exc:
            return [str(exc)]
        return []

    def _evidence_boundary_errors(
        self,
        output: dict[str, Any],
        agent: AgentSpec,
        inputs: dict[str, Any],
    ) -> list[str]:
        evidence_bundle = _evidence_bundle_from_inputs(inputs)
        if evidence_bundle is None:
            return []
        report = _report_from_output(output, agent.output_key)
        if report is None:
            return []
        result = CitationChecker().check(
            report,
            evidence_bundle,
            _verified_findings_from_inputs(inputs),
        )
        unsupported_claims = _stable_unsupported_claims(
            report,
            result.unsupported_claims,
        )
        errors: list[str] = []
        errors.extend(f"unsupported citation URL: {url}" for url in result.unsupported_urls)
        errors.extend(f"missing section sources: {title}" for title in result.missing_section_sources)
        errors.extend(f"unsupported claim outside evidence: {claim}" for claim in unsupported_claims)
        errors.extend(f"rejected claim used: {claim}" for claim in result.rejected_claim_usage)
        return errors

    def _contains_secret(self, value: Any) -> bool:
        if isinstance(value, str):
            return any(pattern.search(value) for pattern in SECRET_PATTERNS)
        if isinstance(value, dict):
            return any(self._contains_secret(item) for item in value.values())
        if isinstance(value, list):
            return any(self._contains_secret(item) for item in value)
        return False

    def _source_violations(self, output: Any, allowed_sources: list[str]) -> list[str]:
        if not allowed_sources:
            return []
        allowed = set(allowed_sources)
        violations: list[str] = []

        def inspect(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"source", "sources", "url", "urls"}:
                        inspect_source_value(item)
                    else:
                        inspect(item)
            elif isinstance(value, list):
                for item in value:
                    inspect(item)

        def inspect_source_value(value: Any) -> None:
            if isinstance(value, str) and value not in allowed:
                violations.append(f"source outside boundary: {value}")
            elif isinstance(value, list):
                for item in value:
                    inspect_source_value(item)

        inspect(output)
        return violations

    def _evidence_id_violations(
        self,
        output: Any,
        inputs: dict[str, Any],
    ) -> list[str]:
        allowed_ids = _allowed_evidence_ids_from_inputs(inputs)
        if not allowed_ids:
            return []
        referenced_ids = _collect_evidence_ids(output)
        return [
            f"evidence id outside boundary: {evidence_id}"
            for evidence_id in sorted(referenced_ids - allowed_ids)
        ]


def _evidence_bundle_from_inputs(inputs: dict[str, Any]) -> EvidenceBundle | None:
    for key in ("evidence_bundle", "bundle"):
        if key in inputs:
            return _coerce_evidence_bundle(inputs[key])
    request = inputs.get("request")
    if isinstance(request, dict):
        for key in ("evidence_bundle", "bundle"):
            if key in request:
                return _coerce_evidence_bundle(request[key])
    return None


def _allowed_evidence_ids_from_inputs(inputs: dict[str, Any]) -> set[str]:
    bundle = _evidence_bundle_from_inputs(inputs)
    if bundle is None:
        return set()
    return {item.evidence_id for item in bundle.items if item.evidence_id}


def _collect_evidence_ids(value: Any) -> set[str]:
    ids: set[str] = set()

    def inspect(item: Any, *, key: str | None = None) -> None:
        if isinstance(item, dict):
            for child_key, child_value in item.items():
                inspect(child_value, key=str(child_key))
            return
        if isinstance(item, list):
            for child in item:
                inspect(child, key=key)
            return
        if key in {
            "evidence_id",
            "evidence_ids",
            "source_evidence_id",
            "source_evidence_ids",
            "supporting_evidence_id",
            "supporting_evidence_ids",
            "rejecting_evidence_id",
            "rejecting_evidence_ids",
            "citation_evidence_id",
            "citation_evidence_ids",
        } and isinstance(item, str):
            stripped = item.strip()
            if stripped:
                ids.add(stripped)

    inspect(value)
    return ids


def _verified_findings_from_inputs(inputs: dict[str, Any]) -> VerifiedFindings | None:
    value = inputs.get("verified_findings")
    if isinstance(value, VerifiedFindings):
        return value
    request = inputs.get("request")
    if isinstance(request, dict) and isinstance(request.get("verified_findings"), VerifiedFindings):
        return request["verified_findings"]
    return None


def _coerce_evidence_bundle(value: Any) -> EvidenceBundle | None:
    if isinstance(value, EvidenceBundle):
        return value
    if not isinstance(value, dict):
        return None
    raw_items = value.get("items")
    if not isinstance(raw_items, list):
        return None
    items = []
    for item in raw_items:
        if isinstance(item, EvidenceItem):
            items.append(item)
        elif isinstance(item, dict):
            items.append(
                EvidenceItem(
                    evidence_id=str(item.get("evidence_id") or ""),
                    source_url=str(item.get("source_url") or ""),
                    title=str(item.get("title") or ""),
                    summary=str(item.get("summary") or item.get("title") or ""),
                    confidence=_float(item.get("confidence"), default=0.0),
                    source_id=str(item.get("source_id") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
    return EvidenceBundle(
        bundle_id=str(value.get("bundle_id") or "agent_input"),
        items=items,
        source_map={
            str(key): [str(source_item) for source_item in source_items]
            for key, source_items in dict(value.get("source_map") or {}).items()
        },
        missing_information=[str(item) for item in value.get("missing_information", [])],
        coverage_notes=[str(item) for item in value.get("coverage_notes", [])],
        metadata=dict(value.get("metadata") or {}),
    )


def _report_from_output(output: dict[str, Any], output_key: str) -> dict[str, Any] | None:
    candidates = [
        output.get(output_key),
        output.get("final_report"),
        output.get("report"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and isinstance(candidate.get("sections"), list):
            return candidate
    return None


def _float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _stable_unsupported_claims(report: dict[str, Any], claims: list[str]) -> list[str]:
    title_map = {
        str(section.get("title", "Untitled")).casefold(): str(section.get("title", "Untitled"))
        for section in report.get("sections", [])
        if isinstance(section, dict)
    }
    stable = []
    for claim in claims:
        prefix, separator, rest = claim.partition(": ")
        if separator and prefix.casefold() in title_map:
            stable.append(f"{title_map[prefix.casefold()]}: {rest}")
        else:
            stable.append(claim)
    return stable
