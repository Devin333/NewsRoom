from __future__ import annotations

from business.boards.ai_news.board_service import AINewsBoardService
from business.boards.application import BoardRunApplicationResultBuilder, BoardServiceRuntime
from business.boards.domain import (
    BoardEvidenceAssemblyService,
    BoardQualityService as DomainBoardQualityService,
    BoardRunReferenceService as DomainBoardRunReferenceService,
    BoardSignalRankingService,
    BoardSignalSelectionService as DomainBoardSignalSelectionService,
)
from business.boards.productized import (
    ProductizedBoardOutputBundleBuilder,
    ProductizedBoardOutputService,
    ProductizedReportWritingService,
    ProductizedSignalClassificationService,
    ProductizedRunStateMetadataProjector,
)
from business.boards.productized.models import ProductizedBoardOutputBundle, ProductizedRunState
from business.boards.services import (
    BoardRunMetadataBuilder,
    BoardRunMetadataPayload,
    BoardPipelineRunner,
    BoardPolicyApplicationService,
    BoardReportDescriptorService,
    BoardReportExtractionService,
    BoardRunBuildService,
    BoardRunReferenceService,
    BoardRunReferences,
    BoardRunResultBuilder,
    BoardSignalSelectionService,
)
from business.evaluation.fixtures import sample_signal
from business.foundation import AnalysisContext, BoardRunPipelineSnapshot, BoardType
from business.foundation.skills import BusinessSkillResult, BusinessSkillRuntime
from business.layers.output import BoardOutput, BoardOutputStats


def test_board_service_base_exposes_decomposed_boundary_services() -> None:
    service = AINewsBoardService()

    assert isinstance(service.runtime, BoardServiceRuntime)
    assert isinstance(service.selection_service, BoardSignalSelectionService)
    assert isinstance(service.selection_service, DomainBoardSignalSelectionService)
    assert isinstance(service.policy_application_service, BoardPolicyApplicationService)
    assert isinstance(service.pipeline_runner, BoardPipelineRunner)
    assert isinstance(service.reference_service, BoardRunReferenceService)
    assert isinstance(service.reference_service, DomainBoardRunReferenceService)
    assert isinstance(service.quality_service, DomainBoardQualityService)
    assert isinstance(service.report_descriptor_service, BoardReportDescriptorService)
    assert isinstance(service.report_service, BoardReportExtractionService)
    assert isinstance(service.result_builder, BoardRunResultBuilder)
    assert isinstance(service.result_builder.application_result_builder, BoardRunApplicationResultBuilder)
    assert isinstance(service.run_build_service, BoardRunBuildService)
    assert isinstance(service.result_builder.metadata_builder, BoardRunMetadataBuilder)
    assert service.result_builder.report_service is service.report_service
    assert service.run_build_service.selection_service is service.selection_service
    assert service.run_build_service.pipeline_runner is service.pipeline_runner
    assert service.run_build_service.result_builder is service.result_builder


def test_board_run_result_uses_reference_and_pipeline_snapshots() -> None:
    service = AINewsBoardService()

    result = service.build_board_run_result([sample_signal("ai_news")])

    assert result.board_intelligence is not None
    assert result.board_intelligence.focus == "product_adoption_news"
    assert result.board_intelligence.policy_profile_id
    assert result.board_output["metadata"]["board_type"] == BoardType.AI_NEWS.value
    assert result.pipeline_snapshot is not None
    assert result.pipeline_snapshot.schema_version == "business.board.run.pipeline_snapshot.v1"
    assert result.report_payloads
    assert result.artifact_refs
    assert result.evidence_refs
    assert result.pipeline_snapshot.processed_relations == result.metadata["processed_relations"]
    assert result.metadata["pipeline_snapshot"] == result.pipeline_snapshot.to_dict()
    assert result.metadata["board_output"] == result.board_output
    assert result.metadata["board_intelligence"]["focus"] == result.board_intelligence.focus


def test_pipeline_run_carries_formal_snapshot_before_result_metadata() -> None:
    service = AINewsBoardService()
    context = AnalysisContext(board_type=BoardType.AI_NEWS)
    selected = service.select_signals([sample_signal("ai_news")], context=context)

    pipeline_run = service.run_build_service.run_selected(
        selected,
        context=context,
        report_title=service._report_title(),
        report_summary=service._report_summary(),
    )

    assert isinstance(pipeline_run.pipeline_snapshot, BoardRunPipelineSnapshot)
    assert pipeline_run.pipeline_snapshot.extraction_count == len(pipeline_run.extraction_results)
    assert pipeline_run.pipeline_snapshot.analysis == pipeline_run.analysis.to_dict()


def test_board_run_build_service_centralizes_context_resolution() -> None:
    service = AINewsBoardService()
    context = AnalysisContext(board_type=BoardType.PROJECT_RADAR)

    resolved = service.run_build_service.resolve_context(context)

    assert resolved.board_type == BoardType.AI_NEWS
    assert service._resolve_context(context).board_type == BoardType.AI_NEWS


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
        pipeline_snapshot=BoardRunPipelineSnapshot(
            extraction_count=1,
            processed_relations=[{"relation_id": "rel-1"}],
            rejected_relations=[],
            analysis={"summary": "analysis"},
        ),
    )

    metadata = payload.to_result_metadata()

    assert isinstance(payload, BoardRunMetadataPayload)
    assert payload.schema_version == "business.board.run.metadata.v1"
    assert metadata["pipeline_snapshot"]["schema_version"] == "business.board.run.pipeline_snapshot.v1"
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

    extraction = BoardReportExtractionService().extract(output)
    report = BoardReportExtractionService().require_report(output)

    assert extraction.payloads[0]["board_name"] == "AI News"
    assert extraction.reports[0] == report
    assert report.report_id == "report-1"
    assert report.board_type == BoardType.AI_NEWS


