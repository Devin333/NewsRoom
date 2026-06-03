from __future__ import annotations

from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    with_namespaced_aliases,
)
from business.boards.cross_board.workflows.daily_intelligence.report_draft_normalization import (
    source_urls_from_draft,
    source_urls_from_evidence,
)
from business.boards.cross_board.workflows.daily_intelligence.report_quality_outputs import (
    build_report_quality_gate_metrics,
    build_report_quality_result,
    build_report_quality_summary,
)
from business.foundation.models.report_output import BlockedReport, FinalReport, render_markdown
from business.foundation.value_normalization import (
    field_value as _field_value,
    list_value as _list_value,
    to_plain_dict as _to_plain_dict,
)


def build_publish_report_outputs(
    *,
    request: Any,
    final_draft: dict[str, Any],
    evidence_bundle: Any,
    verified_findings: Any,
    editor_decision: dict[str, Any],
    verification_result: dict[str, Any],
    citation_check_result: dict[str, Any],
    support_matrix: dict[str, Any],
    quality_events: list[Any],
    rewrite_attempts: int,
    rewrite_instructions: list[str],
    quality_route: str,
    agent_feedback: dict[str, Any],
    source_recollection_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    final_report = _final_report(
        request=request,
        draft=final_draft,
        evidence_bundle=evidence_bundle,
        verified_findings=verified_findings,
        editor_decision=editor_decision,
            rewrite_attempts=rewrite_attempts,
            agent_feedback=agent_feedback,
            source_recollection_quality=source_recollection_quality,
        )
    report_quality_summary = build_report_quality_summary(
        editor_decision=editor_decision,
        verification_result=verification_result,
        citation_check_result=citation_check_result,
        support_matrix=support_matrix,
        route=quality_route,
    )
    quality_gate_metrics = build_report_quality_gate_metrics(
        evidence_bundle=evidence_bundle,
        verified_findings=verified_findings,
        editor_decision=editor_decision,
        verification_result=verification_result,
        citation_check_result=citation_check_result,
        support_matrix=support_matrix,
        route=quality_route,
        rewrite_attempts=rewrite_attempts,
        human_review_required=False,
    )
    quality_result = build_report_quality_result(
        editor_decision=editor_decision,
        route=quality_route,
        rewrite_attempts=rewrite_attempts,
        human_review_required=False,
        quality_gate_metrics=quality_gate_metrics,
        citation_check_result=citation_check_result,
        agent_feedback_metadata=_quality_result_metadata(
            agent_feedback,
            source_recollection_quality,
        ),
    )
    return with_namespaced_aliases(
        {
            "report_quality_summary": report_quality_summary,
            "quality_events": quality_events,
            "quality_gate_metrics": quality_gate_metrics,
            "quality_result": quality_result,
            "quality_route": quality_route,
            "rewrite_instructions": rewrite_instructions,
            "final_report": final_report,
            "report_markdown": render_markdown(final_report),
        }
    )


def build_blocked_report_outputs(
    *,
    request: Any,
    report_draft: dict[str, Any],
    evidence_bundle: Any,
    editor_decision: dict[str, Any],
    verification_result: dict[str, Any],
    citation_check_result: dict[str, Any],
    support_matrix: dict[str, Any],
    verified_findings: Any,
    quality_events: list[Any],
    agent_feedback: dict[str, Any],
    route: str,
    rewrite_attempts: int,
    human_review_required: bool,
    human_review_request: dict[str, Any] | None = None,
    source_recollection_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report_quality_summary = build_report_quality_summary(
        editor_decision=editor_decision,
        verification_result=verification_result,
        citation_check_result=citation_check_result,
        support_matrix=support_matrix,
        route=route,
    )
    quality_gate_metrics = build_report_quality_gate_metrics(
        evidence_bundle=evidence_bundle,
        verified_findings=verified_findings,
        editor_decision=editor_decision,
        verification_result=verification_result,
        citation_check_result=citation_check_result,
        support_matrix=support_matrix,
        route=route,
        rewrite_attempts=rewrite_attempts,
        human_review_required=human_review_required,
    )
    quality_result = build_report_quality_result(
        editor_decision=editor_decision,
        route=route,
        rewrite_attempts=rewrite_attempts,
        human_review_required=human_review_required,
        quality_gate_metrics=quality_gate_metrics,
        citation_check_result=citation_check_result,
        agent_feedback_metadata=_quality_result_metadata(
            agent_feedback,
            source_recollection_quality,
        ),
    )
    feedback_metadata = _agent_feedback_metadata(agent_feedback)
    source_recollection_metadata = dict(source_recollection_quality or {})
    reasons = list(editor_decision["reasons"]) or [_default_block_reason(route)]
    blocked_report = BlockedReport(
        title=report_draft.get("title") or request_title(request),
        reasons=reasons,
        draft=report_draft,
        metadata={
            "evidence_bundle_id": _field_value(evidence_bundle, "bundle_id"),
            "quality_score": editor_decision["quality_score"],
            "quality_route": route,
            "verification_result": verification_result,
            "citation_check_result": citation_check_result,
            "citation_failure_categories": _list_value(
                citation_check_result.get("failure_categories")
            ),
            "support_matrix": support_matrix,
            "rewrite_attempts": rewrite_attempts,
            "human_review_required": human_review_required,
            **feedback_metadata,
            **source_recollection_metadata,
        },
    )
    outputs: dict[str, Any] = {
        "report_quality_summary": report_quality_summary,
        "quality_events": quality_events,
        "quality_gate_metrics": quality_gate_metrics,
        "quality_result": quality_result,
        "quality_route": route,
        "rewrite_instructions": list(editor_decision["rewrite_instructions"]),
        "blocked_report": blocked_report,
    }
    if human_review_request is not None:
        outputs["human_review_request"] = human_review_request
    return with_namespaced_aliases(outputs)


def build_invalid_report_draft(request: Any, *, reason: str) -> dict[str, Any]:
    return {
        "title": request_title(request),
        "sections": [],
        "metadata": {
            "invalid_report_draft": True,
            "invalid_report_draft_reason": reason,
        },
    }


def build_invalid_report_draft_decision(reason: str) -> dict[str, Any]:
    return {
        "decision": "blocked",
        "quality_score": 0.0,
        "reasons": [f"invalid report draft format: {reason}"],
        "rewrite_instructions": [],
        "raw": {},
    }


def build_invalid_editor_review_decision(reason: str) -> dict[str, Any]:
    return {
        "decision": "blocked",
        "quality_score": 0.0,
        "reasons": [f"invalid editor review decision: {reason}"],
        "rewrite_instructions": [],
        "raw": {},
    }


def build_invalid_human_review_resume_route_decision(reason: str) -> dict[str, Any]:
    return {
        "decision": "blocked",
        "quality_score": 0.0,
        "reasons": [f"invalid human review resume route: {reason}"],
        "rewrite_instructions": [],
        "raw": {},
    }


def request_title(request: Any) -> str:
    topic = _field_value(request, "topic")
    if topic:
        return f"Daily Intelligence: {topic}"
    return "Daily Intelligence Report"


def _final_report(
    *,
    request: Any,
    draft: dict[str, Any],
    evidence_bundle: Any,
    verified_findings: Any,
    editor_decision: dict[str, Any],
    rewrite_attempts: int,
    agent_feedback: dict[str, Any],
    source_recollection_quality: dict[str, Any] | None = None,
) -> FinalReport:
    source_urls = source_urls_from_draft(draft)
    if not source_urls:
        source_urls = source_urls_from_evidence(evidence_bundle)
    metadata = dict(draft.get("metadata") or {})
    metadata.update(
        {
            "evidence_bundle_id": _field_value(evidence_bundle, "bundle_id"),
            "quality_score": editor_decision["quality_score"],
            "accepted_claims_count": _collection_count(verified_findings, "accepted_claims"),
            "rejected_claims_count": _collection_count(verified_findings, "rejected_claims"),
            "uncertain_claims_count": _collection_count(verified_findings, "uncertain_claims"),
            "rewrite_attempts": rewrite_attempts,
            "request_topic": _field_value(request, "topic"),
            **_agent_feedback_metadata(agent_feedback),
            **dict(source_recollection_quality or {}),
        }
    )
    return FinalReport(
        title=draft.get("title") or request_title(request),
        sections=list(draft["sections"]),
        source_urls=sorted(source_urls),
        metadata=metadata,
    )


def _agent_feedback_metadata(agent_feedback: dict[str, Any]) -> dict[str, Any]:
    events = _list_value(agent_feedback.get("events"))
    summary = _to_plain_dict(agent_feedback.get("summary"))
    if not events and not summary:
        return {}
    return {
        "agent_feedback_event_count": len(events),
        "agent_feedback_summary": summary,
    }


def _quality_result_metadata(
    agent_feedback: dict[str, Any],
    source_recollection_quality: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        **_agent_feedback_metadata(agent_feedback),
        **dict(source_recollection_quality or {}),
    }


def _collection_count(value: Any, field_name: str) -> int:
    if value is None:
        return 0
    return len(_list_value(_field_value(value, field_name, default=[])))


def _default_block_reason(route: str) -> str:
    if route == "human_review":
        return "human review required before publication"
    return "editor blocked final publication"
