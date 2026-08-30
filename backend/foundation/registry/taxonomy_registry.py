from __future__ import annotations

from typing import Any

from pydantic import Field

from backend.foundation.primitives import PrimitiveModel, normalize_key
from backend.foundation.taxonomy import BoardType, TaxonomyType


class TaxonomyDefinition(PrimitiveModel):
    taxonomy_type: TaxonomyType
    terms: list[str] = Field(default_factory=list)
    aliases: dict[str, list[str]] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaxonomyRegistry:
    def __init__(self, definitions: list[TaxonomyDefinition] | None = None) -> None:
        self._definitions: dict[TaxonomyType, TaxonomyDefinition] = {}
        for definition in definitions or []:
            self.register(definition)

    def register(self, definition: TaxonomyDefinition) -> None:
        self._definitions[definition.taxonomy_type] = definition

    def get(self, taxonomy_type: TaxonomyType) -> TaxonomyDefinition:
        return self._definitions[taxonomy_type]

    def list(self) -> list[TaxonomyDefinition]:
        return [self._definitions[key] for key in sorted(self._definitions, key=lambda item: item.value)]

    def find_term(self, taxonomy_type: TaxonomyType, value: str) -> str | None:
        definition = self._definitions.get(taxonomy_type)
        if definition is None:
            return None
        normalized = normalize_key(value)
        if normalized in {normalize_key(term) for term in definition.terms}:
            return normalized
        for term, aliases in definition.aliases.items():
            normalized_aliases = {normalize_key(alias) for alias in aliases}
            if normalized in normalized_aliases:
                return normalize_key(term)
        return None


def default_taxonomy_registry() -> TaxonomyRegistry:
    return TaxonomyRegistry(
        [
            TaxonomyDefinition(
                taxonomy_type=TaxonomyType.TECHNOLOGY,
                terms=[
                    "agent",
                    "rag",
                    "memory",
                    "planning",
                    "tool_use",
                    "workflow",
                    "model_serving",
                    "evaluation",
                    "fine_tuning",
                    "safety",
                    "alignment",
                ],
                aliases={
                    "agent": ["ai agent", "agent memory", "autonomous agent", "llm agent"],
                    "rag": ["retrieval augmented generation", "retrieval-augmented generation", "graphrag"],
                    "memory": ["long-term memory", "working memory", "agent memory"],
                    "planning": ["task planning", "reasoning planning"],
                    "tool_use": ["tool use", "function calling", "tool calling"],
                    "workflow": ["workflow orchestration", "agent workflow"],
                    "model_serving": ["inference serving", "model serving", "llm serving"],
                    "evaluation": ["benchmark", "eval", "evaluation"],
                    "fine_tuning": ["finetuning", "fine-tuning"],
                },
            ),
            TaxonomyDefinition(
                taxonomy_type=TaxonomyType.TOPIC,
                terms=[
                    "ai agent",
                    "rag",
                    "llmops",
                    "multimodal",
                    "ai coding",
                    "evaluation",
                    "memory",
                    "planning",
                    "tool use",
                    "workflow",
                ],
                aliases={
                    "ai agent": ["agents", "agentic", "autonomous agent"],
                    "ai coding": ["code assistant", "coding agent"],
                    "memory": ["long-term memory", "agent memory"],
                    "tool use": ["function calling", "tool calling"],
                },
            ),
            TaxonomyDefinition(
                taxonomy_type=TaxonomyType.BOARD,
                terms=[board.value for board in BoardType],
            ),
            TaxonomyDefinition(
                taxonomy_type=TaxonomyType.IMPACT_AREA,
                terms=["research", "engineering", "product", "ecosystem", "business", "policy", "community"],
            ),
        ]
    )


__all__ = ["TaxonomyDefinition", "TaxonomyRegistry", "default_taxonomy_registry"]
