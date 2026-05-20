from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from business.foundation.primitives import PrimitiveModel, normalize_key
from business.foundation.taxonomy import BoardType, ObjectType, RelationDirection, RelationType, SignalType, TaxonomyType


class BoardDefinition(PrimitiveModel):
    board_type: BoardType
    name: str
    description: str | None = None
    signal_types: list[SignalType] = Field(default_factory=list)
    default_sort: str = "score"
    default_time_window_hours: int = 168
    enabled: bool = True
    visible_sections: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaxonomyDefinition(PrimitiveModel):
    taxonomy_type: TaxonomyType
    terms: list[str] = Field(default_factory=list)
    aliases: dict[str, list[str]] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RelationDefinition(PrimitiveModel):
    relation_type: RelationType
    source_types: list[str] = Field(default_factory=list)
    target_types: list[str] = Field(default_factory=list)
    source_object_types: list[ObjectType] = Field(default_factory=list)
    target_object_types: list[ObjectType] = Field(default_factory=list)
    direction: RelationDirection = RelationDirection.DIRECTED
    directed: bool | None = None
    min_confidence: float = 0.5
    requires_evidence: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sync_direction_fields(self) -> "RelationDefinition":
        if self.directed is None:
            object.__setattr__(self, "directed", self.direction == RelationDirection.DIRECTED)
        else:
            object.__setattr__(
                self,
                "direction",
                RelationDirection.DIRECTED if self.directed else RelationDirection.UNDIRECTED,
            )
        return self


class BoardRegistry:
    def __init__(self, definitions: list[BoardDefinition] | None = None) -> None:
        self._definitions: dict[BoardType, BoardDefinition] = {}
        for definition in definitions or []:
            self.register(definition)

    def register(self, definition: BoardDefinition) -> None:
        self._definitions[definition.board_type] = definition

    def get(self, board_type: BoardType) -> BoardDefinition:
        return self._definitions[board_type]

    def list(self) -> list[BoardDefinition]:
        return [self._definitions[key] for key in sorted(self._definitions, key=lambda item: item.value)]


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


class RelationRegistry:
    def __init__(self, definitions: list[RelationDefinition] | None = None) -> None:
        self._definitions: dict[RelationType, RelationDefinition] = {}
        for definition in definitions or []:
            self.register(definition)

    def register(self, definition: RelationDefinition) -> None:
        self._definitions[definition.relation_type] = definition

    def get(self, relation_type: RelationType) -> RelationDefinition:
        return self._definitions[relation_type]

    def list(self) -> list[RelationDefinition]:
        return [self._definitions[key] for key in sorted(self._definitions, key=lambda item: item.value)]


def default_board_registry() -> BoardRegistry:
    return BoardRegistry(
        [
            BoardDefinition(
                board_type=BoardType.AI_NEWS,
                name="AI News",
                description="Fresh AI news and adoption signals.",
                signal_types=[SignalType.AI_NEWS],
                default_time_window_hours=72,
                visible_sections=["top_signals", "technology_radar", "cross_board_insights"],
            ),
            BoardDefinition(
                board_type=BoardType.PROJECT_RADAR,
                name="Project Radar",
                description="High quality GitHub AI projects.",
                signal_types=[SignalType.GITHUB_PROJECT],
                default_time_window_hours=336,
                visible_sections=["top_projects", "technology_radar", "related_papers"],
            ),
            BoardDefinition(
                board_type=BoardType.PAPER_RADAR,
                name="Paper Radar",
                description="Papers and emerging techniques.",
                signal_types=[SignalType.PAPER],
                default_time_window_hours=720,
                visible_sections=["top_papers", "technology_radar", "related_projects"],
            ),
            BoardDefinition(
                board_type=BoardType.COMMUNITY_PULSE,
                name="Community Pulse",
                description="Community discussion and sentiment.",
                signal_types=[SignalType.COMMUNITY_DISCUSSION],
                default_time_window_hours=168,
                visible_sections=["top_threads", "community_trends", "cross_board_insights"],
            ),
            BoardDefinition(
                board_type=BoardType.CROSS_BOARD,
                name="Cross Board",
                description="Cross-board intelligence and daily digest.",
                signal_types=[
                    SignalType.AI_NEWS,
                    SignalType.GITHUB_PROJECT,
                    SignalType.PAPER,
                    SignalType.COMMUNITY_DISCUSSION,
                ],
                default_time_window_hours=24,
                visible_sections=["cross_board_insights", "technology_journeys", "daily_report"],
            ),
        ]
    )


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


def default_relation_registry() -> RelationRegistry:
    return RelationRegistry(
        [
            RelationDefinition(relation_type=RelationType.MENTIONS, source_types=["signal", "claim"], target_types=["entity", "topic", "technology"], min_confidence=0.5),
            RelationDefinition(relation_type=RelationType.PROPOSES, source_types=["paper", "claim"], target_types=["technology"], min_confidence=0.6),
            RelationDefinition(relation_type=RelationType.IMPLEMENTS, source_types=["project", "claim"], target_types=["technology", "paper"], min_confidence=0.65),
            RelationDefinition(relation_type=RelationType.DISCUSSES, source_types=["community_thread", "claim"], target_types=["project", "paper", "technology", "topic"], min_confidence=0.55),
            RelationDefinition(relation_type=RelationType.COMPARES, source_types=["claim", "community_thread", "paper"], target_types=["entity", "technology"], direction=RelationDirection.UNDIRECTED, min_confidence=0.6),
            RelationDefinition(relation_type=RelationType.ADOPTS, source_types=["signal", "claim"], target_types=["technology"], min_confidence=0.65),
            RelationDefinition(relation_type=RelationType.SUPPORTS, source_types=["signal", "claim"], target_types=["claim", "relation"], min_confidence=0.55),
            RelationDefinition(relation_type=RelationType.CRITICIZES, source_types=["community_thread", "claim"], target_types=["entity", "technology"], min_confidence=0.55),
            RelationDefinition(relation_type=RelationType.EXTENDS, source_types=["paper", "technology"], target_types=["technology"], min_confidence=0.6),
            RelationDefinition(relation_type=RelationType.SIMILAR_TO, source_types=["claim", "community_thread", "paper"], target_types=["technology"], direction=RelationDirection.UNDIRECTED, min_confidence=0.55),
            RelationDefinition(relation_type=RelationType.SAME_TOPIC, source_types=["signal"], target_types=["topic"], min_confidence=0.5),
        ]
    )
