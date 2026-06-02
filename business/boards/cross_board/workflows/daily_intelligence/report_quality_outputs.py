from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.quality_observability import (
    quality_gate_observability_metrics,
)
from business.foundation.value_normalization import (
    field_value as _field_value,
    float_value as _float_value,
    list_value as _list_value,
)


def build_report_quality_summary(
    *,
    editor_decision: dict[str, Any],
    verification_result: dict[str, Any],
    citation_check_result: dict[str, Any],
    support_matrix: dict[str, Any],
    route: str,
) -> dict[str, Any]:
    return {
        "quality_score": editor_decision["quality_score"],
        "decision": editor_decision["decision"],
        "route": route,
        "verification_status": verification_result.get("status"),
        "risk_level": verification_result.get("risk_level"),
        "citation_passed": citation_check_result.get("passed"),
        "support_coverage": _float_value(support_matrix.get("coverage_ratio"), default=None),
        "accepted_claims_count": len(_list_value((support_matrix.get("accepted_claim_ids")))),
        "rejected_claims_count": len(_list_value((support_matrix.get("rejected_claim_ids")))),
        "uncertain_claims_count": len(_list_value((support_matrix.get("uncertain_claim_ids")))),
        "unsupported_claims_count": len(_list_value((support_matrix.get("unsupported_claims")))),
        "high_severity_unsupported_claims_count": len(
            _list_value(support_matrix.get("high_severity_unsupported_claims"))
        ),
        "reason_count": len(editor_decision["reasons"]),
    }


def build_report_quality_gate_metrics(
    *,
    evidence_bundle: Any,
    verified_findings: Any,
    editor_decision: dict[str, Any],
    verification_result: dict[str, Any],
    citation_check_result: dict[str, Any],
    support_matrix: dict[str, Any],
    route: str,
    rewrite_attempts: int,
    human_review_required: bool,
) -> dict[str, Any]:
    unsupported_claims = _list_value(
        verification_result.get("unsupported_claims")
        or citation_check_result.get("unsupported_claims")
    )
    missing_citations = _list_value(
        verification_result.get("missing_citations")
        or citation_check_result.get("missing_section_sources")
    )
    unsupported_sections = _list_value(support_matrix.get("unsupported_sections"))
    blocked = route in {"blocked", "human_review"}
    rewrite_required = route == "rewrite" or editor_decision["decision"] == "rewrite_required"
    return {
        "evidence_items_count": _evidence_item_count(evidence_bundle),
        "accepted_claims_count": _collection_count(verified_findings, "accepted_claims"),
        "rejected_claims_count": _collection_count(verified_findings, "rejected_claims"),
        "uncertain_claims_count": _collection_count(verified_findings, "uncertain_claims"),
        "unsupported_claims_count": len(unsupported_claims),
        "missing_citations_count": len(missing_citations),
        "unknown_urls_count": len(_list_value(citation_check_result.get("unknown_urls"))),
        "unsupported_evidence_ids_count": len(
            _list_value(citation_check_result.get("unsupported_evidence_ids"))
        ),
        "citation_failure_category_count": len(
            _list_value(citation_check_result.get("failure_categories"))
        ),
        "citation_failure_categories": [
            str(category.get("code"))
            for category in _list_value(citation_check_result.get("failure_categories"))
            if isinstance(category, Mapping) and category.get("code")
        ],
        "unsupported_sections_count": len(unsupported_sections),
        "blocked": blocked,
        "decision": editor_decision["decision"],
        "route": route,
        "risk_level": verification_result.get("risk_level"),
        "quality_score": editor_decision["quality_score"],
        "rewrite_attempts": rewrite_attempts,
        "rewrite_required": rewrite_required,
        "human_review_required": human_review_required,
        **quality_gate_observability_metrics(
            blocked=blocked,
            rewrite_required=rewrite_required,
            human_review_required=human_review_required,
        ),
    }


