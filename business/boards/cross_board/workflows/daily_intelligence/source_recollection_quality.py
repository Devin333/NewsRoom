from __future__ import annotations

from typing import Any

from pydantic import Field

from business.foundation import PrimitiveModel
from business.boards.cross_board.workflows.daily_intelligence.agent_feedback_models import (
    SOURCE_RECOLLECT_TARGET,
)
from business.boards.cross_board.workflows.daily_intelligence.source_recollection_execution import (
    DailySourceRecollectionExecutionReport,
)


SOURCE_RECOLLECTION_QUALITY_ASSESSMENT_SCHEMA_VERSION = (
    "business.cross_board.daily_source_recollection.quality_assessment.v1"
)


class DailySourceRecollectionQualityThresholds(PrimitiveModel):
    min_raw_items_per_task: int = Field(default=1, ge=0)
    max_problem_task_rate: float = Field(default=0.5, ge=0.0, le=1.0)
    max_error_rate: float = Field(default=0.5, ge=0.0, le=1.0)


class DailySourceRecollectionQualityAssessment(PrimitiveModel):
    schema_version: str = SOURCE_RECOLLECTION_QUALITY_ASSESSMENT_SCHEMA_VERSION
    plan_id: str | None = None
    profile_id: str | None = None
    policy_target_id: str = SOURCE_RECOLLECT_TARGET
    report_status: str | None = None
    decision: str
    severity: str
    route: str
    recommended_action: str
    task_count: int = 0
    raw_item_count: int = 0
    error_count: int = 0
    problem_task_count: int = 0
    problem_task_rate: float = 0.0
    error_rate: float = 0.0
    thresholds: DailySourceRecollectionQualityThresholds = Field(
        default_factory=DailySourceRecollectionQualityThresholds
    )
    passed_thresholds: list[str] = Field(default_factory=list)
    failed_thresholds: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class DailySourceRecollectionQualityService:
    def __init__(
        self,
        thresholds: DailySourceRecollectionQualityThresholds | None = None,
    ) -> None:
        self.thresholds = thresholds or DailySourceRecollectionQualityThresholds()

    def assess(
        self,
        report: DailySourceRecollectionExecutionReport | dict[str, Any] | None,
    ) -> DailySourceRecollectionQualityAssessment:
        execution_report = _execution_report(report)
        if execution_report is None:
            return self._skipped_assessment(
                reason="missing_execution_report",
                report_status=None,
            )
        if execution_report.status == "skipped":
            return self._skipped_assessment(
                reason=execution_report.reason or "source_recollection_skipped",
                report_status=execution_report.status,
                plan_id=execution_report.plan_id,
                profile_id=execution_report.profile_id,
                task_count=execution_report.task_count,
            )

        task_count = execution_report.task_count
        problem_task_count = (
            execution_report.partial_task_count
            + execution_report.failed_task_count
            + execution_report.skipped_task_count
        )
        problem_task_rate = _rate(problem_task_count, task_count)
        error_rate = _rate(execution_report.error_count, execution_report.fetch_result_count)
        expected_raw_items = task_count * self.thresholds.min_raw_items_per_task
        passed_thresholds: list[str] = []
        failed_thresholds: list[str] = []
        issues: list[str] = []

        _record_threshold(
            passed_thresholds,
            failed_thresholds,
            issues,
            name="raw_item_coverage",
            passed=execution_report.raw_item_count >= expected_raw_items,
            issue="source_recollection_raw_item_threshold_missed",
        )
        _record_threshold(
            passed_thresholds,
            failed_thresholds,
            issues,
            name="problem_task_rate",
            passed=problem_task_rate <= self.thresholds.max_problem_task_rate,
            issue="source_recollection_problem_task_rate_exceeded",
        )
        _record_threshold(
            passed_thresholds,
            failed_thresholds,
            issues,
            name="error_rate",
            passed=error_rate <= self.thresholds.max_error_rate,
            issue="source_recollection_error_rate_exceeded",
        )

        decision, severity, route, recommended_action = _route_assessment(
            report_status=execution_report.status,
            failed_thresholds=failed_thresholds,
            problem_task_count=problem_task_count,
            error_count=execution_report.error_count,
        )
        return DailySourceRecollectionQualityAssessment(
            plan_id=execution_report.plan_id,
            profile_id=execution_report.profile_id,
            report_status=execution_report.status,
            decision=decision,
            severity=severity,
            route=route,
            recommended_action=recommended_action,
            task_count=task_count,
            raw_item_count=execution_report.raw_item_count,
            error_count=execution_report.error_count,
            problem_task_count=problem_task_count,
            problem_task_rate=problem_task_rate,
            error_rate=error_rate,
            thresholds=self.thresholds,
            passed_thresholds=passed_thresholds,
            failed_thresholds=failed_thresholds,
            issues=issues,
        )

    def _skipped_assessment(
        self,
        *,
        reason: str,
        report_status: str | None,
        plan_id: str | None = None,
        profile_id: str | None = None,
        task_count: int = 0,
    ) -> DailySourceRecollectionQualityAssessment:
        return DailySourceRecollectionQualityAssessment(
            plan_id=plan_id,
            profile_id=profile_id,
            report_status=report_status,
            decision="skipped",
            severity="info",
            route="continue_without_recollection",
            recommended_action="continue_without_recollection",
            task_count=task_count,
            thresholds=self.thresholds,
            issues=[reason],
        )


def _execution_report(
    value: DailySourceRecollectionExecutionReport | dict[str, Any] | None,
) -> DailySourceRecollectionExecutionReport | None:
    if isinstance(value, DailySourceRecollectionExecutionReport):
        return value
    if isinstance(value, dict):
        return DailySourceRecollectionExecutionReport.model_validate(value)
    return None


def _record_threshold(
    passed_thresholds: list[str],
    failed_thresholds: list[str],
    issues: list[str],
    *,
    name: str,
    passed: bool,
    issue: str,
) -> None:
    if passed:
        passed_thresholds.append(name)
        return
    failed_thresholds.append(name)
    issues.append(issue)


def _route_assessment(
    *,
    report_status: str,
    failed_thresholds: list[str],
    problem_task_count: int,
    error_count: int,
) -> tuple[str, str, str, str]:
    if failed_thresholds:
        return (
            "insufficient",
            "warning",
            "source_recollection_quality_review",
            "review_source_recollection",
        )
    if report_status == "partial" or problem_task_count > 0 or error_count > 0:
        return (
            "partial",
            "info",
            "continue_source_pipeline_with_caution",
            "continue_with_caution",
        )
    return (
        "pass",
        "info",
        "continue_source_pipeline",
        "continue_source_pipeline",
    )


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


__all__ = [
    "DailySourceRecollectionQualityAssessment",
    "DailySourceRecollectionQualityService",
    "DailySourceRecollectionQualityThresholds",
    "SOURCE_RECOLLECTION_QUALITY_ASSESSMENT_SCHEMA_VERSION",
]
