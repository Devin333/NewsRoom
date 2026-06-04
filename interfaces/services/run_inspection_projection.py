from __future__ import annotations

from typing import Any

from framework.shared.json import to_jsonable as to_json_safe
from infrastructure.storage.lineage.evidence import quality_lineage_summary


QUALITY_RESULT_KEYS = ("quality.result", "quality_result")
CITATION_CHECK_KEYS = ("quality.citation_check_result", "citation_check_result")
SUPPORT_MATRIX_KEYS = ("quality.support_matrix", "support_matrix")
CANDIDATE_CLAIMS_KEYS = ("evidence.candidate_claims", "candidate_claims")
VERIFIED_FINDINGS_KEYS = ("evidence.verified_findings", "verified_findings")
FINAL_REPORT_KEYS = ("report.final", "final_report", "report")
BLOCKED_REPORT_KEYS = ("report.blocked", "blocked_report")
QUALITY_ROUTE_KEYS = ("quality.route", "quality_route")


def project_manifest_output_preview(
    output: dict[str, Any],
    *,
    business_output: dict[str, Any],
    artifacts: dict[str, Any],
) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for key, value in output.items():
        if len(preview) >= 12:
            break
        preview[str(key)] = _preview_value(value)
    quality_trace = project_quality_trace_preview(business_output)
    if quality_trace:
        preview["quality_trace"] = quality_trace
    llm_trace = project_llm_trace_preview(output)
    if llm_trace:
        preview["llm_trace"] = llm_trace
    partial_artifacts = project_partial_artifacts_preview(artifacts)
    if partial_artifacts and "partial_artifacts" not in preview:
        preview["partial_artifacts"] = partial_artifacts
    return preview


def project_quality_trace_preview(output: dict[str, Any]) -> dict[str, Any]:
    quality_result = _first_dict_value(output, QUALITY_RESULT_KEYS)
    citation_check = _first_dict_value(output, CITATION_CHECK_KEYS)
    support_matrix = _first_dict_value(output, SUPPORT_MATRIX_KEYS)
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
        "route": quality_result.get("route") or _first_value(output, QUALITY_ROUTE_KEYS),
        "citation_failure_categories": quality_metadata.get(
            "citation_failure_categories", []
        ),
        "unsupported_claims": citation_check.get("unsupported_claims", []),
        "rejected_claim_usage": citation_check.get("rejected_claim_usage", []),
        "unsupported_sections": support_matrix.get("unsupported_sections", []),
        "quality_lineage": quality_lineage,
    }


def project_quality_lineage_preview(output: dict[str, Any]) -> dict[str, Any]:
    candidate_claims = _first_dict_list_value(output, CANDIDATE_CLAIMS_KEYS)
    verified_findings = _first_dict_value(output, VERIFIED_FINDINGS_KEYS)
    claims = [
        *_dict_list(verified_findings.get("accepted_claims")),
        *_dict_list(verified_findings.get("rejected_claims")),
        *_dict_list(verified_findings.get("uncertain_claims")),
    ]
    report = _first_dict_value(output, FINAL_REPORT_KEYS + BLOCKED_REPORT_KEYS)
    quality_result = _first_dict_value(output, QUALITY_RESULT_KEYS)
    quality_results = [quality_result] if quality_result else []
    if not (claims or candidate_claims or report or quality_results):
        return {}
    return quality_lineage_summary(
        run_id=str(output.get("run_id") or ""),
        report_id=str(output.get("report_id") or report.get("report_id") or output.get("run_id") or ""),
        claims=claims or candidate_claims,
        quality_results=quality_results,
    )


def project_llm_trace_preview(output: dict[str, Any]) -> dict[str, Any]:
    raw_llm_route_manifest = output.get("llm_route_manifest")
    raw_llm_router_events = output.get("llm_router_events")
    llm_route_manifest: dict[str, Any] = (
        dict(raw_llm_route_manifest) if isinstance(raw_llm_route_manifest, dict) else {}
    )
    llm_router_events: list[Any] = (
        list(raw_llm_router_events) if isinstance(raw_llm_router_events, list) else []
    )
    if not (llm_route_manifest or llm_router_events):
        return {}
    raw_llm_metrics = llm_route_manifest.get("metrics")
    llm_metrics = (
        dict(raw_llm_metrics)
        if isinstance(raw_llm_metrics, dict)
        else {}
    )
    return {
        "selected_deployment_id": llm_route_manifest.get("selected_deployment_id"),
        "fallback_used": llm_route_manifest.get("fallback_used"),
        "fallback_count": llm_route_manifest.get("fallback_count"),
        "provider_error_count": llm_metrics.get("provider_error_count"),
        "cooldown_skip_count": llm_metrics.get("cooldown_skip_count"),
        "router_event_count": len(llm_router_events),
        "budget_check": llm_route_manifest.get("budget_check"),
        "global_budget_check": llm_route_manifest.get("global_budget_check"),
    }


def project_partial_artifacts_preview(artifacts: dict[str, Any]) -> dict[str, Any]:
    if not artifacts:
        return {}
    return {
        "artifact_keys": sorted(str(key) for key in artifacts)[:20],
        "required_artifact_keys": [
            key for key in ("request", "events", "step_results", "manifest") if key in artifacts
        ],
    }


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _first_dict_value(output: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    for key in keys:
        value = output.get(key)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _first_dict_list_value(output: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for key in keys:
        value = output.get(key)
        items = _dict_list(value)
        if items:
            return items
    return []


def _first_value(output: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = output.get(key)
        if value is not None:
            return value
    return None


def _preview_value(value: Any) -> Any:
    safe = to_json_safe(value)
    if isinstance(safe, dict):
        return {"type": "object", "keys": sorted(str(key) for key in safe)[:12]}
    if isinstance(safe, list):
        return {"type": "array", "count": len(safe)}
    text = str(safe)
    return text[:240] + ("..." if len(text) > 240 else "")


__all__ = [
    "project_llm_trace_preview",
    "project_manifest_output_preview",
    "project_partial_artifacts_preview",
    "project_quality_lineage_preview",
    "project_quality_trace_preview",
]
