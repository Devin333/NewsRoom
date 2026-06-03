from __future__ import annotations

from typing import Any

from infrastructure.storage.lineage.evidence import quality_lineage_summary


def project_quality_trace_preview(output: dict[str, Any]) -> dict[str, Any]:
    raw_quality_result = output.get("quality_result")
    raw_citation_check = output.get("citation_check_result")
    raw_support_matrix = output.get("support_matrix")
    quality_result: dict[str, Any] = (
        dict(raw_quality_result) if isinstance(raw_quality_result, dict) else {}
    )
    citation_check: dict[str, Any] = (
        dict(raw_citation_check) if isinstance(raw_citation_check, dict) else {}
    )
    support_matrix: dict[str, Any] = (
        dict(raw_support_matrix) if isinstance(raw_support_matrix, dict) else {}
    )
    quality_lineage = project_quality_lineage_preview(output)
    if not (quality_result or citation_check or support_matrix or quality_lineage):
        return {}
    raw_quality_metadata = quality_result.get("metadata")
    quality_metadata = (
        dict(raw_quality_metadata)
        if isinstance(raw_quality_metadata, dict)
        else {}
    )
    return {
        "decision": quality_result.get("decision"),
        "route": quality_result.get("route") or output.get("quality_route"),
        "citation_failure_categories": quality_metadata.get(
            "citation_failure_categories", []
        ),
        "unsupported_claims": citation_check.get("unsupported_claims", []),
        "rejected_claim_usage": citation_check.get("rejected_claim_usage", []),
        "unsupported_sections": support_matrix.get("unsupported_sections", []),
        "quality_lineage": quality_lineage,
    }


def project_quality_lineage_preview(output: dict[str, Any]) -> dict[str, Any]:
    raw_candidate_claims = output.get("candidate_claims")
    candidate_claims = _dict_list(raw_candidate_claims)
    raw_verified_findings = output.get("verified_findings")
    verified_findings: dict[str, Any] = (
        dict(raw_verified_findings) if isinstance(raw_verified_findings, dict) else {}
    )
    claims = [
        *_dict_list(verified_findings.get("accepted_claims")),
        *_dict_list(verified_findings.get("rejected_claims")),
        *_dict_list(verified_findings.get("uncertain_claims")),
    ]
    raw_final_report = output.get("final_report")
    raw_blocked_report = output.get("blocked_report")
    report = (
        dict(raw_final_report)
        if isinstance(raw_final_report, dict)
        else dict(raw_blocked_report)
        if isinstance(raw_blocked_report, dict)
        else {}
    )
    raw_quality_result = output.get("quality_result")
    quality_results = [dict(raw_quality_result)] if isinstance(raw_quality_result, dict) else []
    if not (claims or candidate_claims or report or quality_results):
        return {}
    return quality_lineage_summary(
        run_id=str(output.get("run_id") or ""),
        report_id=str(output.get("report_id") or report.get("report_id") or output.get("run_id") or ""),
        claims=claims or candidate_claims,
        quality_results=quality_results,
    )


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


__all__ = [
    "project_quality_lineage_preview",
    "project_quality_trace_preview",
]
