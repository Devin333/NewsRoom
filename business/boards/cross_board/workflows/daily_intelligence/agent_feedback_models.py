from __future__ import annotations

from typing import Any

from pydantic import Field

from business.foundation import PrimitiveModel


HUMAN_REVIEW_TARGET = "daily.human_review"
PUBLICATION_GATE_TARGET = "daily.publication_gate"
SOURCE_RECOLLECT_TARGET = "daily.source_recollect"


class DailyAgentFeedbackEvent(PrimitiveModel):
    feedback_id: str
    source_agent_id: str
    target_agent_id: str
    feedback_type: str
    severity: str
    requested_action: str
    reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DailyAgentFeedbackPolicyRecommendation(PrimitiveModel):
    recommendation_id: str
    target_agent_id: str
    recommended_action: str
    priority: str
    reason: str
    source_feedback_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DailyAgentFeedbackSummary(PrimitiveModel):
    event_count: int
    rewrite_request_count: int = 0
    source_recollect_request_count: int = 0
    human_review_request_count: int = 0
    block_request_count: int = 0
    highest_severity: str = "none"
    target_agent_ids: list[str] = Field(default_factory=list)
    policy_recommendations: list[DailyAgentFeedbackPolicyRecommendation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
