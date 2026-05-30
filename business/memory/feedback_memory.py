from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any, Literal

from business.memory.intelligence_builder import stable_id
from business.memory.intelligence_models import DecisionMemory, PreferenceMemory
from business.memory.models import BusinessMemoryHit


MISRANK_TAGS = {
    "weak_evidence_ranked_too_high",
    "star_spike_overweighted",
    "paper_without_evaluation_overranked",
    "community_noise_overranked",
}


def estimate_previous_misrank_penalty(hits: list[BusinessMemoryHit]) -> float:
    if not hits:
        return 0.0
    penalty = 0.0
    for hit in hits:
        tags = {tag.casefold() for tag in hit.tags}
        metadata_text = " ".join(str(value).casefold() for value in hit.metadata.values() if isinstance(value, str))
        if MISRANK_TAGS & tags:
            penalty += 0.3
        if any(tag in metadata_text for tag in MISRANK_TAGS):
            penalty += 0.2
    return _clamp(penalty)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


FeedbackType = Literal[
    "like",
    "dislike",
    "correction",
    "source_block",
    "source_boost",
    "topic_subscribe",
    "topic_mute",
    "ranking_override",
    "claim_correction",
]


@dataclass(frozen=True)
class FeedbackMemory:
    feedback_id: str
    feedback_type: FeedbackType
    target_type: str
    target_id: str
    user_id: str | None = None
    content: str | None = None
    weight: float = 1.0
    created_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "feedback_id": self.feedback_id,
            "feedback_type": self.feedback_type,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "user_id": self.user_id,
            "content": self.content,
            "weight": self.weight,
            "created_at": _dt(self.created_at),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class FeedbackIngestionResult:
    feedback_id: str
    preference_ids: list[str] = field(default_factory=list)
    decision_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "feedback_id": self.feedback_id,
            "preference_ids": list(self.preference_ids),
            "decision_ids": list(self.decision_ids),
            "metadata": dict(self.metadata),
        }


class FeedbackMemoryService:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def ingest_feedback(self, feedback: FeedbackMemory) -> FeedbackIngestionResult:
        preferences = self.feedback_to_preference(feedback)
        decisions = self.feedback_to_decision(feedback)
        if preferences:
            self.repository.save_preferences(preferences)
        if decisions:
            self.repository.save_decisions(decisions)
        return FeedbackIngestionResult(
            feedback_id=feedback.feedback_id,
            preference_ids=[preference.preference_id for preference in preferences],
            decision_ids=[decision.decision_id for decision in decisions],
            metadata={"feedback_type": feedback.feedback_type},
        )

    def feedback_to_preference(self, feedback: FeedbackMemory) -> list[PreferenceMemory]:
        if feedback.feedback_type in {"source_block", "source_boost"}:
            return [_preference(feedback, owner_type="source", preference_type=feedback.feedback_type)]
        if feedback.feedback_type in {"topic_subscribe", "topic_mute"}:
            return [_preference(feedback, owner_type="topic", preference_type=feedback.feedback_type)]
        if feedback.feedback_type == "ranking_override":
            return [_preference(feedback, owner_type="ranking", preference_type="ranking_override")]
        return []

    def feedback_to_decision(self, feedback: FeedbackMemory) -> list[DecisionMemory]:
        if feedback.feedback_type in {"like", "dislike", "correction", "claim_correction"}:
            decision = "pass" if feedback.feedback_type == "like" else "reject"
            if feedback.feedback_type in {"correction", "claim_correction"}:
                decision = "correction"
            return [
                DecisionMemory(
                    decision_id=stable_id("feedback-decision", feedback.feedback_id, prefix="decision"),
                    decision_type=f"feedback_{feedback.feedback_type}",
                    target_type=feedback.target_type,
                    target_id=feedback.target_id,
                    decision=decision,
                    run_id=str(feedback.metadata.get("run_id") or "feedback"),
                    reason=feedback.content,
                    agent_id=feedback.user_id,
                    created_at=feedback.created_at or datetime.now(UTC),
                    metadata=feedback.to_dict(),
                )
            ]
        return []


def _preference(feedback: FeedbackMemory, *, owner_type: str, preference_type: str) -> PreferenceMemory:
    return PreferenceMemory(
        preference_id=stable_id("feedback-preference", feedback.feedback_id, preference_type, prefix="preference"),
        owner_type=owner_type,
        owner_id=feedback.target_id,
        preference_type=preference_type,
        content=feedback.content or feedback.feedback_type,
        weight=feedback.weight,
        source="human_feedback",
        created_at=feedback.created_at or datetime.now(UTC),
        metadata=feedback.to_dict(),
    )


def _dt(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


__all__ = [
    "FeedbackIngestionResult",
    "FeedbackMemory",
    "FeedbackMemoryService",
    "FeedbackType",
    "estimate_previous_misrank_penalty",
]
