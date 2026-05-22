from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from business.agents.historian_agent import HistorianAgent, HistorianAgentOutput


@dataclass(frozen=True)
class HistorianContextRequest:
    topic: str | None = None
    entity_id: str | None = None
    claim_text: str | None = None
    limit: int = 10


@dataclass(frozen=True)
class HistorianContextResult:
    output: HistorianAgentOutput
    prompt_context: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output.to_dict(),
            "prompt_context": self.prompt_context,
            "metadata": dict(self.metadata),
        }


class HistorianContextAdapter:
    def __init__(self, historian_agent: HistorianAgent) -> None:
        self.historian_agent = historian_agent

    def build_context(self, request: HistorianContextRequest) -> HistorianContextResult:
        from business.agents.historian_agent import HistorianAgentInput

        output = self.historian_agent.analyze(
            HistorianAgentInput(
                topic=request.topic,
                entity_id=request.entity_id,
                claim_text=request.claim_text,
                limit=request.limit,
            )
        )
        prompt = self._to_prompt_context(output)
        return HistorianContextResult(
            output=output,
            prompt_context=prompt,
            metadata={
                "is_new_event": output.is_new_event,
                "repeated_claim_count": len(output.repeated_claims),
                "contradiction_count": len(output.contradictions),
            },
        )

    def _to_prompt_context(self, output: HistorianAgentOutput) -> str:
        parts: list[str] = ["Historical analysis:", output.summary]
        if output.repeated_claims:
            parts.append("Repeated claims:")
            parts.extend(f"- {item}" for item in output.repeated_claims)
        if output.contradictions:
            parts.append("Contradictions:")
            parts.extend(f"- {item}" for item in output.contradictions)
        if output.recommendations:
            parts.append("Historian recommendations:")
            parts.extend(f"- {item}" for item in output.recommendations)
        return "\n".join(parts)


__all__ = ["HistorianContextAdapter", "HistorianContextRequest", "HistorianContextResult"]
