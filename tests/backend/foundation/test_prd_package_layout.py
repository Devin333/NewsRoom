from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module

from backend.foundation import (
    AnalysisContext,
    BoardContext,
    BoardDefinition,
    BoardType,
    BusinessId,
    BusinessLLMRequest,
    Confidence,
    ConfidenceMethod,
    ConfidencePolicy,
    RelationDefinition,
    RelationDirection,
    RelationType,
    RunContext,
    ScoreLevel,
    SignalType,
    SourceRef,
    SourceReliability,
    SourceType,
    TimeWindow,
)
from backend.foundation.taxonomy import ObjectType


def test_prd_directory_modules_import_independently() -> None:
    module_names = [
        "backend.foundation.primitives.ids",
        "backend.foundation.primitives.score",
        "backend.foundation.primitives.confidence",
        "backend.foundation.primitives.time_window",
        "backend.foundation.primitives.source_ref",
        "backend.foundation.models.signal",
        "backend.foundation.models.entity",
        "backend.foundation.models.topic",
        "backend.foundation.models.technology",
        "backend.foundation.models.claim",
        "backend.foundation.models.relation",
        "backend.foundation.models.insight",
        "backend.foundation.models.board",
        "backend.foundation.models.report",
        "backend.foundation.taxonomy",
        "backend.foundation.contracts.repositories",
        "backend.foundation.contracts.llm_ports",
        "backend.foundation.contracts.source_ports",
        "backend.foundation.contracts.graph_ports",
        "backend.foundation.context.run_context",
        "backend.foundation.context.board_context",
        "backend.foundation.context.analysis_context",
        "backend.foundation.policies.confidence_policy",
        "backend.foundation.policies.freshness_policy",
        "backend.foundation.policies.quality_policy",
        "backend.foundation.registry.board_registry",
        "backend.foundation.registry.taxonomy_registry",
        "backend.foundation.registry.relation_registry",
    ]

    imported = [import_module(name) for name in module_names]

    assert imported[0].BusinessId is BusinessId
    assert imported[5].Signal.__name__ == "Signal"
    imported_by_name = dict(zip(module_names, imported, strict=True))
    assert imported_by_name["backend.foundation.contracts.llm_ports"].BusinessLLMRequest is BusinessLLMRequest


def test_prd_primitives_support_stable_ids_source_refs_and_confidence_metadata() -> None:
    first_id = BusinessId.stable("technology", "Agent Memory")
    second_id = BusinessId.stable("technology", "agent memory")
    source = SourceRef(
        source_name="OpenAI Blog",
        source_type=SourceType.OFFICIAL_BLOG,
        url="https://openai.com/blog",
        reliability=SourceReliability.OFFICIAL,
    )
    confidence = Confidence(
        value=0.91,
        reason="official source and exact title match",
        evidence_count=2,
        method=ConfidenceMethod.EXACT_MATCH,
    )

    assert first_id == second_id
    assert first_id.namespace == "technology"
    assert first_id.value.startswith("technology_")
    assert source.source_id and source.source_id.startswith("src_")
    assert source.source_url == "https://openai.com/blog"
    assert source.collected_at.tzinfo == UTC
    assert confidence.level == ScoreLevel.VERY_HIGH
    assert confidence.to_dict()["level"] == "very_high"
    assert confidence.method == ConfidenceMethod.EXACT_MATCH


def test_prd_context_models_compose_run_board_and_analysis_context() -> None:
    window = TimeWindow(
        start_at=datetime(2026, 5, 19, tzinfo=UTC),
        end_at=datetime(2026, 5, 20, tzinfo=UTC),
        label="daily",
    )
    run_context = RunContext(
        run_id="run-1",
        run_type="daily",
        profile="live-offline",
        time_window=window,
        created_at=datetime(2026, 5, 20),
    )
    board_context = BoardContext(
        board_type=BoardType.RESEARCH,
        source_limit=5,
        time_window=TimeWindow(start_at=window.start_at - timedelta(days=6), end_at=window.end_at),
    )

    context = AnalysisContext(run_context=run_context, board_context=board_context, taxonomy_version="v1")

    assert run_context.created_at.tzinfo == UTC
    assert context.board_type == BoardType.RESEARCH
    assert context.time_window == board_context.time_window
    assert context.enable_llm is True


def test_prd_registry_and_policy_fields_cover_contract_thresholds() -> None:
    board = BoardDefinition(
        board_type=BoardType.PROJECT_RADAR,
        name="Project Radar",
        description="High quality AI projects.",
        signal_types=[SignalType.GITHUB_PROJECT],
        default_time_window_hours=336,
    )
    relation = RelationDefinition(
        relation_type=RelationType.IMPLEMENTS,
        source_object_types=[ObjectType.PROJECT],
        target_object_types=[ObjectType.TECHNOLOGY],
        directed=True,
        min_confidence=0.65,
    )
    policy = ConfidencePolicy()

    assert board.enabled is True
    assert board.signal_types == [SignalType.GITHUB_PROJECT]
    assert relation.direction == RelationDirection.DIRECTED
    assert relation.directed is True
    assert policy.display_level(0.49) == "hidden"
    assert policy.display_level(0.5) == "weak_related"
    assert policy.display_level(0.7) == "related"
    assert policy.display_level(0.9) == "strong_related"


def test_business_llm_request_uses_schema_alias_without_concrete_client_dependency() -> None:
    request = BusinessLLMRequest(prompt="Extract claims", schema={"type": "object"})

    assert request.output_schema == {"type": "object"}
    assert request.to_dict()["output_schema"] == {"type": "object"}
