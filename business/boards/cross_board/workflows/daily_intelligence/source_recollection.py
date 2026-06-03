from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import Field

from business.foundation import PrimitiveModel
from business.boards.cross_board.workflows.daily_intelligence.agent_feedback_models import (
    SOURCE_RECOLLECT_TARGET,
    DailyAgentFeedbackEvent,
    DailyAgentFeedbackPolicyRecommendation,
    DailyAgentFeedbackSummary,
)


SOURCE_RECOLLECTION_PROFILE_SCHEMA_VERSION = (
    "business.cross_board.daily_source_recollection.profile.v1"
)


class DailySourceRecollectionProfile(PrimitiveModel):
    schema_version: str = SOURCE_RECOLLECTION_PROFILE_SCHEMA_VERSION
    profile_id: str
    target_id: str = SOURCE_RECOLLECT_TARGET
    status: str = "requested"
    reason: str
    source_recollect_round: int = 0
    max_source_recollect_rounds: int = 0
    queries: list[str] = Field(default_factory=list)
    evidence_gaps: list[Any] = Field(default_factory=list)
    source_recollection_requests: list[Any] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    source_feedback_ids: list[str] = Field(default_factory=list)
    recommendation_ids: list[str] = Field(default_factory=list)
    query_count: int = 0
    evidence_gap_count: int = 0
    source_recollection_request_count: int = 0
    missing_information_count: int = 0
    route: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DailySourceRecollectionService:
    def build_profile(
        self,
        *,
        events: list[DailyAgentFeedbackEvent],
        summary: DailyAgentFeedbackSummary,
        route: dict[str, Any],
        loop_state: dict[str, Any],
    ) -> DailySourceRecollectionProfile | None:
        if not _is_source_recollect_route(route):
            return None
        recollect_events = [
            event
            for event in events
            if event.requested_action == "source_recollect"
            and event.target_agent_id == SOURCE_RECOLLECT_TARGET
        ]
        recommendations = _source_recollect_recommendations(summary)
        if not recollect_events and not recommendations:
            return None
        evidence_gaps = _event_items(
            recollect_events,
            lambda event: event.evidence_gaps,
        )
        recollection_requests = _event_items(
            recollect_events,
            lambda event: event.source_recollection_requests,
        )
        missing_information = _string_items(
            _event_items(
                recollect_events,
                lambda event: event.missing_information,
            )
        )
        queries = _dedupe_text(
            [
                *_query_texts(recollection_requests),
                *_query_texts(evidence_gaps),
                *missing_information,
            ]
        )
        source_recollect_round = _source_recollect_round(route, loop_state)
        max_source_recollect_rounds = _max_source_recollect_rounds(route, loop_state)
        return DailySourceRecollectionProfile(
            profile_id=_profile_id(source_recollect_round),
            reason=_profile_reason(recommendations, recollect_events),
            source_recollect_round=source_recollect_round,
            max_source_recollect_rounds=max_source_recollect_rounds,
            queries=queries,
            evidence_gaps=evidence_gaps,
            source_recollection_requests=recollection_requests,
            missing_information=missing_information,
            source_feedback_ids=_dedupe_text(
                [feedback_id for event in recollect_events if (feedback_id := event.feedback_id)]
            ),
            recommendation_ids=_dedupe_text(
                [
                    recommendation.recommendation_id
                    for recommendation in recommendations
                    if recommendation.recommendation_id
                ]
            ),
            query_count=len(queries),
            evidence_gap_count=len(evidence_gaps),
            source_recollection_request_count=len(recollection_requests),
            missing_information_count=len(missing_information),
            route=dict(route),
        )


def _is_source_recollect_route(route: dict[str, Any]) -> bool:
    return (
        str(route.get("decision") or "").strip() == "source_recollect_required"
        and str(route.get("policy_target_id") or "").strip() == SOURCE_RECOLLECT_TARGET
    )


def _source_recollect_recommendations(
    summary: DailyAgentFeedbackSummary,
) -> list[DailyAgentFeedbackPolicyRecommendation]:
    return [
        recommendation
        for recommendation in summary.policy_recommendations
        if recommendation.recommended_action == "source_recollect"
        and recommendation.target_agent_id == SOURCE_RECOLLECT_TARGET
    ]


def _event_items(
    events: list[DailyAgentFeedbackEvent],
    value: Callable[[DailyAgentFeedbackEvent], list[Any]],
) -> list[Any]:
    items: list[Any] = []
    for event in events:
        items.extend(_list_value(value(event)))
    return items


def _query_texts(values: list[Any]) -> list[str]:
    texts: list[str] = []
    for value in values:
        if isinstance(value, dict):
            for key in ("query", "reason", "description", "title"):
                text = str(value.get(key) or "").strip()
                if text:
                    texts.append(text)
                    break
            continue
        text = str(value).strip()
        if text:
            texts.append(text)
    return texts


def _string_items(values: list[Any]) -> list[str]:
    return [text for value in values if (text := str(value).strip())]


def _source_recollect_round(route: dict[str, Any], loop_state: dict[str, Any]) -> int:
    return _int_value(
        route.get("source_recollect_round"),
        default=_int_value(loop_state.get("source_recollect_rounds"), default=0),
    )


def _max_source_recollect_rounds(route: dict[str, Any], loop_state: dict[str, Any]) -> int:
    return _int_value(
        route.get("max_source_recollect_rounds"),
        default=_int_value(loop_state.get("max_source_recollect_rounds"), default=0),
    )


def _profile_id(round_number: int) -> str:
    return f"daily-source-recollect-{round_number}"


def _profile_reason(
    recommendations: list[DailyAgentFeedbackPolicyRecommendation],
    events: list[DailyAgentFeedbackEvent],
) -> str:
    for recommendation in recommendations:
        reason = recommendation.reason.strip()
        if reason:
            return reason
    for event in events:
        reason = event.reason.strip()
        if reason:
            return reason
    return "agent feedback requested source recollection"


def _list_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if value is None:
        return []
    return [value]


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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


__all__ = [
    "DailySourceRecollectionProfile",
    "DailySourceRecollectionService",
    "SOURCE_RECOLLECTION_PROFILE_SCHEMA_VERSION",
]
