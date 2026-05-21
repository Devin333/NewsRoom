from __future__ import annotations

from pydantic import Field

from business.foundation import BoardCard, ObjectRef, PrimitiveModel, Score


class SentimentSummary(PrimitiveModel):
    overall: str = "neutral"
    positive_ratio: float = 0.0
    negative_ratio: float = 0.0
    neutral_ratio: float = 1.0
    key_positive_points: list[str] = Field(default_factory=list)
    key_negative_points: list[str] = Field(default_factory=list)


class CommunityPulseItem(PrimitiveModel):
    card: BoardCard
    platform: str
    thread_url: str
    heat_score: Score
    sentiment: SentimentSummary = Field(default_factory=SentimentSummary)
    discussed_objects: list[ObjectRef] = Field(default_factory=list)
    related_projects: list[ObjectRef] = Field(default_factory=list)
    related_papers: list[ObjectRef] = Field(default_factory=list)
    related_technologies: list[ObjectRef] = Field(default_factory=list)
    viewpoint_summary: str = ""
