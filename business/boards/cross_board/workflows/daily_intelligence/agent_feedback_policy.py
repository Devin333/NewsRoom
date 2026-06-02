from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.agent_feedback_models import (
    DailyAgentFeedbackEvent,
    DailyAgentFeedbackPolicyRecommendation,
    SOURCE_RECOLLECT_TARGET,
)
from business.boards.cross_board.workflows.daily_intelligence.agents import WRITER_AGENT_ID


class DailyAgentFeedbackPolicyService:
    def recommend(
        self,
        events: list[DailyAgentFeedbackEvent],
    ) -> list[DailyAgentFeedbackPolicyRecommendation]:
        recommendations: list[DailyAgentFeedbackPolicyRecommendation] = []
        recommendations.extend(
            self._recommend_for_action(
                events,
                action="block",
                recommendation_id="daily-agent-feedback-policy-block",
                priority="block",
            )
        )
        recommendations.extend(
            self._recommend_for_action(
                events,
                action="human_review",
                recommendation_id="daily-agent-feedback-policy-human-review",
                priority="warning",
            )
        )
        recommendations.extend(
            self._recommend_for_action(
                events,
                action="source_recollect",
                recommendation_id="daily-agent-feedback-policy-source-recollect",
                priority="warning",
                target_agent_id=SOURCE_RECOLLECT_TARGET,
            )
        )
        recommendations.extend(
            self._recommend_for_action(
                events,
                action="rewrite",
                recommendation_id="daily-agent-feedback-policy-rewrite",
                priority="warning",
                target_agent_id=WRITER_AGENT_ID,
            )
        )
        return recommendations

    def _recommend_for_action(
        self,
        events: list[DailyAgentFeedbackEvent],
        *,
        action: str,
        recommendation_id: str,
        priority: str,
        target_agent_id: str | None = None,
    ) -> list[DailyAgentFeedbackPolicyRecommendation]:
        matched_events = [
            event
            for event in events
            if event.requested_action == action
            and (target_agent_id is None or event.target_agent_id == target_agent_id)
        ]
        if not matched_events:
            return []
        targets = _dedupe_text([event.target_agent_id for event in matched_events])
        recommendations = []
        for target in targets:
            target_events = [event for event in matched_events if event.target_agent_id == target]
            recommendations.append(
                DailyAgentFeedbackPolicyRecommendation(
                    recommendation_id=f"{recommendation_id}:{target}",
                    target_agent_id=target,
                    recommended_action=action,
                    priority=_highest_priority(priority, target_events),
                    reason=_first_reason(target_events),
                    source_feedback_ids=[event.feedback_id for event in target_events],
                    metadata={
                        "feedback_types": _dedupe_text([event.feedback_type for event in target_events]),
                        "source_agent_ids": _dedupe_text([event.source_agent_id for event in target_events]),
                    },
                )
            )
        return recommendations


def _first_reason(events: list[DailyAgentFeedbackEvent]) -> str:
    for event in events:
        reason = event.reason.strip()
        if reason:
            return reason
    return "agent feedback policy recommendation"


def _highest_priority(default: str, events: list[DailyAgentFeedbackEvent]) -> str:
    order = {"info": 0, "warning": 1, "block": 2}
    priority = default
    for event in events:
        severity = event.severity if event.severity in order else "info"
        if order[severity] > order.get(priority, 0):
            priority = severity
    return priority


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
