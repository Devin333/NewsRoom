from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.source_recollection_execution import (
    DailySourceRecollectionExecutionReport,
    DailySourceRecollectionExecutionTaskResult,
)
from business.boards.cross_board.workflows.daily_intelligence.source_recollection_quality import (
    DailySourceRecollectionQualityService,
)


def test_source_recollection_quality_passes_complete_execution_report() -> None:
    assessment = DailySourceRecollectionQualityService().assess(
        DailySourceRecollectionExecutionReport(
            plan_id="plan-1",
            profile_id="profile-1",
            status="succeeded",
            task_count=1,
            succeeded_task_count=1,
            raw_item_count=1,
            fetch_request_count=1,
            fetch_result_count=1,
            tasks=[
                DailySourceRecollectionExecutionTaskResult(
                    task_id="task-1",
                    query="official launch timing",
                    raw_item_count=1,
                    status="succeeded",
                )
            ],
        )
    )

    assert assessment.decision == "pass"
    assert assessment.route == "continue_source_pipeline"
    assert assessment.recommended_action == "continue_source_pipeline"
    assert assessment.failed_thresholds == []
    assert assessment.passed_thresholds == [
        "raw_item_coverage",
        "problem_task_rate",
        "error_rate",
    ]


def test_source_recollection_quality_routes_insufficient_results_to_review() -> None:
    assessment = DailySourceRecollectionQualityService().assess(
        DailySourceRecollectionExecutionReport(
            plan_id="plan-1",
            profile_id="profile-1",
            status="failed",
            task_count=2,
            failed_task_count=2,
            raw_item_count=0,
            error_count=2,
            fetch_request_count=2,
            fetch_result_count=2,
            tasks=[
                DailySourceRecollectionExecutionTaskResult(
                    task_id="task-1",
                    query="official launch timing",
                    error_count=1,
                    status="failed",
                    reason="all_fetches_failed",
                ),
                DailySourceRecollectionExecutionTaskResult(
                    task_id="task-2",
                    query="independent confirmation",
                    error_count=1,
                    status="failed",
                    reason="all_fetches_failed",
                ),
            ],
        )
    )

    assert assessment.decision == "insufficient"
    assert assessment.severity == "warning"
    assert assessment.route == "source_recollection_quality_review"
    assert assessment.recommended_action == "review_source_recollection"
    assert assessment.failed_thresholds == [
        "raw_item_coverage",
        "problem_task_rate",
        "error_rate",
    ]
    assert assessment.issues == [
        "source_recollection_raw_item_threshold_missed",
        "source_recollection_problem_task_rate_exceeded",
        "source_recollection_error_rate_exceeded",
    ]


def test_source_recollection_quality_keeps_skipped_report_explicit() -> None:
    assessment = DailySourceRecollectionQualityService().assess(
        DailySourceRecollectionExecutionReport(
            status="skipped",
            reason="missing_or_empty_execution_plan",
        )
    )

    assert assessment.decision == "skipped"
    assert assessment.route == "continue_without_recollection"
    assert assessment.recommended_action == "continue_without_recollection"
    assert assessment.issues == ["missing_or_empty_execution_plan"]
