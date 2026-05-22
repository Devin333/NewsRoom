from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from business.memory.historical_context import HistoricalContext, HistoricalContextRequest, HistoricalContextService


@dataclass(frozen=True)
class HistorianAgentInput:
    topic: str | None = None
    entity_id: str | None = None
    event_id: str | None = None
    claim_text: str | None = None
    limit: int = 10


@dataclass(frozen=True)
class HistorianAgentOutput:
    historical_context: HistoricalContext
    summary: str
    is_new_event: bool
    repeated_claims: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    timeline_summary: str | None = None
    recommendations: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "historical_context": self.historical_context.to_dict(),
            "summary": self.summary,
            "is_new_event": self.is_new_event,
            "repeated_claims": list(self.repeated_claims),
            "contradictions": list(self.contradictions),
            "timeline_summary": self.timeline_summary,
            "recommendations": list(self.recommendations),
            "metadata": dict(self.metadata),
        }


class HistorianAgent:
    def __init__(self, context_service: HistoricalContextService) -> None:
        self.context_service = context_service

    def analyze(self, request: HistorianAgentInput) -> HistorianAgentOutput:
        context = self.context_service.build_context(
            HistoricalContextRequest(
                topic=request.topic,
                entity_id=request.entity_id,
                event_id=request.event_id,
                claim_text=request.claim_text,
                limit=request.limit,
            )
        )
        return self._summarize(context)

    def _summarize(self, context: HistoricalContext) -> HistorianAgentOutput:
        repeated = [claim.text for claim in context.repeated_claims]
        contradictions = [claim.text for claim in context.contradictions]
        is_new_event = not repeated and not contradictions and not context.recent_events
        summary = context.timeline_summary or context.to_prompt_context(limit=5) or "No historical context found."
        recommendations = []
        if contradictions:
            recommendations.append("Run quality gate before publishing.")
        if repeated:
            recommendations.append("Treat this as follow-up, not a new event.")
        if context.unresolved_questions:
            recommendations.extend(context.unresolved_questions)
        return HistorianAgentOutput(
            historical_context=context,
            summary=summary,
            is_new_event=is_new_event,
            repeated_claims=repeated,
            contradictions=contradictions,
            timeline_summary=context.timeline_summary,
            recommendations=recommendations,
            metadata={"context_empty": context.is_empty()},
        )


__all__ = ["HistorianAgent", "HistorianAgentInput", "HistorianAgentOutput"]
