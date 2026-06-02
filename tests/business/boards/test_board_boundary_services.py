from __future__ import annotations

from business.boards.ai_news.board_service import AINewsBoardService
from business.boards.productized.models import ProductizedRunState
from business.boards.services import (
    BoardRunReferenceService,
    BoardRunResultBuilder,
    BoardSignalSelectionService,
)
from business.evaluation.fixtures import sample_signal
from business.foundation import BoardType


def test_board_service_base_exposes_decomposed_boundary_services() -> None:
    service = AINewsBoardService()

    assert isinstance(service.selection_service, BoardSignalSelectionService)
    assert isinstance(service.reference_service, BoardRunReferenceService)
    assert isinstance(service.result_builder, BoardRunResultBuilder)


def test_board_run_result_uses_reference_and_pipeline_snapshots() -> None:
    service = AINewsBoardService()

    result = service.build_board_run_result([sample_signal("ai_news")])

    assert result.artifact_refs
    assert result.evidence_refs
    assert result.metadata["pipeline_snapshot"]["processed_relations"] == result.metadata["processed_relations"]


def test_productized_run_state_is_formal_intermediate_model() -> None:
    state = ProductizedRunState(
        board_type=BoardType.AI_NEWS,
        run_id="run-1",
        topic="Agent Memory",
        skill_traces=[{"skill": "source-reliability"}],
        evidence_items=[{"source_id": "src-1"}],
    )

    metadata = state.runtime_metadata()

    assert metadata["productized_run_state"]["schema_version"] == "business.board.productized.run_state.v1"
    assert metadata["skill_trace_metadata"] == [{"skill": "source-reliability"}]
    assert metadata["evidence_items"] == [{"source_id": "src-1"}]
