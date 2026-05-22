from __future__ import annotations

from business.foundation import AnalysisContext, BoardType
from business.layers.analysis.trend_analyzer import TrendAnalyzer
from business.layers.extraction import ExtractionPipeline
from business.layers.extraction.entity_extractor import EntityExtractor
from business.layers.extraction.technology_extractor import TechnologyExtractor
from business.layers.relation.implement_linker import ImplementLinker
from business.layers.relation import RelationPipeline
from business.layers.relation.relation_validator import RelationValidator
from business.layers.signal import SignalPipeline


def test_extraction_helpers_are_independent_from_pipeline_private_methods() -> None:
    signal = SignalPipeline().coerce_signals([_sample_raw_item("github_project")], board_type=BoardType.PROJECT_RADAR).signals[0]
    context = AnalysisContext(board_type=BoardType.PROJECT_RADAR)

    entities = EntityExtractor().extract(signal, context)
    technologies = TechnologyExtractor().extract(signal, context)

    assert entities[0].metadata["extraction_method"] == "github_repo_rule"
    assert technologies
    assert technologies[0].confidence.reason


def test_relation_and_analysis_helpers_are_independent_from_pipeline_private_methods() -> None:
    signal = SignalPipeline().coerce_signals([_sample_raw_item("github_project")], board_type=BoardType.PROJECT_RADAR).signals[0]
    context = AnalysisContext(board_type=BoardType.PROJECT_RADAR)
    extraction = ExtractionPipeline().extract(signal, context)

    candidates = ImplementLinker().link([signal], [extraction])
    assert candidates
    assert RelationValidator().validate(candidates[0]) is None

    relations = RelationPipeline().run([signal], [extraction]).relations
    trends = TrendAnalyzer().analyze([signal], [extraction], relations, context)
    assert trends
    assert trends[0].score.factors


def _sample_raw_item(signal_type: str) -> dict[str, object]:
    return {
        "source_item_id": f"{signal_type}-item",
        "source_id": f"{signal_type}-source",
        "source_name": "Source",
        "source_type": "github",
        "title": "example/agent-memory implements Agent Memory",
        "summary": "example/agent-memory implements agent memory for workflow orchestration.",
        "content": "example/agent-memory implements agent memory for workflow orchestration.",
        "url": "https://github.com/example/agent-memory",
        "language": "en",
        "authors": ["Alice"],
        "tags": ["ai", "agent memory"],
        "fetched_at": "2026-05-19T01:00:00Z",
        "published_at": "2026-05-19T00:00:00Z",
        "metadata": {"source_reliability": "high"},
    }
