from interfaces.api.models import ApiError as ApiApiError
from interfaces.api.models import ApiResponse as ApiApiResponse
from interfaces.api.models import ApprovalResumeContextRequest as ApiApprovalResumeContextRequest
from interfaces.api.models import ArtifactRef as ApiArtifactRef
from interfaces.api.models import DailyRunRequest as ApiDailyRunRequest
from interfaces.api.models import PageResult as ApiPageResult
from interfaces.api.models import Pagination as ApiPagination
from interfaces.api.models import ReportDetail as ApiReportDetail
from interfaces.api.models import ReportSummary as ApiReportSummary
from interfaces.api.models import RunRequest as ApiRunRequest
from interfaces.api.models import RunResponse as ApiRunResponse
from interfaces.api.models import WeeklyRunRequest as ApiWeeklyRunRequest
from interfaces.models import (
    ApiError,
    ApiResponse,
    ApprovalResumeContextRequest,
    ArtifactRef,
    DailyRunRequest,
    PageResult,
    Pagination,
    ReportDetail,
    ReportSummary,
    RunRequest,
    RunResponse,
    WeeklyRunRequest,
)


def test_contract_models_are_exported_from_shared_interfaces_models() -> None:
    assert ApiRunRequest is RunRequest
    assert ApiRunResponse is RunResponse
    assert ApiDailyRunRequest is DailyRunRequest
    assert ApiApiResponse is ApiResponse
    assert ApiApprovalResumeContextRequest is ApprovalResumeContextRequest
    assert ApiApiError is ApiError
    assert ApiArtifactRef is ArtifactRef
    assert ApiPagination is Pagination
    assert ApiPageResult is PageResult
    assert ApiReportSummary is ReportSummary
    assert ApiReportDetail is ReportDetail
    assert ApiWeeklyRunRequest is WeeklyRunRequest
    assert RunRequest.__module__ == "interfaces.models.contracts"
    assert RunResponse.__module__ == "interfaces.models.contracts"
    assert ReportSummary.__module__ == "interfaces.models.contracts"
    assert ReportDetail.__module__ == "interfaces.models.contracts"
    assert ApprovalResumeContextRequest().decision_key == "human_review_decision"
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
