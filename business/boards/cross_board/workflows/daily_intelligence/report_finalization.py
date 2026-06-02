from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from business.foundation.models.report_output import BlockedReport, FinalReport, render_markdown
from business.foundation.value_normalization import (
    field_value as _field_value,
    float_value as _float_value,
    list_value as _list_value,
    string_list as _string_list,
    to_plain_dict as _to_plain_dict,
)
from business.layers.analysis.quality import EditorDecision
from business.boards.cross_board.workflows.daily_intelligence.agent_feedback_finalization_policy import (
    AgentFeedbackFinalizationPolicyDecision,
    select_agent_feedback_finalization_policy,
)
from business.boards.cross_board.workflows.daily_intelligence.evidence_step import quality_event
from business.boards.cross_board.workflows.daily_intelligence.quality_gate_policy import (
    assess_non_social_media_bypass,
    build_non_social_media_pass_decision,
)
from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    with_namespaced_aliases,
)
from business.boards.cross_board.workflows.daily_intelligence.report_quality_outputs import (
    build_human_review_request,
    build_report_quality_gate_metrics,
    build_report_quality_result,
    build_report_quality_summary,
)
from business.boards.cross_board.workflows.daily_intelligence.report_draft_normalization import (
    ReportDraftNormalizationError,
    normalize_report_draft,
    source_urls_from_draft,
    source_urls_from_evidence,
    sources_outside_evidence,
)


PUBLISH_ROUTE = "final"
BLOCKED_ROUTE = "blocked"
HUMAN_REVIEW_ROUTE = "human_review"
REWRITE_ROUTE = "rewrite"

PASS_DECISION = EditorDecision.PASS.value
REWRITE_REQUIRED_DECISION = EditorDecision.REWRITE_REQUIRED.value
HUMAN_REVIEW_REQUIRED_DECISION = EditorDecision.HUMAN_REVIEW.value
BLOCK_DECISION = EditorDecision.BLOCKED.value

_DECISION_ALIASES = {
    "blocked": BLOCK_DECISION,
    "block": BLOCK_DECISION,
    "human_review": HUMAN_REVIEW_REQUIRED_DECISION,
    "human_review_required": HUMAN_REVIEW_REQUIRED_DECISION,
    "pass": PASS_DECISION,
    "publish": PASS_DECISION,
    "rewrite": REWRITE_REQUIRED_DECISION,
    "rewrite_required": REWRITE_REQUIRED_DECISION,
}


@dataclass(frozen=True)
class DailyReportFinalizationInput:
    request: Any
    report_draft: Any
    editor_review: Any
    verification_result: Any
    citation_check_result: Any
    support_matrix: Any
    evidence_bundle: Any
    verified_findings: Any
    quality_events: list[Any]
    edited_report_draft: Any | None = None
    agent_feedback_events: list[Any] | None = None
    agent_feedback_summary: Any | None = None


