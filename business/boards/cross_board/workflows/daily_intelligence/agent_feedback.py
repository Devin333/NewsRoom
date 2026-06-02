from __future__ import annotations

from typing import Any

from pydantic import Field

from framework.workflow import StepScopedDataBufferView
from business.foundation import PrimitiveModel
from business.boards.cross_board.workflows.daily_intelligence.agents import (
    EDITOR_AGENT_ID,
    VERIFIER_AGENT_ID,
    WRITER_AGENT_ID,
)
from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    with_namespaced_aliases,
)


HUMAN_REVIEW_TARGET = "daily.human_review"
PUBLICATION_GATE_TARGET = "daily.publication_gate"


class DailyAgentFeedbackEvent(PrimitiveModel):
    feedback_id: str
    source_agent_id: str
    target_agent_id: str
    feedback_type: str
    severity: str
    requested_action: str
    reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DailyAgentFeedbackSummary(PrimitiveModel):
    event_count: int
    rewrite_request_count: int = 0
    human_review_request_count: int = 0
    block_request_count: int = 0
    highest_severity: str = "none"
    target_agent_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def collect_agent_feedback(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    events = DailyAgentFeedbackCollector().collect(
        verification_result=_dict_value(buffer.read("verification_result")),
        citation_check_result=_dict_value(buffer.read("citation_check_result")),
        support_matrix=_dict_value(buffer.read("support_matrix")),
        editor_review=_dict_value(buffer.read("editor_review")),
    )
    return with_namespaced_aliases({
        "agent_feedback_events": events,
        "agent_feedback_summary": summarize_agent_feedback(events),
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
    return DailyAgentFeedbackSummary(
        event_count=len(events),
        rewrite_request_count=sum(1 for event in events if event.requested_action == "rewrite"),
        human_review_request_count=sum(1 for event in events if event.requested_action == "human_review"),
        block_request_count=sum(1 for event in events if event.requested_action == "block"),
        highest_severity=_highest_severity(events),
        target_agent_ids=target_agent_ids,
        metadata={
            "feedback_types": _dedupe_text([event.feedback_type for event in events]),
        },
    )


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
