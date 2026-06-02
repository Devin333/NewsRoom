from __future__ import annotations

from typing import Any

from framework.workflow import DataBufferReadPermissionError, StepScopedDataBufferView
from business.boards.cross_board.workflows.daily_intelligence.agent_feedback_models import (
    HUMAN_REVIEW_TARGET,
    PUBLICATION_GATE_TARGET,
    DailyAgentFeedbackEvent,
    DailyAgentFeedbackSummary,
)
from business.boards.cross_board.workflows.daily_intelligence.agent_feedback_policy import (
    DailyAgentFeedbackPolicyService,
)
from business.boards.cross_board.workflows.daily_intelligence.agents import (
    EDITOR_AGENT_ID,
    VERIFIER_AGENT_ID,
    WRITER_AGENT_ID,
)
from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    with_namespaced_aliases,
)


MAX_AGENT_FEEDBACK_REWRITE_ROUNDS = 1


def collect_agent_feedback(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    editor_review = _optional_buffer_dict(buffer, "editor_review")
    events = DailyAgentFeedbackCollector().collect(
        verification_result=_optional_buffer_dict(buffer, "verification_result"),
        citation_check_result=_optional_buffer_dict(buffer, "citation_check_result"),
        support_matrix=_optional_buffer_dict(buffer, "support_matrix"),
        editor_review=editor_review,
    )
    summary = summarize_agent_feedback(events)
    loop_state = _next_feedback_loop_state(
        buffer,
        summary,
        writer_rewrite_routable=not bool(editor_review),
    )
    return with_namespaced_aliases({
        "agent_feedback_events": events,
        "agent_feedback_summary": summary,
        "agent_feedback_route": _feedback_route(
            summary,
            loop_state,
            editor_review_available=bool(editor_review),
        ),
        "agent_feedback_loop_state": loop_state,
    })


class DailyAgentFeedbackCollector:
    def collect(
        self,
        *,
        verification_result: dict[str, Any],
        citation_check_result: dict[str, Any],
        support_matrix: dict[str, Any],
        editor_review: dict[str, Any],
    ) -> list[DailyAgentFeedbackEvent]:
        events: list[DailyAgentFeedbackEvent] = []
        self._collect_verifier_feedback(events, verification_result, citation_check_result, support_matrix)
        self._collect_editor_feedback(events, editor_review)
        return [
            event.model_copy(update={"feedback_id": f"daily-agent-feedback-{index + 1}"})
            for index, event in enumerate(events)
        ]

    def _collect_verifier_feedback(
        self,
        events: list[DailyAgentFeedbackEvent],
        verification_result: dict[str, Any],
        citation_check_result: dict[str, Any],
        support_matrix: dict[str, Any],
    ) -> None:
        status = str(verification_result.get("status") or "").strip().lower()
        risk_level = str(verification_result.get("risk_level") or "medium").strip().lower()
        unsupported_claims = _list_value(verification_result.get("unsupported_claims"))
        missing_citations = _list_value(verification_result.get("missing_citations"))
        reasons = _string_list(verification_result.get("reasons"))
        if status == "needs_rewrite":
            events.append(
                _feedback_event(
                    source_agent_id=VERIFIER_AGENT_ID,
                    target_agent_id=WRITER_AGENT_ID,
                    feedback_type="verification_rewrite_request",
                    severity=_severity_from_risk(risk_level),
                    requested_action="rewrite",
                    reason=_first_text(reasons, default="verifier requested writer rewrite"),
                    metadata={
                        "verification_status": status,
                        "risk_level": risk_level,
                        "unsupported_claims_count": len(unsupported_claims),
                        "missing_citations_count": len(missing_citations),
                    },
                )
            )
        elif status == "blocked":
            events.append(
                _feedback_event(
                    source_agent_id=VERIFIER_AGENT_ID,
                    target_agent_id=PUBLICATION_GATE_TARGET,
                    feedback_type="verification_block_request",
                    severity="block",
                    requested_action="block",
                    reason=_first_text(reasons, default="verifier blocked publication"),
                    metadata={
                        "verification_status": status,
                        "risk_level": risk_level,
                        "unsupported_claims_count": len(unsupported_claims),
                        "missing_citations_count": len(missing_citations),
                    },
                )
            )
        if missing_citations:
            events.append(
                _feedback_event(
                    source_agent_id=VERIFIER_AGENT_ID,
                    target_agent_id=WRITER_AGENT_ID,
                    feedback_type="missing_citation_feedback",
                    severity=_severity_from_risk(risk_level),
                    requested_action="rewrite",
                    reason="verifier found missing citations",
                    metadata={"missing_citations": missing_citations},
                )
            )
        unsupported_sources = _list_value(citation_check_result.get("unsupported_urls"))
        unknown_sources = _list_value(citation_check_result.get("unknown_urls"))
        unsupported_sections = _list_value(support_matrix.get("unsupported_sections"))
        if unsupported_sources or unknown_sources or unsupported_sections:
            events.append(
                _feedback_event(
                    source_agent_id=VERIFIER_AGENT_ID,
                    target_agent_id=WRITER_AGENT_ID,
                    feedback_type="evidence_boundary_feedback",
                    severity=_severity_from_risk(risk_level),
                    requested_action="rewrite",
                    reason="verifier found citations outside accepted evidence",
                    metadata={
                        "unsupported_urls": unsupported_sources,
                        "unknown_urls": unknown_sources,
                        "unsupported_sections": unsupported_sections,
                    },
                )
            )

    def _collect_editor_feedback(
        self,
        events: list[DailyAgentFeedbackEvent],
        editor_review: dict[str, Any],
    ) -> None:
        decision = str(editor_review.get("decision") or "").strip().lower()
        reasons = _string_list(editor_review.get("reasons"))
        rewrite_instructions = _string_list(editor_review.get("rewrite_instructions"))
        if decision == "rewrite_required":
            events.append(
                _feedback_event(
                    source_agent_id=EDITOR_AGENT_ID,
                    target_agent_id=WRITER_AGENT_ID,
                    feedback_type="editor_rewrite_request",
                    severity=_severity_from_quality_score(editor_review.get("quality_score")),
                    requested_action="rewrite",
                    reason=_first_text(rewrite_instructions, reasons, default="editor requested writer rewrite"),
                    metadata={
                        "quality_score": editor_review.get("quality_score"),
                        "rewrite_instructions": rewrite_instructions,
                        "reasons": reasons,
                    },
                )
            )
        elif decision == "human_review_required":
            events.append(
                _feedback_event(
                    source_agent_id=EDITOR_AGENT_ID,
                    target_agent_id=HUMAN_REVIEW_TARGET,
                    feedback_type="editor_human_review_request",
                    severity="warning",
                    requested_action="human_review",
                    reason=_first_text(reasons, default="editor requested human review"),
                    metadata={
                        "quality_score": editor_review.get("quality_score"),
                        "reasons": reasons,
                    },
                )
            )
        elif decision == "block":
            events.append(
                _feedback_event(
                    source_agent_id=EDITOR_AGENT_ID,
                    target_agent_id=PUBLICATION_GATE_TARGET,
                    feedback_type="editor_block_request",
                    severity="block",
                    requested_action="block",
                    reason=_first_text(reasons, default="editor blocked publication"),
                    metadata={
                        "quality_score": editor_review.get("quality_score"),
                        "reasons": reasons,
                    },
                )
            )


def summarize_agent_feedback(events: list[DailyAgentFeedbackEvent]) -> DailyAgentFeedbackSummary:
    target_agent_ids = _dedupe_text([event.target_agent_id for event in events])
    policy_recommendations = DailyAgentFeedbackPolicyService().recommend(events)
    return DailyAgentFeedbackSummary(
        event_count=len(events),
        rewrite_request_count=sum(1 for event in events if event.requested_action == "rewrite"),
        human_review_request_count=sum(1 for event in events if event.requested_action == "human_review"),
        block_request_count=sum(1 for event in events if event.requested_action == "block"),
        highest_severity=_highest_severity(events),
        target_agent_ids=target_agent_ids,
        policy_recommendations=policy_recommendations,
        metadata={
            "feedback_types": _dedupe_text([event.feedback_type for event in events]),
            "policy_recommendation_count": len(policy_recommendations),
        },
    )


def _feedback_route(
    summary: DailyAgentFeedbackSummary,
    loop_state: dict[str, Any],
    *,
    editor_review_available: bool,
) -> dict[str, Any]:
    if (
        not editor_review_available
        and loop_state["rewrite_requested"]
        and not loop_state["rewrite_exhausted"]
    ):
        return {
            "decision": "retry_required",
            "next_step_id": "writer_agent",
            "target_agent_id": WRITER_AGENT_ID,
            "reason": "agent feedback requested writer rewrite",
            "rewrite_round": loop_state["rewrite_rounds"],
            "max_rewrite_rounds": loop_state["max_rewrite_rounds"],
        }
    if (
        not editor_review_available
        and loop_state["rewrite_requested"]
        and loop_state["rewrite_exhausted"]
    ):
        return {
            "decision": "blocked",
            "next_step_id": "finalize_report",
            "target_agent_id": PUBLICATION_GATE_TARGET,
            "reason": "agent feedback rewrite rounds exhausted",
            "rewrite_round": loop_state["rewrite_rounds"],
            "max_rewrite_rounds": loop_state["max_rewrite_rounds"],
        }
    if summary.block_request_count:
        return {
            "decision": "blocked",
            "next_step_id": "finalize_report",
            "target_agent_id": PUBLICATION_GATE_TARGET,
            "reason": "agent feedback requested publication block",
            "rewrite_round": loop_state["rewrite_rounds"],
            "max_rewrite_rounds": loop_state["max_rewrite_rounds"],
        }
    next_step_id = "finalize_report" if editor_review_available else "editor_agent"
    target_agent_id = "daily.finalize_report" if editor_review_available else EDITOR_AGENT_ID
    return {
        "decision": "pass",
        "next_step_id": next_step_id,
        "target_agent_id": target_agent_id,
        "reason": "no bounded agent feedback retry required",
        "rewrite_round": loop_state["rewrite_rounds"],
        "max_rewrite_rounds": loop_state["max_rewrite_rounds"],
    }


def _next_feedback_loop_state(
    buffer: StepScopedDataBufferView,
    summary: DailyAgentFeedbackSummary,
    *,
    writer_rewrite_routable: bool,
) -> dict[str, Any]:
    previous = _optional_buffer_dict(buffer, "agent_feedback_loop_state")
    previous_rounds = _int_value(previous.get("rewrite_rounds"), default=0)
    rewrite_requested = writer_rewrite_routable and _writer_rewrite_requested(summary)
    rewrite_exhausted = (
        rewrite_requested
        and previous_rounds >= MAX_AGENT_FEEDBACK_REWRITE_ROUNDS
    )
    rewrite_rounds = previous_rounds
    if rewrite_requested and not rewrite_exhausted:
        rewrite_rounds += 1
    return {
        "rewrite_rounds": rewrite_rounds,
        "max_rewrite_rounds": MAX_AGENT_FEEDBACK_REWRITE_ROUNDS,
        "rewrite_requested": rewrite_requested,
        "rewrite_exhausted": rewrite_exhausted,
    }


def _writer_rewrite_requested(summary: DailyAgentFeedbackSummary) -> bool:
    if summary.rewrite_request_count <= 0:
        return False
    for recommendation in summary.policy_recommendations:
        if (
            recommendation.recommended_action == "rewrite"
            and recommendation.target_agent_id == WRITER_AGENT_ID
        ):
            return True
    return WRITER_AGENT_ID in summary.target_agent_ids


def _feedback_event(
    *,
    source_agent_id: str,
    target_agent_id: str,
    feedback_type: str,
    severity: str,
    requested_action: str,
    reason: str,
    metadata: dict[str, Any],
) -> DailyAgentFeedbackEvent:
    return DailyAgentFeedbackEvent(
        feedback_id="pending",
        source_agent_id=source_agent_id,
        target_agent_id=target_agent_id,
        feedback_type=feedback_type,
        severity=severity,
        requested_action=requested_action,
        reason=reason,
        metadata={key: value for key, value in metadata.items() if value not in (None, [], {})},
    )


def _dict_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        payload = value.to_dict()
        return payload if isinstance(payload, dict) else {}
    return {}


def _optional_buffer_dict(buffer: StepScopedDataBufferView, key: str) -> dict[str, Any]:
    try:
        if not buffer.exists(key):
            return {}
        return _dict_value(buffer.read(key, required=False))
    except DataBufferReadPermissionError:
        return {}


def _list_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if value is None:
        return []
    return [value]


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in _list_value(value) if str(item).strip()]


def _first_text(*groups: list[str], default: str) -> str:
    for group in groups:
        for item in group:
            text = str(item).strip()
            if text:
                return text
    return default


def _severity_from_risk(risk_level: str) -> str:
    if risk_level == "high":
        return "block"
    if risk_level == "medium":
        return "warning"
    return "info"


def _severity_from_quality_score(value: Any) -> str:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "warning"
    if score < 0.4:
        return "block"
    if score < 0.8:
        return "warning"
    return "info"


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _highest_severity(events: list[DailyAgentFeedbackEvent]) -> str:
    order = {"none": 0, "info": 1, "warning": 2, "block": 3}
    severity = "none"
    for event in events:
        if order.get(event.severity, 0) > order[severity]:
            severity = event.severity
    return severity


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