def build_report_quality_result(
    *,
    editor_decision: dict[str, Any],
    route: str,
    rewrite_attempts: int,
    human_review_required: bool,
    quality_gate_metrics: dict[str, Any],
    citation_check_result: dict[str, Any],
    agent_feedback_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    passed = route in {"final", "rewrite"}
    return {
        "decision": editor_decision["decision"],
        "passed": passed,
        "route": route,
        "blocked": route in {"blocked", "human_review"},
        "quality_score": editor_decision["quality_score"],
        "rewrite_attempts": rewrite_attempts,
        "rewrite_required": route == "rewrite" or editor_decision["decision"] == "rewrite_required",
        "human_review_required": human_review_required,
        "route_history": _route_history(
            route=route,
            decision=editor_decision["decision"],
            rewrite_attempts=rewrite_attempts,
            human_review_required=human_review_required,
        ),
        "reasons": list(editor_decision["reasons"]),
        "artifact_refs": {
            "editor_review": "editor_review.json",
            "report_quality_summary": "report_quality_summary.json",
            "quality_gate_metrics": "quality_gate_metrics.json",
            "quality_events": "quality_events.json",
        },
        "quality_gate_metrics": dict(quality_gate_metrics),
        "metadata": {
            "source": "daily.finalize_report",
            "citation_failure_categories": _list_value(
                citation_check_result.get("failure_categories")
            ),
            "remediation": quality_remediation(
                rewrite_instructions=editor_decision["rewrite_instructions"],
                human_review_required=human_review_required,
            ),
            **dict(agent_feedback_metadata or {}),
        },
    }


def quality_remediation(*, rewrite_instructions: list[str], human_review_required: bool) -> list[str]:
    if rewrite_instructions:
        return list(rewrite_instructions)
    if human_review_required:
        return ["human reviewer must approve, reject, or request rewrite"]
    return []


def build_human_review_request(
    *,
    request: Any,
    report_draft: dict[str, Any],
    evidence_bundle: Any,
    editor_decision: dict[str, Any],
    verification_result: dict[str, Any],
    fallback_title: str,
) -> dict[str, Any]:
    bundle_id = _field_value(evidence_bundle, "bundle_id") or "daily"
    review_id = f"review-{bundle_id}"
    return {
        "review_id": review_id,
        "run_id": _field_value(request, "run_id") or bundle_id,
        "draft_id": f"draft-{bundle_id}",
        "reason": _human_review_reason(editor_decision),
        "risk_level": verification_result.get("risk_level") or "medium",
        "status": "pending",
        "title": report_draft.get("title") or fallback_title,
        "quality_score": editor_decision["quality_score"],
        "reasons": list(editor_decision["reasons"]),
        "rewrite_instructions": list(editor_decision["rewrite_instructions"]),
        "quality_artifact_refs": {
            "editor_review": "editor_review.json",
            "report_quality_summary": "report_quality_summary.json",
            "quality_result": "quality_result.json",
            "quality_gate_metrics": "quality_gate_metrics.json",
        },
        "metadata": {
            "decision": editor_decision["decision"],
            "evidence_bundle_id": bundle_id,
            "remediation": quality_remediation(
                rewrite_instructions=editor_decision["rewrite_instructions"],
                human_review_required=True,
            ),
        },
    }


def _human_review_reason(editor_decision: dict[str, Any]) -> str:
    if editor_decision["decision"] == "blocked":
        return "quality gate blocked"
    return "quality gate rewrite required"


def _route_history(
    *,
    route: str,
    decision: str,
    rewrite_attempts: int,
    human_review_required: bool,
) -> list[str]:
    history: list[str] = []
    if rewrite_attempts > 0 or route == "rewrite" or decision == "rewrite_required":
        history.append("rewrite")
    if route == "blocked":
        history.append("blocked")
    if human_review_required or route == "human_review":
        history.append("human_review")
    if route == "final":
        history.append("final")
    return history or [route]


def _evidence_item_count(evidence_bundle: Any) -> int:
    item_count = _field_value(evidence_bundle, "item_count")
    if item_count is not None:
        try:
            return int(item_count)
        except (TypeError, ValueError):
            return 0
    return len(_list_value(_field_value(evidence_bundle, "items", default=[])))


def _collection_count(value: Any, field_name: str) -> int:
    if value is None:
        return 0
    return len(_list_value(_field_value(value, field_name, default=[])))
