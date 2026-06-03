from business.boards.cross_board.workflows.daily_intelligence.source_recollection_artifact_projection import (
    source_recollection_manifest_summary,
    source_recollection_quality_manifest_summary,
)
from business.boards.cross_board.workflows.daily_intelligence.source_recollection_execution import (
    DailySourceRecollectionExecutionReport,
)
from business.boards.cross_board.workflows.daily_intelligence.source_recollection_quality import (
    DailySourceRecollectionQualityAssessment,
)


def test_source_recollection_manifest_summary_projects_namespaced_report_and_quality() -> None:
    summary = source_recollection_manifest_summary(
        {
            "sources.recollection_profile": {"profile_id": "profile-1"},
            "sources.recollection_execution_plan": {"plan_id": "plan-1"},
            "sources.recollection_execution_report": {
                "plan_id": "plan-1",
                "status": "succeeded",
                "task_count": "2",
                "raw_item_count": 4,
                "error_count": 0,
                "fetch_request_count": 2,
                "fetch_result_count": 2,
            },
            "sources.recollection_quality_assessment": {
                "decision": "pass",
                "severity": "info",
                "route": "continue_source_pipeline",
                "recommended_action": "continue_source_pipeline",
            },
        }
    )

    assert summary == {
        "plan_id": "plan-1",
        "status": "succeeded",
        "task_count": 2,
        "raw_item_count": 4,
        "error_count": 0,
        "fetch_request_count": 2,
        "fetch_result_count": 2,
        "artifact": "source_recollection/execution_report.json",
        "profile_artifact": "source_recollection/profile.json",
        "plan_artifact": "source_recollection/execution_plan.json",
        "quality": {
            "decision": "pass",
            "severity": "info",
            "route": "continue_source_pipeline",
            "recommended_action": "continue_source_pipeline",
            "artifact": "source_recollection/quality_assessment.json",
        },
    }


def test_source_recollection_manifest_summary_projects_formal_models() -> None:
    report = DailySourceRecollectionExecutionReport(
        plan_id="plan-1",
        profile_id="profile-1",
        status="partial",
        task_count=2,
        raw_item_count=1,
        error_count=1,
        fetch_request_count=2,
        fetch_result_count=2,
    )
    assessment = DailySourceRecollectionQualityAssessment(
        plan_id="plan-1",
        profile_id="profile-1",
        report_status="partial",
        decision="partial",
        severity="info",
        route="continue_source_pipeline_with_caution",
        recommended_action="continue_with_caution",
    )

    summary = source_recollection_manifest_summary(
        {
            "source_recollection_execution_report": report,
            "source_recollection_quality_assessment": assessment,
        }
    )

    assert summary is not None
    assert summary["plan_id"] == "plan-1"
    assert summary["status"] == "partial"
    assert summary["raw_item_count"] == 1
    assert "profile_artifact" not in summary
    assert "plan_artifact" not in summary
    assert summary["quality"] == {
        "decision": "partial",
        "severity": "info",
        "route": "continue_source_pipeline_with_caution",
        "recommended_action": "continue_with_caution",
        "artifact": "source_recollection/quality_assessment.json",
    }


def test_source_recollection_manifest_summary_skips_missing_report() -> None:
    assert source_recollection_manifest_summary({}) is None


def test_source_recollection_quality_manifest_summary_handles_unknown_shape() -> None:
    assert source_recollection_quality_manifest_summary("invalid") == {
        "decision": None,
        "severity": None,
        "route": None,
        "recommended_action": None,
        "artifact": "source_recollection/quality_assessment.json",
    }