def test_board_report_descriptor_service_centralizes_report_title_and_summary() -> None:
    service = AINewsBoardService()

    descriptor = service.report_descriptor_service.build(service.board_definition)

    assert descriptor.title == service._report_title()
    assert descriptor.summary == service._report_summary()


def test_pipeline_runner_preserves_annotation_and_board_output_postprocess_hook() -> None:
    service = AINewsBoardService()

    output = service.build_board_output([sample_signal("ai_news")])

    assert output.metadata["board_type"] == BoardType.AI_NEWS.value
    assert output.metadata["report"]["board_type"] == BoardType.AI_NEWS.value
    assert output.cards
    assert output.cards[0].metadata["board_focus"] == "product_adoption_news"


def test_productized_run_state_metadata_projector_owns_metadata_projection() -> None:
    state = ProductizedRunState(
        board_type=BoardType.AI_NEWS,
        run_id="run-1",
        topic="Agent Memory",
        skill_traces=[{"skill": "source-reliability"}],
        evidence_items=[{"source_id": "src-1"}],
    )
    projector = ProductizedRunStateMetadataProjector()

    metadata = projector.runtime_metadata(state)

    assert metadata["productized_run_state"]["schema_version"] == "business.board.productized.run_state.v1"
    assert metadata["skill_trace_metadata"] == [{"skill": "source-reliability"}]
    assert metadata["evidence_items"] == [{"source_id": "src-1"}]

    board_output_metadata = projector.board_output_metadata(state)
    assert board_output_metadata["skill_trace_metadata"] == [{"skill": "source-reliability"}]
    assert "evidence_items" not in board_output_metadata
    assert state.runtime_metadata() == metadata
    assert state.board_output_metadata() == board_output_metadata


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
    assert "board_service" not in service.__dict__


def test_productized_classification_service_uses_selection_port() -> None:
    class StubSelector:
        def __init__(self) -> None:
            self.calls = []

        def select_signals(self, signals, *, context):
            self.calls.append({"signals": signals, "context": context})
            return [signals[0]]

    selector = StubSelector()
    context = AnalysisContext(board_type=BoardType.AI_NEWS)
    service = ProductizedSignalClassificationService(selector=selector)

    result = service.classify(context=context, prepared_signals=["signal-1", "signal-2"])

    assert result == {"board_signals": ["signal-1"]}
    assert selector.calls == [{"signals": ["signal-1", "signal-2"], "context": context}]


def test_productized_output_service_uses_run_result_port_and_board_name() -> None:
    class StubReportResult:
        output = {"markdown_report": "# Stub\n"}

        def to_dict(self):
            return {"skill_name": "report-writing", "status": "success"}

    class StubReportWriter:
        def __init__(self) -> None:
            self.calls = []

        def write(self, *, request, board_name, cards, productized_run):
            self.calls.append(
                {
                    "request": request,
                    "board_name": board_name,
                    "cards": cards,
                    "productized_run": productized_run,
                }
            )
            return StubReportResult()

    class StubRunResultBuilder:
        def __init__(self, result) -> None:
            self.result = result
            self.calls = []

        def build_board_run_result(self, signals, *, context=None):
            self.calls.append({"signals": signals, "context": context})
            return self.result

    board_service = AINewsBoardService()
    run_result = board_service.build_board_run_result([sample_signal("ai_news")])
    run_result_builder = StubRunResultBuilder(run_result)
    report_writer = StubReportWriter()
    run_state = ProductizedRunState(board_type=BoardType.AI_NEWS, run_id="port-run")
    context = AnalysisContext(board_type=BoardType.AI_NEWS)
    service = ProductizedBoardOutputService(
        skill_runtime=BusinessSkillRuntime(),
        run_result_builder=run_result_builder,
        board_name="Port Board",
        report_writing_service=report_writer,
    )

    bundle = service.build(
        request={"run_id": "port-run"},
        context=context,
        ranked_signals=["ranked-signal"],
        productized_run=run_state,
    )

    assert bundle.summary_md == "# Stub\n"
    assert run_result_builder.calls == [{"signals": ["ranked-signal"], "context": context}]
    assert report_writer.calls[0]["board_name"] == "Port Board"


def test_productized_domain_services_are_exposed_at_board_domain_boundary() -> None:
    from business.boards.productized import ProductizedEvidenceService, ProductizedRankingService

    evidence_service = ProductizedEvidenceService()
    ranking_service = ProductizedRankingService()

    assert isinstance(evidence_service.evidence_service, BoardEvidenceAssemblyService)
    assert isinstance(ranking_service.ranking_service, BoardSignalRankingService)


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
    assert "productized_run_state" not in bundle.board_run_result.metadata
    assert bundle.board_output["metadata"]["productized_run_state"]["run_id"] == "output-run"
    assert "evidence_items" not in bundle.board_output["metadata"]
