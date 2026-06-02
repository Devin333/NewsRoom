from __future__ import annotations

from pydantic import Field

from business.foundation import PrimitiveModel
from business.boards.cross_board.workflows.daily_intelligence.agent_feedback_models import (
    SOURCE_RECOLLECT_TARGET,
)
from business.boards.cross_board.workflows.daily_intelligence.source_recollection import (
    DailySourceRecollectionProfile,
)


SOURCE_RECOLLECTION_EXECUTION_PLAN_SCHEMA_VERSION = (
    "business.cross_board.daily_source_recollection.execution_plan.v1"
)
SOURCE_RECOLLECTION_EXECUTION_REPORT_SCHEMA_VERSION = (
    "business.cross_board.daily_source_recollection.execution_report.v1"
)


class DailySourceRecollectionExecutionTask(PrimitiveModel):
    task_id: str
    query: str
    status: str = "ready"
    reason: str
    source_feedback_ids: list[str] = Field(default_factory=list)
    recommendation_ids: list[str] = Field(default_factory=list)


class DailySourceRecollectionExecutionPlan(PrimitiveModel):
    schema_version: str = SOURCE_RECOLLECTION_EXECUTION_PLAN_SCHEMA_VERSION
    plan_id: str
    profile_id: str
    target_id: str = SOURCE_RECOLLECT_TARGET
    status: str
    execution_mode: str = "source_fetch_execution_contract"
    source_recollect_round: int = 0
    max_source_recollect_rounds: int = 0
    reason: str
    tasks: list[DailySourceRecollectionExecutionTask] = Field(default_factory=list)
    task_count: int = 0
    query_count: int = 0
    source_feedback_ids: list[str] = Field(default_factory=list)
    recommendation_ids: list[str] = Field(default_factory=list)


class DailySourceRecollectionExecutionTaskResult(PrimitiveModel):
    task_id: str
    query: str
    selected_source_ids: list[str] = Field(default_factory=list)
    fetch_request_ids: list[str] = Field(default_factory=list)
    fetch_result_ids: list[str] = Field(default_factory=list)
    raw_item_count: int = 0
    error_count: int = 0
    status: str
    reason: str | None = None


class DailySourceRecollectionExecutionReport(PrimitiveModel):
    schema_version: str = SOURCE_RECOLLECTION_EXECUTION_REPORT_SCHEMA_VERSION
    plan_id: str | None = None
    profile_id: str | None = None
    status: str
    reason: str | None = None
    task_count: int = 0
    succeeded_task_count: int = 0
    partial_task_count: int = 0
    failed_task_count: int = 0
    skipped_task_count: int = 0
    raw_item_count: int = 0
    error_count: int = 0
    fetch_request_count: int = 0
    fetch_result_count: int = 0
    tasks: list[DailySourceRecollectionExecutionTaskResult] = Field(default_factory=list)


class DailySourceRecollectionExecutionService:
    def build_plan(
        self,
        profile: DailySourceRecollectionProfile | None,
    ) -> DailySourceRecollectionExecutionPlan | None:
        if profile is None:
            return None
        queries = _dedupe_text(profile.queries)
        tasks = [
            DailySourceRecollectionExecutionTask(
                task_id=f"{profile.profile_id}-task-{index:02d}",
                query=query,
                reason=profile.reason,
                source_feedback_ids=list(profile.source_feedback_ids),
                recommendation_ids=list(profile.recommendation_ids),
            )
            for index, query in enumerate(queries, start=1)
        ]
        status = "ready" if tasks else "empty"
        return DailySourceRecollectionExecutionPlan(
            plan_id=f"{profile.profile_id}-execution-plan",
            profile_id=profile.profile_id,
            status=status,
            source_recollect_round=profile.source_recollect_round,
            max_source_recollect_rounds=profile.max_source_recollect_rounds,
            reason=profile.reason,
            tasks=tasks,
            task_count=len(tasks),
            query_count=len(queries),
            source_feedback_ids=list(profile.source_feedback_ids),
            recommendation_ids=list(profile.recommendation_ids),
        )


class DailySourceRecollectionExecutionReportService:
    def skipped_report(
        self,
        *,
        reason: str,
        plan: DailySourceRecollectionExecutionPlan | None = None,
    ) -> DailySourceRecollectionExecutionReport:
        return DailySourceRecollectionExecutionReport(
            plan_id=plan.plan_id if plan is not None else None,
            profile_id=plan.profile_id if plan is not None else None,
            status="skipped",
            reason=reason,
            task_count=len(plan.tasks) if plan is not None else 0,
            skipped_task_count=len(plan.tasks) if plan is not None else 0,
            tasks=[
                DailySourceRecollectionExecutionTaskResult(
                    task_id=task.task_id,
                    query=task.query,
                    status="skipped",
                    reason=reason,
                )
                for task in (plan.tasks if plan is not None else [])
            ],
        )

    def build_report(
        self,
        *,
        plan: DailySourceRecollectionExecutionPlan,
        tasks: list[DailySourceRecollectionExecutionTaskResult],
    ) -> DailySourceRecollectionExecutionReport:
        task_count = len(tasks)
        succeeded_task_count = sum(1 for task in tasks if task.status == "succeeded")
        partial_task_count = sum(1 for task in tasks if task.status == "partial")
        failed_task_count = sum(1 for task in tasks if task.status == "failed")
        skipped_task_count = sum(1 for task in tasks if task.status == "skipped")
        return DailySourceRecollectionExecutionReport(
            plan_id=plan.plan_id,
            profile_id=plan.profile_id,
            status=_report_status(tasks),
            reason=plan.reason,
            task_count=task_count,
            succeeded_task_count=succeeded_task_count,
            partial_task_count=partial_task_count,
            failed_task_count=failed_task_count,
            skipped_task_count=skipped_task_count,
            raw_item_count=sum(task.raw_item_count for task in tasks),
            error_count=sum(task.error_count for task in tasks),
            fetch_request_count=sum(len(task.fetch_request_ids) for task in tasks),
            fetch_result_count=sum(len(task.fetch_result_ids) for task in tasks),
            tasks=tasks,
        )


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _report_status(tasks: list[DailySourceRecollectionExecutionTaskResult]) -> str:
    if not tasks:
        return "skipped"
    statuses = {task.status for task in tasks}
    if statuses == {"succeeded"}:
        return "succeeded"
    if statuses == {"failed"}:
        return "failed"
    if statuses == {"skipped"}:
        return "skipped"
    return "partial"


__all__ = [
    "DailySourceRecollectionExecutionPlan",
    "DailySourceRecollectionExecutionReport",
    "DailySourceRecollectionExecutionReportService",
    "DailySourceRecollectionExecutionService",
    "DailySourceRecollectionExecutionTask",
    "DailySourceRecollectionExecutionTaskResult",
    "SOURCE_RECOLLECTION_EXECUTION_REPORT_SCHEMA_VERSION",
    "SOURCE_RECOLLECTION_EXECUTION_PLAN_SCHEMA_VERSION",
]
