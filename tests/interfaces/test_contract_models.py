from interfaces.models import (
    ApiError,
    ApiResponse,
    ApprovalResumeContextRequest,
    ApprovalView,
    ArtifactRef,
    MemorySearchMatch,
    MemorySearchResponse,
    PageResult,
    Pagination,
    ReportDetail,
    ReportSummary,
    RunResponse,
    ScheduleUpsertRequest,
    ScheduleView,
    SourceHealthView,
)


def test_contract_models_are_exported_from_shared_interfaces_models() -> None:
    assert RunResponse is not None
    assert ApiResponse is not None
    assert ApprovalResumeContextRequest is not None
    assert ApiError is not None
    assert ArtifactRef is not None
    assert Pagination is not None
    assert PageResult is not None
    assert ReportSummary is not None
    assert ReportDetail is not None
    assert SourceHealthView is not None
    assert MemorySearchResponse is not None
    assert ScheduleUpsertRequest is not None
    assert ScheduleView is not None
    assert ApprovalView is not None
    assert RunResponse.__module__ == "interfaces.models.contracts"
    assert ReportSummary.__module__ == "interfaces.models.contracts"
    assert ReportDetail.__module__ == "interfaces.models.contracts"
    assert ApprovalResumeContextRequest().decision_key == "human_review_decision"
    assert ScheduleUpsertRequest(
        schedule_id="memory-reindex",
        name="Memory reindex",
        task_type="memory.reindex",
    ).queue_name == "news:queue:memory"
    assert Pagination(limit=10).limit == 10
    assert PageResult(items=[]).items == []


def test_run_response_exposes_interface_and_runtime_statuses() -> None:
    response = RunResponse(
        run_id="run-1",
        task_id="task-1",
        status="queued",
        task_status="queued",
        run_status=None,
        report_status=None,
        report_id=None,
        artifact_refs=[],
        diagnostics=[],
        message="queued as msg-1",
    )

    payload = response.model_dump() if hasattr(response, "model_dump") else response.dict()

    assert payload["status"] == "queued"
    assert payload["task_status"] == "queued"
    assert payload["run_status"] is None
    assert payload["report_status"] is None
    assert payload["artifact_refs"] == []
    assert payload["diagnostics"] == []


def test_run_response_exposes_manifest_and_artifact_refs() -> None:
    response = RunResponse(
        run_id="run-1",
        status="succeeded",
        run_status="succeeded",
        report_status="final",
        report_id="run-1:final",
        manifest_ref=ArtifactRef(
            artifact_id="manifest",
            run_id="run-1",
            artifact_type="manifest",
            path="manifest.json",
            content_type="application/json",
        ),
        artifact_refs=[
            ArtifactRef(
                artifact_id="report_json",
                run_id="run-1",
                artifact_type="report_json",
                path="report.json",
                content_type="application/json",
            )
        ],
        diagnostics=["quality_route=human_review"],
    )

    payload = response.model_dump() if hasattr(response, "model_dump") else response.dict()

    assert payload["manifest_ref"]["artifact_id"] == "manifest"
    assert payload["artifact_refs"][0]["artifact_id"] == "report_json"
    assert payload["artifact_refs"][0]["content_type"] == "application/json"
    assert payload["diagnostics"] == ["quality_route=human_review"]


def test_report_summary_matches_target_contract_fields() -> None:
    summary = ReportSummary(
        report_id="report-1",
        run_id="run-1",
        status="final",
        title="Daily Intelligence",
        summary="A concise summary",
        citation_coverage_score=1.0,
        source_count=3,
        evidence_count=2,
        metadata={"topic": "AI"},
    )

    assert summary.summary == "A concise summary"
    assert summary.citation_coverage_score == 1.0
    assert summary.source_count == 3
    assert summary.evidence_count == 2


def test_target_view_models_are_serializable_and_schema_ready() -> None:
    health = SourceHealthView(
        source_id="source-1",
        source_name="Source",
        url="https://example.com/rss",
        status="healthy",
    )
    memory = MemorySearchResponse(
        collection="report_sections",
        query="agent runtime",
        limit=1,
        result_count=1,
        results=[
            MemorySearchMatch(
                document_id="doc-1",
                collection="report_sections",
                score=0.9,
                text="Agent runtime memory improved.",
                metadata={"run_id": "run-1"},
            )
        ],
    )
    schedule = ScheduleView(
        schedule_id="memory-reindex",
        name="Memory reindex",
        trigger_type="interval",
        task_type="memory.reindex",
        queue_name="news:queue:memory",
        interval_seconds=86400,
        payload={"run_id": "run-1"},
    )
    approval = ApprovalView(
        approval_id="approval-1",
        requested_action="publish_report",
        status="pending",
        risk_level="high",
        run_id="run-1",
        requested_by="operator",
    )

    payloads = [
        model.model_dump() if hasattr(model, "model_dump") else model.dict()
        for model in (health, memory, schedule, approval)
    ]

    assert payloads[0]["status"] == "healthy"
    assert payloads[1]["results"][0]["document_id"] == "doc-1"
    assert payloads[2]["payload"] == {"run_id": "run-1"}
    assert payloads[3]["requested_action"] == "publish_report"
    for model in (SourceHealthView, MemorySearchResponse, ScheduleView, ApprovalView):
        schema = (
            model.model_json_schema()
            if hasattr(model, "model_json_schema")
            else model.schema()
        )
        assert schema["title"] == model.__name__
