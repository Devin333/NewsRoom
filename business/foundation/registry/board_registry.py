from __future__ import annotations

from typing import Any

from pydantic import Field

from business.foundation.primitives import PrimitiveModel
from business.foundation.taxonomy import BoardType, SignalType


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
                board_type=BoardType.RESEARCH,
                name="Research",
                description="Research papers and emerging techniques.",
                signal_types=[SignalType.PAPER],
                default_time_window_hours=720,
                visible_sections=["research_papers", "technology_radar", "related_projects"],
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


__all__ = ["BoardDefinition", "BoardRegistry", "default_board_registry"]
