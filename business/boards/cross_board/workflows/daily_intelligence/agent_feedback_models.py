from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

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
    evidence_gaps: list[Any] = Field(default_factory=list)
    source_recollection_requests: list[Any] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _project_legacy_source_recollection_metadata(self) -> "DailyAgentFeedbackEvent":
        if not self.evidence_gaps:
            object.__setattr__(
                self,
                "evidence_gaps",
                _list_value(self.metadata.get("evidence_gaps")),
            )
        if not self.source_recollection_requests:
            object.__setattr__(
                self,
                "source_recollection_requests",
                _list_value(self.metadata.get("source_recollection_requests")),
            )
        if not self.missing_information:
            object.__setattr__(
                self,
                "missing_information",
                _string_items(_list_value(self.metadata.get("missing_information"))),
            )
        return self


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


def _list_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if value is None:
        return []
    return [value]


def _string_items(values: list[Any]) -> list[str]:
    return [text for value in values if (text := str(value).strip())]