def finalize_daily_report(payload: DailyReportFinalizationInput) -> dict[str, Any]:
    """Assemble agentic Daily report outputs without depending on workflow state."""

    request = payload.request
    editor_decision = normalize_editor_decision(payload.editor_review)
    verification_result = _to_plain_dict(payload.verification_result)
    citation_check_result = _to_plain_dict(payload.citation_check_result)
    support_matrix = _to_plain_dict(payload.support_matrix)
    evidence_bundle = payload.evidence_bundle
    verified_findings = payload.verified_findings
    quality_events = list(payload.quality_events)
    agent_feedback = _agent_feedback_from_input(payload)
    try:
        report_draft = normalize_report_draft(payload.report_draft)
    except ReportDraftNormalizationError as exc:
        quality_events.append(
            quality_event(
                "finalize_report_invalid_report_draft",
                reason=str(exc),
            )
        )
        return _blocked_outputs(
            request=request,
            report_draft=_invalid_report_draft(request, reason=str(exc)),
            evidence_bundle=evidence_bundle,
            editor_decision=_invalid_report_draft_decision(str(exc)),
            verification_result=verification_result,
            citation_check_result=citation_check_result,
            support_matrix=support_matrix,
            verified_findings=verified_findings,
            quality_events=quality_events,
            agent_feedback=agent_feedback,
            route=BLOCKED_ROUTE,
            rewrite_attempts=0,
            human_review_required=False,
        )

    decision = editor_decision["decision"]
    rewrite_instructions = list(editor_decision["rewrite_instructions"])
    quality_score = editor_decision["quality_score"]
    bypass_assessment = assess_non_social_media_bypass(evidence_bundle, decision)
    if bypass_assessment.should_bypass:
        original_decision = decision
        editor_decision = build_non_social_media_pass_decision(editor_decision)
        decision = PASS_DECISION
        rewrite_instructions = []
        quality_events.append(
            quality_event(
                "finalize_report_bypassed_non_social_media",
                original_decision=original_decision,
                quality_score=quality_score,
                **bypass_assessment.event_metadata,
            )
        )
    feedback_policy_decision = select_agent_feedback_finalization_policy(
        agent_feedback.get("summary"),
        strict_gate_required=bypass_assessment.strict_gate_required,
    )
    if feedback_policy_decision.should_apply:
        editor_decision = _apply_agent_feedback_finalization_policy(
            editor_decision,
            feedback_policy_decision,
        )
        decision = editor_decision["decision"]
        rewrite_instructions = list(editor_decision["rewrite_instructions"])
        quality_events.append(
            quality_event(
                "finalize_report_agent_feedback_policy_applied",
                recommended_action=feedback_policy_decision.recommended_action,
                recommendation_id=(
                    feedback_policy_decision.recommendation or {}
                ).get("recommendation_id"),
                target_agent_id=(
                    feedback_policy_decision.recommendation or {}
                ).get("target_agent_id"),
            )
        )

    if decision == PASS_DECISION:
        return _publish_outputs(
            request=request,
            final_draft=report_draft,
            evidence_bundle=evidence_bundle,
            verified_findings=verified_findings,
            editor_decision=editor_decision,
            verification_result=verification_result,
            citation_check_result=citation_check_result,
            support_matrix=support_matrix,
            quality_events=[
                *quality_events,
                quality_event(
                    "finalize_report_published",
                    decision=decision,
                    quality_score=quality_score,
                ),
            ],
            rewrite_attempts=0,
            rewrite_instructions=rewrite_instructions,
            quality_route=PUBLISH_ROUTE,
            agent_feedback=agent_feedback,
        )

    if decision == REWRITE_REQUIRED_DECISION:
        edited_report_draft = None
        edited_report_draft_invalid = False
        try:
            if payload.edited_report_draft is not None:
                edited_report_draft = normalize_report_draft(payload.edited_report_draft)
        except ReportDraftNormalizationError as exc:
            edited_report_draft_invalid = True
            editor_decision = _append_editor_reason(
                editor_decision,
                f"edited report draft is invalid: {exc}",
            )
            quality_events.append(
                quality_event(
                    "finalize_report_invalid_edited_report_draft",
                    reason=str(exc),
                    quality_score=quality_score,
                )
            )
        if edited_report_draft is not None:
            invalid_sources = sources_outside_evidence(
                edited_report_draft,
                evidence_bundle,
            )
            if not invalid_sources:
                return _publish_outputs(
                    request=request,
                    final_draft=edited_report_draft,
                    evidence_bundle=evidence_bundle,
                    verified_findings=verified_findings,
                    editor_decision=editor_decision,
                    verification_result=verification_result,
                    citation_check_result=citation_check_result,
                    support_matrix=support_matrix,
                    quality_events=[
                        *quality_events,
                        quality_event(
                            "finalize_report_published_after_edit",
                            decision=decision,
                            quality_score=quality_score,
                        ),
                    ],
                    rewrite_attempts=1,
                    rewrite_instructions=rewrite_instructions,
                    quality_route=REWRITE_ROUTE,
                    agent_feedback=agent_feedback,
                )
            editor_decision = _append_editor_reason(
                editor_decision,
                "edited report draft cites sources outside evidence bundle: "
                + ", ".join(invalid_sources),
            )
            quality_events.append(
                quality_event(
                    "finalize_report_rewrite_source_boundary_failed",
                    invalid_sources=invalid_sources,
                    quality_score=quality_score,
                )
            )
        elif not edited_report_draft_invalid:
            quality_events.append(
                quality_event(
                    "finalize_report_rewrite_missing_edit",
                    quality_score=quality_score,
                )
            )

    if decision == HUMAN_REVIEW_REQUIRED_DECISION:
        quality_events.append(
            quality_event(
                "finalize_report_human_review_requested",
                quality_score=quality_score,
                reason_count=len(editor_decision["reasons"]),
            )
        )
        return _blocked_outputs(
            request=request,
            report_draft=report_draft,
            evidence_bundle=evidence_bundle,
            editor_decision=editor_decision,
            verification_result=verification_result,
            citation_check_result=citation_check_result,
            support_matrix=support_matrix,
            verified_findings=verified_findings,
            quality_events=quality_events,
            agent_feedback=agent_feedback,
            route=HUMAN_REVIEW_ROUTE,
            rewrite_attempts=0,
            human_review_required=True,
            human_review_request=build_human_review_request(
                request=request,
                report_draft=report_draft,
                evidence_bundle=evidence_bundle,
                editor_decision=editor_decision,
                verification_result=verification_result,
                fallback_title=_request_title(request),
            ),
        )

    quality_events.append(
        quality_event(
            "finalize_report_blocked",
            decision=decision,
            quality_score=quality_score,
            reason_count=len(editor_decision["reasons"]),
        )
    )
    return _blocked_outputs(
        request=request,
        report_draft=report_draft,
        evidence_bundle=evidence_bundle,
        editor_decision=editor_decision,
        verification_result=verification_result,
        citation_check_result=citation_check_result,
        support_matrix=support_matrix,
        verified_findings=verified_findings,
        quality_events=quality_events,
        agent_feedback=agent_feedback,
        route=BLOCKED_ROUTE,
        rewrite_attempts=1 if decision == REWRITE_REQUIRED_DECISION else 0,
        human_review_required=False,
    )


