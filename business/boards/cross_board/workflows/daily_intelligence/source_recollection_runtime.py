from __future__ import annotations

from dataclasses import replace
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.source_recollection_execution import (
    DailySourceRecollectionExecutionPlan,
    DailySourceRecollectionExecutionTask,
)
from business.foundation.models.source import SourceFetchRequest


class DailySourceRecollectionArtifactProjector:
    def task_metadata(
        self,
        plan: DailySourceRecollectionExecutionPlan,
        task: DailySourceRecollectionExecutionTask,
    ) -> dict[str, Any]:
        return {
            "source_recollection_plan_id": plan.plan_id,
            "source_recollection_profile_id": plan.profile_id,
            "source_recollection_task_id": task.task_id,
            "source_recollection_query": task.query,
        }

    def with_fetch_request(
        self,
        fetch_request: SourceFetchRequest,
        plan: DailySourceRecollectionExecutionPlan,
        task: DailySourceRecollectionExecutionTask,
    ) -> SourceFetchRequest:
        metadata = dict(fetch_request.metadata)
        metadata.update(self.task_metadata(plan, task))
        return replace(fetch_request, metadata=metadata)

    def with_raw_item(
        self,
        item: Any,
        plan: DailySourceRecollectionExecutionPlan,
        task: DailySourceRecollectionExecutionTask,
    ) -> Any:
        metadata = dict(getattr(item, "metadata", {}) or {})
        metadata.update(self.task_metadata(plan, task))
        if hasattr(item, "__dataclass_fields__"):
            return replace(item, metadata=metadata)
        if isinstance(item, dict):
            return {**item, "metadata": metadata}
        return item

    def skipped_source_metadata(
        self,
        metadata: dict[str, Any],
        plan: DailySourceRecollectionExecutionPlan,
        task: DailySourceRecollectionExecutionTask,
    ) -> dict[str, Any]:
        values = dict(metadata)
        values.update(self.task_metadata(plan, task))
        return values

    def task_id_from_item(self, item: Any) -> str | None:
        value = _item_metadata(item).get("source_recollection_task_id")
        return str(value) if value else None


class SourceRecollectionTaskItemTracker:
    def __init__(self, *, task_ids: list[str]) -> None:
        self._item_ids_by_task = {task_id: set() for task_id in task_ids}
        self._fallback_index = 0

    @classmethod
    def from_existing_items(
        cls,
        *,
        plan: DailySourceRecollectionExecutionPlan,
        items: list[Any],
        artifact_projector: DailySourceRecollectionArtifactProjector,
    ) -> "SourceRecollectionTaskItemTracker":
        tracker = cls(task_ids=[task.task_id for task in plan.tasks])
        for item in items:
            task_id = artifact_projector.task_id_from_item(item)
            if task_id:
                tracker._record_item_id(task_id, _item_id(item))
        return tracker

    def item_count(self, task: DailySourceRecollectionExecutionTask) -> int:
        return len(self._item_ids_by_task.get(task.task_id, set()))

    def record_items(self, task: DailySourceRecollectionExecutionTask, items: list[Any]) -> None:
        for item in items:
            self._record_item_id(task.task_id, _item_id(item))

    def _record_item_id(self, task_id: str, item_id: str | None) -> None:
        if task_id not in self._item_ids_by_task:
            return
        if not item_id:
            self._fallback_index += 1
            item_id = f"source-recollection-item-{self._fallback_index}"
        self._item_ids_by_task[task_id].add(item_id)


def _item_id(item: Any) -> str | None:
    if isinstance(item, dict):
        value = item.get("source_item_id")
    else:
        value = getattr(item, "source_item_id", None)
    return str(value) if value else None


def _item_metadata(item: Any) -> dict[str, Any]:
    metadata = getattr(item, "metadata", None)
    if isinstance(metadata, dict):
        return metadata
    if isinstance(item, dict):
        metadata = item.get("metadata")
        return metadata if isinstance(metadata, dict) else {}
    return {}


__all__ = [
    "DailySourceRecollectionArtifactProjector",
    "SourceRecollectionTaskItemTracker",
]
