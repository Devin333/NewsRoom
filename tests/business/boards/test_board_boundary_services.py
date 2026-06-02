from __future__ import annotations

from business.boards.ai_news.board_service import AINewsBoardService
from business.boards.productized import (
    ProductizedBoardOutputBundleBuilder,
    ProductizedBoardOutputService,
    ProductizedReportWritingService,
)
from business.boards.productized.models import ProductizedBoardOutputBundle, ProductizedRunState
from business.boards.services import (
    BoardRunMetadataBuilder,
    BoardRunMetadataPayload,
    BoardPipelineRunner,
    BoardReportExtractionService,
    BoardRunReferenceService,
    BoardRunReferences,
    BoardRunResultBuilder,
    BoardSignalSelectionService,
)
from business.evaluation.fixtures import sample_signal
from business.foundation import BoardType
from business.foundation.skills import BusinessSkillResult, BusinessSkillRuntime
from business.layers.output import BoardOutput, BoardOutputStats


def test_board_service_base_exposes_decomposed_boundary_services() -> None:
    service = AINewsBoardService()

    assert isinstance(service.selection_service, BoardSignalSelectionService)
    assert isinstance(service.pipeline_runner, BoardPipelineRunner)
    assert isinstance(service.reference_service, BoardRunReferenceService)
    assert isinstance(service.report_service, BoardReportExtractionService)
    assert isinstance(service.result_builder, BoardRunResultBuilder)
    assert isinstance(service.result_builder.metadata_builder, BoardRunMetadataBuilder)
    assert service.result_builder.report_service is service.report_service


def test_board_run_result_uses_reference_and_pipeline_snapshots() -> None:
    service = AINewsBoardService()

    result = service.build_board_run_result([sample_signal("ai_news")])

    assert result.artifact_refs
    assert result.evidence_refs
    assert result.metadata["pipeline_snapshot"]["processed_relations"] == result.metadata["processed_relations"]


def test_board_run_metadata_builder_centralizes_legacy_metadata_fields() -> None:
    class StubOutput:
        def to_dict(self) -> dict[str, object]:
            return {"metadata": {"board_type": "ai_news"}}

    class StubRef:
        def __init__(self, ref_id: str) -> None:
            self.ref_id = ref_id

        def to_dict(self) -> dict[str, object]:
            return {"ref_id": self.ref_id}

    payload = BoardRunMetadataBuilder().build(
        output=StubOutput(),
        refs=BoardRunReferences(
            trace_ref=object(),
            manifest_ref=object(),
            artifact_refs=[StubRef("artifact-1")],
            evidence_refs=[StubRef("evidence-1")],
            memory_refs=[StubRef("memory-1")],
        ),
        pipeline_snapshot={
            "processed_relations": [{"relation_id": "rel-1"}],
            "rejected_relations": [],
            "analysis": {"summary": "analysis"},
        },
    )

    metadata = payload.to_result_metadata()

    assert isinstance(payload, BoardRunMetadataPayload)
    assert payload.schema_version == "business.board.run.metadata.v1"
    assert metadata["pipeline_snapshot"] == payload.pipeline_snapshot
    assert metadata["processed_relations"] == [{"relation_id": "rel-1"}]
    assert metadata["analysis"] == {"summary": "analysis"}


def test_board_report_extraction_service_centralizes_legacy_report_metadata() -> None:
    output = BoardOutput(
        board_type=BoardType.AI_NEWS,
        stats=BoardOutputStats(
            signal_count=0,
            card_count=0,
            detail_page_count=0,
            insight_count=0,
            relation_count=0,
            radar_item_count=0,
        ),
        metadata={
            "report": {
                "report_id": "report-1",
                "report_type": "board",
                "board_type": BoardType.AI_NEWS.value,
                "board_name": "AI News",
                "title": "AI News Report",
                "summary": "Summary",
                "sections": [
                    {
                        "title": "Highlights",
                        "section_type": "summary",
                        "level": "computed",
                    }
                ],
            }
        },
    )

    report = BoardReportExtractionService().require_report(output)

    assert report.report_id == "report-1"
    assert report.board_type == BoardType.AI_NEWS


def test_pipeline_runner_preserves_annotation_and_board_output_postprocess_hook() -> None:
    service = AINewsBoardService()

    output = service.build_board_output([sample_signal("ai_news")])

    assert output.metadata["board_type"] == BoardType.AI_NEWS.value
    assert output.metadata["report"]["board_type"] == BoardType.AI_NEWS.value
    assert output.cards
    assert output.cards[0].metadata["board_focus"] == "product_adoption_news"


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

    board_output_metadata = state.board_output_metadata()
    assert board_output_metadata["skill_trace_metadata"] == [{"skill": "source-reliability"}]
    assert "evidence_items" not in board_output_metadata


def test_productized_board_output_bundle_keeps_step_outputs_explicit() -> None:
    state = ProductizedRunState(board_type=BoardType.AI_NEWS, run_id="run-1")
    run_result = object()
    bundle = ProductizedBoardOutputBundle(
        board_run_result=run_result,
        board_output={"metadata": {}},
        cards=[{"card_id": "card-1"}],
        detail_pages=[],
        insights=[],
        summary_md="# Summary\n",
        skill_traces=[{"skill": "report-writing"}],
        run_state=state,
    )

    outputs = bundle.to_step_outputs()

    assert outputs["board_run_result"] is run_result
    assert outputs["productized_run"] is state
    assert outputs["skill_traces"] == [{"skill": "report-writing"}]


def test_productized_board_output_service_exposes_decomposed_services() -> None:
    service = ProductizedBoardOutputService(
        board_service=AINewsBoardService(),
        skill_runtime=BusinessSkillRuntime(),
    )

    assert isinstance(service.report_writing_service, ProductizedReportWritingService)
    assert isinstance(service.bundle_builder, ProductizedBoardOutputBundleBuilder)


def test_productized_board_output_bundle_builder_centralizes_metadata_merge() -> None:
    board_service = AINewsBoardService()
    result = board_service.build_board_run_result([sample_signal("ai_news")])
    state = ProductizedRunState(
        board_type=BoardType.AI_NEWS,
        run_id="output-run",
        skill_traces=[{"skill": "existing"}],
        evidence_items=[{"source_id": "source-1"}],
        trend_analysis={"event_analyses": []},
    )
    report_result = BusinessSkillResult(
        skill_name="report-writing",
        output={"markdown_report": "# Report\n"},
        status="success",
    )

    bundle = ProductizedBoardOutputBundleBuilder().build(
        result=result,
        report_result=report_result,
        productized_run=state,
    )

    assert bundle.summary_md == "# Report\n"
    assert bundle.skill_traces[-1]["skill_name"] == "report-writing"
    assert bundle.board_run_result.metadata["productized_run_state"]["run_id"] == "output-run"
    assert bundle.board_output["metadata"]["productized_run_state"]["run_id"] == "output-run"
    assert "evidence_items" not in bundle.board_output["metadata"]