def normalize_editor_decision(editor_review: Any) -> dict[str, Any]:
    review = _unwrap_editor_review(editor_review)
    raw_decision = _field_value(review, "decision")
    decision = _normalize_decision(raw_decision)
    reasons = _string_list(_field_value(review, "reasons", default=[]))
    rewrite_instructions = _string_list(
        _field_value(
            review,
            "rewrite_instructions",
            default=_field_value(review, "required_changes", default=[]),
        )
    )
    quality_score = _float_value(_field_value(review, "quality_score"), default=0.0)
    return {
        "decision": decision,
        "quality_score": quality_score,
        "reasons": reasons,
        "rewrite_instructions": rewrite_instructions,
        "raw": _to_plain_dict(editor_review),
    }


def _append_editor_reason(editor_decision: dict[str, Any], reason: str) -> dict[str, Any]:
    next_decision = dict(editor_decision)
    reasons = list(next_decision.get("reasons") or [])
    reasons.append(reason)
    next_decision["reasons"] = reasons
    return next_decision


def _apply_agent_feedback_finalization_policy(
    editor_decision: dict[str, Any],
    policy_decision: AgentFeedbackFinalizationPolicyDecision,
) -> dict[str, Any]:
    recommended_action = policy_decision.recommended_action
    recommendation = policy_decision.recommendation or {}
    next_decision = _append_editor_reason(
        editor_decision,
        _agent_feedback_policy_reason(policy_decision),
    )
    if recommended_action == "block":
        next_decision["decision"] = BLOCK_DECISION
    elif recommended_action == "human_review":
        next_decision["decision"] = HUMAN_REVIEW_REQUIRED_DECISION
    elif recommended_action == "rewrite":
        next_decision["decision"] = REWRITE_REQUIRED_DECISION
        rewrite_instructions = list(next_decision.get("rewrite_instructions") or [])
        reason = str(recommendation.get("reason") or "").strip()
        if reason and reason not in rewrite_instructions:
            rewrite_instructions.append(reason)
        next_decision["rewrite_instructions"] = rewrite_instructions
    return next_decision


