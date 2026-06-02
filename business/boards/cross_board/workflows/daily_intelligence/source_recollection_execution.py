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


__all__ = [
    "DailySourceRecollectionExecutionPlan",
    "DailySourceRecollectionExecutionService",
    "DailySourceRecollectionExecutionTask",
    "SOURCE_RECOLLECTION_EXECUTION_PLAN_SCHEMA_VERSION",
]
