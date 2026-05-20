from __future__ import annotations

from datetime import UTC, datetime

import pytest

from business.foundation import (
    BoardType,
    ConfidencePolicy,
    FreshnessPolicy,
    QualityPolicy,
    RelationDirection,
    RelationType,
    TaxonomyType,
)
from business.foundation.context import AnalysisContext, default_time_window
from business.foundation.registry import (
    default_board_registry,
    default_relation_registry,
    default_taxonomy_registry,
)


def test_default_board_registry_lists_all_frontend_boards() -> None:
    registry = default_board_registry()

    boards = {definition.board_type for definition in registry.list()}

    assert boards == {
        BoardType.AI_NEWS,
        BoardType.PROJECT_RADAR,
        BoardType.PAPER_RADAR,
        BoardType.COMMUNITY_PULSE,
        BoardType.CROSS_BOARD,
    }
    assert registry.get(BoardType.PROJECT_RADAR).signal_types == ["github_project"]


def test_taxonomy_registry_resolves_terms_and_aliases() -> None:
    registry = default_taxonomy_registry()

    assert registry.find_term(TaxonomyType.TECHNOLOGY, "Agent Memory") == "agent"
    assert registry.find_term(TaxonomyType.TECHNOLOGY, "retrieval-augmented generation") == "rag"
    assert registry.find_term(TaxonomyType.TOPIC, "coding agent") == "ai_coding"
    assert registry.find_term(TaxonomyType.TOPIC, "not-a-topic") is None


def test_relation_registry_defines_direction_and_thresholds() -> None:
    registry = default_relation_registry()

    implements = registry.get(RelationType.IMPLEMENTS)
    compares = registry.get(RelationType.COMPARES)

    assert implements.direction == RelationDirection.DIRECTED
    assert implements.requires_evidence is True
    assert implements.min_confidence >= 0.5
    assert compares.direction == RelationDirection.UNDIRECTED


def test_foundation_policies_are_independent_config_objects() -> None:
    confidence = ConfidencePolicy()
    quality = QualityPolicy()
    freshness = FreshnessPolicy()

    assert confidence.minimum_relation_confidence == 0.5
    assert quality.minimum_evidence_relations == 1
    assert freshness.freshness_window_days == 7


def test_analysis_context_normalizes_time_windows_and_specializes_board() -> None:
    reference_time = datetime(2026, 5, 20, 12, 0, 0)
    window = default_time_window(days=14, reference_time=reference_time)
    context = AnalysisContext(time_window=window, metadata={"topic": "AI agents"})

    board_context = context.for_board(BoardType.PAPER_RADAR)

    assert window.start.tzinfo == UTC
    assert window.end.tzinfo == UTC
    assert window.label == "last_14_days"
    assert board_context.board_type == BoardType.PAPER_RADAR
    assert board_context.metadata == {"topic": "AI agents"}
    assert context.board_type is None


def test_time_window_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError):
        default_time_window(days=-1, reference_time=datetime(2026, 5, 20, tzinfo=UTC))
