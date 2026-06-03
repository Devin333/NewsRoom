from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from business.foundation.value_normalization import (
    field_value as _field_value,
    float_value as _float_value,
    string_list as _string_list,
    to_plain_dict as _to_plain_dict,
)
from business.layers.analysis.quality import EditorDecision
from business.boards.cross_board.workflows.daily_intelligence.agent_feedback_finalization_policy import (
    AgentFeedbackFinalizationPolicyDecision,
    select_agent_feedback_finalization_policy,
)
from business.boards.cross_board.workflows.daily_intelligence.evidence_step import quality_event
from business.boards.cross_board.workflows.daily_intelligence.human_review_resume import (
    normalize_daily_human_review_resume_route,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_gate_policy import (
    assess_non_social_media_bypass,
    build_non_social_media_pass_decision,
)
from business.boards.cross_board.workflows.daily_intelligence.source_recollection_finalization_policy import (
    SourceRecollectionFinalizationPolicyDecision,
    select_source_recollection_finalization_policy,
    source_recollection_quality_metadata,
)
from business.boards.cross_board.workflows.daily_intelligence.report_finalization_outputs import (
    build_blocked_report_outputs,
    build_invalid_editor_review_decision,
    build_invalid_report_draft,
    build_invalid_report_draft_decision,
    build_publish_report_outputs,
    request_title,
)
from business.boards.cross_board.workflows.daily_intelligence.report_quality_outputs import (
    build_human_review_request,
)
from business.boards.cross_board.workflows.daily_intelligence.report_draft_normalization import (
    ReportDraftNormalizationError,
    normalize_report_draft,
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


class EditorDecisionNormalizationError(ValueError):
    pass


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
    source_recollection_quality_assessment: Any | None = None
    human_review_resume_route: Any | None = None


def finalize_daily_report(payload: DailyReportFinalizationInput) -> dict[str, Any]:
    """Assemble agentic Daily report outputs without depending on workflow state."""

    request = payload.request
    verification_result = _to_plain_dict(payload.verification_result)
    citation_check_result = _to_plain_dict(payload.citation_check_result)
    support_matrix = _to_plain_dict(payload.support_matrix)
    evidence_bundle = payload.evidence_bundle
    verified_findings = payload.verified_findings
    quality_events = list(payload.quality_events)
    agent_feedback = _agent_feedback_from_input(payload)
    source_recollection_quality = source_recollection_quality_metadata(
        payload.source_recollection_quality_assessment
    )
    try:
        report_draft = normalize_report_draft(payload.report_draft)
    except ReportDraftNormalizationError as exc:
        quality_events.append(
            quality_event(
                "finalize_report_invalid_report_draft",
                reason=str(exc),
            )
        )
        return build_blocked_report_outputs(
            request=request,
            report_draft=build_invalid_report_draft(request, reason=str(exc)),
            evidence_bundle=evidence_bundle,
            editor_decision=build_invalid_report_draft_decision(str(exc)),
            verification_result=verification_result,
            citation_check_result=citation_check_result,
            support_matrix=support_matrix,
            verified_findings=verified_findings,
            quality_events=quality_events,
            agent_feedback=agent_feedback,
            source_recollection_quality=source_recollection_quality,
            route=BLOCKED_ROUTE,
            rewrite_attempts=0,
            human_review_required=False,
        )

    try:
        editor_decision = normalize_editor_decision(payload.editor_review)
    except EditorDecisionNormalizationError as exc:
        quality_events.append(
            quality_event(
                "finalize_report_invalid_editor_review",
                reason=str(exc),
            )
        )
        return build_blocked_report_outputs(
            request=request,
            report_draft=report_draft,
            evidence_bundle=evidence_bundle,
            editor_decision=build_invalid_editor_review_decision(str(exc)),
            verification_result=verification_result,
            citation_check_result=citation_check_result,
            support_matrix=support_matrix,
            verified_findings=verified_findings,
            quality_events=quality_events,
            agent_feedback=agent_feedback,
            source_recollection_quality=source_recollection_quality,
            route=BLOCKED_ROUTE,
            rewrite_attempts=0,
            human_review_required=False,
        )

    human_review_resume_route = normalize_daily_human_review_resume_route(
        payload.human_review_resume_route
    )
    if human_review_resume_route is not None:
        return _finalize_after_human_review_resume(
            payload=payload,
            report_draft=report_draft,
            editor_decision=editor_decision,
            verification_result=verification_result,
            citation_check_result=citation_check_result,
            support_matrix=support_matrix,
            evidence_bundle=evidence_bundle,
            verified_findings=verified_findings,
            quality_events=quality_events,
            agent_feedback=agent_feedback,
            source_recollection_quality=source_recollection_quality,
            human_review_resume_route=human_review_resume_route,
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
    source_recollection_policy_decision = select_source_recollection_finalization_policy(
        payload.source_recollection_quality_assessment,
        strict_gate_required=bypass_assessment.strict_gate_required,
    )
    if source_recollection_policy_decision.should_apply:
        editor_decision = _apply_source_recollection_finalization_policy(
            editor_decision,
            source_recollection_policy_decision,
        )
        decision = editor_decision["decision"]
        rewrite_instructions = list(editor_decision["rewrite_instructions"])
        quality_events.append(
            quality_event(
                "finalize_report_source_recollection_quality_policy_applied",
                recommended_action=source_recollection_policy_decision.recommended_action,
                assessment_decision=(
                    source_recollection_policy_decision.assessment or {}
                ).get("decision"),
                assessment_route=(
                    source_recollection_policy_decision.assessment or {}
                ).get("route"),
                failed_thresholds=(
                    source_recollection_policy_decision.assessment or {}
                ).get("failed_thresholds"),
            )
        )

    if decision == PASS_DECISION:
        return build_publish_report_outputs(
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
            source_recollection_quality=source_recollection_quality,
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
                return build_publish_report_outputs(
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
                    source_recollection_quality=source_recollection_quality,
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
        return build_blocked_report_outputs(
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
            source_recollection_quality=source_recollection_quality,
            route=HUMAN_REVIEW_ROUTE,
            rewrite_attempts=0,
            human_review_required=True,
            human_review_request=build_human_review_request(
                request=request,
                report_draft=report_draft,
                evidence_bundle=evidence_bundle,
                editor_decision=editor_decision,
                verification_result=verification_result,
                fallback_title=request_title(request),
                source_recollection_quality=source_recollection_quality,
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
    return build_blocked_report_outputs(
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
        source_recollection_quality=source_recollection_quality,
        route=BLOCKED_ROUTE,
        rewrite_attempts=1 if decision == REWRITE_REQUIRED_DECISION else 0,
        human_review_required=False,
    )


def _finalize_after_human_review_resume(
    *,
    payload: DailyReportFinalizationInput,
    report_draft: dict[str, Any],
    editor_decision: dict[str, Any],
    verification_result: dict[str, Any],
    citation_check_result: dict[str, Any],
    support_matrix: dict[str, Any],
    evidence_bundle: Any,
    verified_findings: Any,
    quality_events: list[Any],
    agent_feedback: dict[str, Any],
    source_recollection_quality: dict[str, Any] | None,
    human_review_resume_route: dict[str, Any],
) -> dict[str, Any]:
    route = str(human_review_resume_route["route"])
    reason = str(
        human_review_resume_route.get("reason")
        or _human_review_resume_default_reason(route)
    )
    quality_events.append(
        quality_event(
            "finalize_report_human_review_resume_route_applied",
            approval_id=human_review_resume_route.get("approval_id"),
            decision=human_review_resume_route.get("decision"),
            route=route,
            next_step_id=human_review_resume_route.get("next_step_id"),
        )
    )
    reviewed_decision = _human_review_editor_decision(
        editor_decision,
        human_review_resume_route,
        reason=reason,
    )
    if route == PUBLISH_ROUTE:
        return _with_human_review_resume_route(
            build_publish_report_outputs(
                request=payload.request,
                final_draft=report_draft,
                evidence_bundle=evidence_bundle,
                verified_findings=verified_findings,
                editor_decision=reviewed_decision,
                verification_result=verification_result,
                citation_check_result=citation_check_result,
                support_matrix=support_matrix,
                quality_events=[
                    *quality_events,
                    quality_event(
                        "finalize_report_published_after_human_review",
                        approval_id=human_review_resume_route.get("approval_id"),
                    ),
                ],
                rewrite_attempts=0,
                rewrite_instructions=[],
                quality_route=PUBLISH_ROUTE,
                agent_feedback=agent_feedback,
                source_recollection_quality=source_recollection_quality,
            ),
            human_review_resume_route,
        )
    if route == REWRITE_ROUTE:
        edited_report_draft = _normalized_edited_draft(payload, quality_events)
        if edited_report_draft is not None:
            invalid_sources = sources_outside_evidence(edited_report_draft, evidence_bundle)
            if not invalid_sources:
                return _with_human_review_resume_route(
                    build_publish_report_outputs(
                        request=payload.request,
                        final_draft=edited_report_draft,
                        evidence_bundle=evidence_bundle,
                        verified_findings=verified_findings,
                        editor_decision=reviewed_decision,
                        verification_result=verification_result,
                        citation_check_result=citation_check_result,
                        support_matrix=support_matrix,
                        quality_events=[
                            *quality_events,
                            quality_event(
                                "finalize_report_published_after_human_review_changes",
                                approval_id=human_review_resume_route.get("approval_id"),
                            ),
                        ],
                        rewrite_attempts=1,
                        rewrite_instructions=list(
                            reviewed_decision.get("rewrite_instructions") or []
                        ),
                        quality_route=REWRITE_ROUTE,
                        agent_feedback=agent_feedback,
                        source_recollection_quality=source_recollection_quality,
                    ),
                    human_review_resume_route,
                )
            reviewed_decision = _append_editor_reason(
                reviewed_decision,
                "human review changes cite sources outside evidence bundle: "
                + ", ".join(invalid_sources),
            )
        else:
            reviewed_decision = _append_editor_reason(
                reviewed_decision,
                "human review requested changes but no edited draft was provided",
            )
    return _with_human_review_resume_route(
        build_blocked_report_outputs(
            request=payload.request,
            report_draft=report_draft,
            evidence_bundle=evidence_bundle,
            editor_decision=reviewed_decision,
            verification_result=verification_result,
            citation_check_result=citation_check_result,
            support_matrix=support_matrix,
            verified_findings=verified_findings,
            quality_events=[
                *quality_events,
                quality_event(
                    "finalize_report_blocked_after_human_review",
                    approval_id=human_review_resume_route.get("approval_id"),
                    route=route,
                ),
            ],
            agent_feedback=agent_feedback,
            source_recollection_quality=source_recollection_quality,
            route=BLOCKED_ROUTE,
            rewrite_attempts=1 if route == REWRITE_ROUTE else 0,
            human_review_required=False,
        ),
        human_review_resume_route,
    )


def _normalized_edited_draft(
    payload: DailyReportFinalizationInput,
    quality_events: list[Any],
) -> dict[str, Any] | None:
    if payload.edited_report_draft is None:
        return None
    try:
        return normalize_report_draft(payload.edited_report_draft)
    except ReportDraftNormalizationError as exc:
        quality_events.append(
            quality_event(
                "finalize_report_invalid_human_review_edit",
                reason=str(exc),
            )
        )
        return None


def _human_review_editor_decision(
    editor_decision: dict[str, Any],
    human_review_resume_route: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    next_decision = dict(editor_decision)
    route = str(human_review_resume_route["route"])
    if route == PUBLISH_ROUTE:
        next_decision["decision"] = PASS_DECISION
        next_decision["rewrite_instructions"] = []
    elif route == REWRITE_ROUTE:
        next_decision["decision"] = REWRITE_REQUIRED_DECISION
        instructions = list(next_decision.get("rewrite_instructions") or [])
        if reason not in instructions:
            instructions.append(reason)
        next_decision["rewrite_instructions"] = instructions
    else:
        next_decision["decision"] = BLOCK_DECISION
        next_decision["rewrite_instructions"] = []
    reasons = list(next_decision.get("reasons") or [])
    if reason not in reasons:
        reasons.append(reason)
    next_decision["reasons"] = reasons
    raw = dict(next_decision.get("raw") or {})
    raw["human_review_resume_route"] = dict(human_review_resume_route)
    next_decision["raw"] = raw
    return next_decision


def _human_review_resume_default_reason(route: str) -> str:
    if route == PUBLISH_ROUTE:
        return "human reviewer approved publication"
    if route == REWRITE_ROUTE:
        return "human reviewer requested changes"
    return "human reviewer rejected publication"


def _with_human_review_resume_route(
    outputs: dict[str, Any],
    human_review_resume_route: dict[str, Any],
) -> dict[str, Any]:
    outputs["human_review_resume_route"] = dict(human_review_resume_route)
    outputs["quality.human_review_resume_route"] = outputs["human_review_resume_route"]
    return outputs


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


def _apply_source_recollection_finalization_policy(
    editor_decision: dict[str, Any],
    policy_decision: SourceRecollectionFinalizationPolicyDecision,
) -> dict[str, Any]:
    next_decision = _append_editor_reason(
        editor_decision,
        _source_recollection_policy_reason(policy_decision),
    )
    if next_decision["decision"] != BLOCK_DECISION:
        next_decision["decision"] = HUMAN_REVIEW_REQUIRED_DECISION
        next_decision["rewrite_instructions"] = []
    return next_decision


def _agent_feedback_policy_reason(
    policy_decision: AgentFeedbackFinalizationPolicyDecision,
) -> str:
    recommendation = policy_decision.recommendation or {}
    reason = str(recommendation.get("reason") or "agent feedback policy recommendation").strip()
    return f"agent feedback policy recommended {policy_decision.recommended_action}: {reason}"


def _source_recollection_policy_reason(
    policy_decision: SourceRecollectionFinalizationPolicyDecision,
) -> str:
    assessment = policy_decision.assessment or {}
    issues = _string_list(assessment.get("issues", []))
    detail = ", ".join(issues) if issues else "source recollection quality threshold missed"
    return f"source recollection quality recommended human review: {detail}"


def _agent_feedback_from_input(payload: DailyReportFinalizationInput) -> dict[str, Any]:
    return {
        "events": list(payload.agent_feedback_events or []),
        "summary": _to_plain_dict(payload.agent_feedback_summary),
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
        raise EditorDecisionNormalizationError(
            f"unsupported editor decision: {value!r}; expected one of {allowed}"
        )
    return decision
