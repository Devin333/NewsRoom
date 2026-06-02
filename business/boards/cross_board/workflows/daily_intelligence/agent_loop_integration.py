from __future__ import annotations

from typing import Any

from framework.agent import (
    AgentAction,
    AgentSpec,
    OutputJudge,
    OutputValidationResult,
)
from business.foundation.models.source import Lineage
from business.layers.relation.evidence.models import EvidenceBundle, EvidenceItem, VerifiedFindings
from business.layers.analysis.quality.citation_checker import CitationChecker
from business.boards.cross_board.workflows.daily_intelligence.grounded_writer import normalize_daily_writer_output
from business.boards.cross_board.workflows.daily_intelligence.profiles import PROFILE_AGENTIC_LIVE


def build_daily_output_judge() -> OutputJudge:
    return OutputJudge(output_validators=[DailyEvidenceOutputValidator()])


def normalize_daily_agent_output(
    *,
    agent: AgentSpec,
    output: dict[str, Any],
    inputs: dict[str, Any],
) -> dict[str, Any]:
    if agent.agent_id != "daily.writer" or _request_profile(inputs) != PROFILE_AGENTIC_LIVE:
        return output
    return normalize_daily_writer_output(output=output, output_key=agent.output_key, inputs=inputs)


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
                    source_urls=[str(url) for url in item.get("source_urls", []) if url],
                    title=str(item.get("title") or ""),
                    summary=str(item.get("summary") or item.get("title") or ""),
                    confidence=_float(item.get("confidence"), default=0.0),
                    source_id=str(item.get("source_id") or ""),
                    source_item_id=_optional_str(item.get("source_item_id")),
                    source_item_ids=[str(value) for value in item.get("source_item_ids", []) if value],
                    source_reliability=_optional_str(item.get("source_reliability")),
                    publishable=bool(item.get("publishable", True)),
                    evidence_type=str(item.get("evidence_type") or "other"),
                    lineage=_lineage_from_payload(item.get("lineage")),
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


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _lineage_from_payload(value: Any) -> Lineage | None:
    if isinstance(value, Lineage):
        return value
    if isinstance(value, dict):
        try:
            return Lineage.from_dict(value)
        except Exception:
            return None
    return None


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
