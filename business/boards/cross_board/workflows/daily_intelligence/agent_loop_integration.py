from __future__ import annotations

from typing import Any

from framework.agent import (
    AgentAction,
    AgentOutputBudgetValidator,
    AgentSpec,
    OutputJudge,
    OutputValidationResult,
)
from business.layers.relation.evidence.models import VerifiedFindings
from business.layers.analysis.quality.citation_checker import CitationChecker
from business.boards.cross_board.workflows.daily_intelligence.grounded_writer import normalize_daily_writer_output
from business.boards.cross_board.workflows.daily_intelligence.agent_evidence_input_view import (
    DailyAgentEvidenceInputView,
)
from business.boards.cross_board.workflows.daily_intelligence.agent_output_budget import (
    DAILY_AGENT_OUTPUT_BUDGET,
)
from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    canonicalize_namespaced_input_aliases,
    with_namespaced_aliases,
)
from business.boards.cross_board.workflows.daily_intelligence.output_projection import (
    daily_output_value,
)
from business.boards.cross_board.workflows.daily_intelligence.profiles import PROFILE_AGENTIC_LIVE


def build_daily_output_judge() -> OutputJudge:
    return OutputJudge(
        pre_output_validators=[
            AgentOutputBudgetValidator(default_budget=DAILY_AGENT_OUTPUT_BUDGET)
        ],
        output_validators=[DailyEvidenceOutputValidator()],
    )


class DailyAgentInputCanonicalizingRunner:
    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate

    def run(
        self,
        agent: AgentSpec,
        inputs: dict[str, Any],
        **kwargs: Any,
    ) -> Any:
        return self._delegate.run(
            agent,
            canonicalize_daily_agent_inputs(inputs),
            **kwargs,
        )

    def run_spec(
        self,
        spec: AgentSpec,
        input_text: str | dict[str, Any],
        **kwargs: Any,
    ) -> Any:
        inputs = input_text if isinstance(input_text, dict) else {"input_text": input_text}
        return self.run(spec, dict(inputs), **kwargs)


def canonicalize_daily_agent_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    return canonicalize_namespaced_input_aliases(inputs)


def normalize_daily_agent_output(
    *,
    agent: AgentSpec,
    output: dict[str, Any],
    inputs: dict[str, Any],
) -> dict[str, Any]:
    if agent.agent_id != "daily.writer" or _request_profile(inputs) != PROFILE_AGENTIC_LIVE:
        return with_namespaced_aliases(output)
    return with_namespaced_aliases(
        normalize_daily_writer_output(
            output=output,
            output_key=agent.output_key,
            inputs=inputs,
        )
    )


class DailyEvidenceOutputValidator:
    def __call__(
        self,
        *,
        agent: AgentSpec,
        action: AgentAction,
        called_tools: list[str],
        inputs: dict[str, Any],
    ) -> OutputValidationResult:
        _ = called_tools
        output = action.output or {}
        validation_errors = self._evidence_boundary_errors(output, agent, inputs)
        policy_violations = self._evidence_id_violations(output, inputs)
        return OutputValidationResult(
            validation_errors=validation_errors,
            policy_violations=policy_violations,
            block=bool(policy_violations),
            feedback="unsupported evidence id referenced" if policy_violations else None,
        )

    def _evidence_boundary_errors(
        self,
        output: dict[str, Any],
        agent: AgentSpec,
        inputs: dict[str, Any],
    ) -> list[str]:
        evidence_view = DailyAgentEvidenceInputView.from_inputs(inputs)
        if evidence_view is None:
            return []
        report = _report_from_output(output, agent.output_key)
        if report is None:
            return []
        result = CitationChecker().check(
            report,
            evidence_view.evidence_bundle,
            _verified_findings_from_inputs(inputs),
        )
        unsupported_claims = _stable_unsupported_claims(
            report,
            result.unsupported_claims,
        )
        errors: list[str] = []
        errors.extend(f"unknown citation URL: {url}" for url in result.unknown_urls)
        errors.extend(f"unsupported citation URL: {url}" for url in result.unsupported_urls)
        errors.extend(f"missing section sources: {title}" for title in result.missing_section_sources)
        errors.extend(f"unsupported claim outside evidence: {claim}" for claim in unsupported_claims)
        errors.extend(f"rejected claim used: {claim}" for claim in result.rejected_claim_usage)
        return errors

    def _evidence_id_violations(
        self,
        output: Any,
        inputs: dict[str, Any],
    ) -> list[str]:
        evidence_view = DailyAgentEvidenceInputView.from_inputs(inputs)
        if evidence_view is None:
            return []
        allowed_ids = evidence_view.allowed_evidence_ids
        if not allowed_ids:
            return []
        referenced_ids = _collect_evidence_ids(output)
        return [
            f"evidence id outside boundary: {evidence_id}"
            for evidence_id in sorted(referenced_ids - allowed_ids)
        ]


def _collect_evidence_ids(value: Any, *, max_depth: int = 50) -> set[str]:
    ids: set[str] = set()

    def inspect(item: Any, *, key: str | None = None, depth: int = 0) -> None:
        if depth > max_depth:
            return
        if isinstance(item, dict):
            for child_key, child_value in item.items():
                inspect(child_value, key=str(child_key), depth=depth + 1)
            return
        if isinstance(item, list):
            for child in item:
                inspect(child, key=key, depth=depth + 1)
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


def _report_from_output(output: dict[str, Any], output_key: str) -> dict[str, Any] | None:
    candidates = [
        output.get(output_key),
        daily_output_value(output, "final_report"),
        output.get("report"),
    ]
    for candidate in candidates:
        if _is_report_payload(candidate):
            return candidate
    return None


def _is_report_payload(candidate: Any) -> bool:
    if not isinstance(candidate, dict):
        return False
    sections = candidate.get("sections")
    if not isinstance(sections, list):
        return False
    if not all(isinstance(section, dict) for section in sections):
        return False
    title = candidate.get("title")
    if isinstance(title, str) and title.strip():
        return True
    return any(_has_report_section_fields(section) for section in sections)


def _has_report_section_fields(section: dict[str, Any]) -> bool:
    return any(
        key in section
        for key in (
            "content",
            "sources",
            "source_urls",
            "evidence_ids",
            "citations",
            "claim_grounding",
        )
    )


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


def _request_profile(inputs: dict[str, Any]) -> str | None:
    request = inputs.get("request")
    if isinstance(request, dict) and request.get("profile") is not None:
        return str(request.get("profile"))
    return None
