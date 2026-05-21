from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RecallIntent = Literal[
    "topic_overview",
    "entity_history",
    "claim_check",
    "source_reliability",
    "decision_history",
    "preference_lookup",
    "general",
]


@dataclass(frozen=True)
class RecallPlan:
    query: str
    intent: RecallIntent = "general"
    topic: str | None = None
    entity_id: str | None = None
    claim_text: str | None = None
    source_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    include_evidence: bool = True
    include_claims: bool = True
    include_entities: bool = True
    include_events: bool = True
    include_decisions: bool = True
    include_preferences: bool = False
    include_conflicts: bool = True
    limit_per_layer: int = 8


class RecallPlanner:
    def plan(
        self,
        query: str,
        *,
        topic: str | None = None,
        entity_id: str | None = None,
        claim_text: str | None = None,
        source_id: str | None = None,
    ) -> RecallPlan:
        intent = self.infer_intent(
            query,
            entity_id=entity_id,
            claim_text=claim_text,
            source_id=source_id,
        )
        return RecallPlan(
            query=query,
            intent=intent,
            topic=topic,
            entity_id=entity_id,
            claim_text=claim_text,
            source_id=source_id,
            target_type=_target_type_for_intent(intent),
            target_id=entity_id or source_id or topic,
            include_preferences=intent == "preference_lookup",
        )

    def infer_intent(
        self,
        query: str,
        *,
        entity_id: str | None = None,
        claim_text: str | None = None,
        source_id: str | None = None,
    ) -> RecallIntent:
        if entity_id:
            return "entity_history"
        if claim_text:
            return "claim_check"
        if source_id:
            return "source_reliability"
        normalized = query.casefold()
        if any(token in normalized for token in ("history", "timeline", "past", "过去", "历史")):
            return "topic_overview"
        if any(token in normalized for token in ("reliable", "source", "来源", "source reliability")):
            return "source_reliability"
        if any(token in normalized for token in ("decision", "gate", "review")):
            return "decision_history"
        if any(token in normalized for token in ("preference", "偏好")):
            return "preference_lookup"
        return "general"


def _target_type_for_intent(intent: RecallIntent) -> str | None:
    if intent == "entity_history":
        return "entity"
    if intent == "source_reliability":
        return "source"
    if intent == "topic_overview":
        return "topic"
    return None


__all__ = ["RecallIntent", "RecallPlan", "RecallPlanner"]