def _agent_feedback_policy_reason(
    policy_decision: AgentFeedbackFinalizationPolicyDecision,
) -> str:
    recommendation = policy_decision.recommendation or {}
    reason = str(recommendation.get("reason") or "agent feedback policy recommendation").strip()
    return f"agent feedback policy recommended {policy_decision.recommended_action}: {reason}"


def _publish_outputs(
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
) -> dict[str, Any]:
    final_report = _final_report(
        request=request,
        draft=final_draft,
        evidence_bundle=evidence_bundle,
        verified_findings=verified_findings,
        editor_decision=editor_decision,
        rewrite_attempts=rewrite_attempts,
        agent_feedback=agent_feedback,
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
        agent_feedback_metadata=_agent_feedback_metadata(agent_feedback),
    )
    return with_namespaced_aliases({
        "report_quality_summary": report_quality_summary,
        "quality_events": quality_events,
        "quality_gate_metrics": quality_gate_metrics,
        "quality_result": quality_result,
        "quality_route": quality_route,
        "rewrite_instructions": rewrite_instructions,
        "final_report": final_report,
        "report_markdown": render_markdown(final_report),
    })


def _blocked_outputs(
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
        agent_feedback_metadata=_agent_feedback_metadata(agent_feedback),
    )
    feedback_metadata = _agent_feedback_metadata(agent_feedback)
    reasons = list(editor_decision["reasons"]) or [_default_block_reason(route)]
    blocked_report = BlockedReport(
        title=report_draft.get("title") or _request_title(request),
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


def _final_report(
    *,
    request: Any,
    draft: dict[str, Any],
    evidence_bundle: Any,
    verified_findings: Any,
    editor_decision: dict[str, Any],
    rewrite_attempts: int,
    agent_feedback: dict[str, Any],
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
        }
    )
    return FinalReport(
        title=draft.get("title") or _request_title(request),
        sections=list(draft["sections"]),
        source_urls=sorted(source_urls),
        metadata=metadata,
    )


def _invalid_report_draft(request: Any, *, reason: str) -> dict[str, Any]:
    return {
        "title": _request_title(request),
        "sections": [],
        "metadata": {
            "invalid_report_draft": True,
            "invalid_report_draft_reason": reason,
        },
    }


def _invalid_report_draft_decision(reason: str) -> dict[str, Any]:
    return {
        "decision": BLOCK_DECISION,
        "quality_score": 0.0,
        "reasons": [f"invalid report draft format: {reason}"],
        "rewrite_instructions": [],
        "raw": {},
    }


def _agent_feedback_from_input(payload: DailyReportFinalizationInput) -> dict[str, Any]:
    return {
        "events": list(payload.agent_feedback_events or []),
        "summary": _to_plain_dict(payload.agent_feedback_summary),
    }


def _agent_feedback_metadata(agent_feedback: dict[str, Any]) -> dict[str, Any]:
    events = _list_value(agent_feedback.get("events"))
    summary = _to_plain_dict(agent_feedback.get("summary"))
    if not events and not summary:
        return {}
    return {
        "agent_feedback_event_count": len(events),
        "agent_feedback_summary": summary,
    }


def _unwrap_editor_review(editor_review: Any) -> Any:
    if (
        isinstance(editor_review, Mapping)
        and "editor_review" in editor_review
        and "decision" not in editor_review
    ):
        return editor_review["editor_review"]
    return editor_review


def _normalize_decision(value: Any) -> str:
    if hasattr(value, "value"):
        value = value.value
    normalized = str(value or "").strip().lower()
    decision = _DECISION_ALIASES.get(normalized)
    if decision is None:
        allowed = ", ".join(sorted(set(_DECISION_ALIASES.values())))
        raise ValueError(f"unsupported editor decision: {value!r}; expected one of {allowed}")
    return decision


def _request_title(request: Any) -> str:
    topic = _field_value(request, "topic")
    if topic:
        return f"Daily Intelligence: {topic}"
    return "Daily Intelligence Report"


def _collection_count(value: Any, field_name: str) -> int:
    if value is None:
        return 0
    return len(_list_value(_field_value(value, field_name, default=[])))


def _default_block_reason(route: str) -> str:
    if route == HUMAN_REVIEW_ROUTE:
        return "human review required before publication"
    return "editor blocked final publication"
