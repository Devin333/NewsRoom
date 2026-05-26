from __future__ import annotations

from typing import Any

from business.layers._worker_utils import handler_output
from framework.workers.models import Task, TaskResult, TaskStatus


class PaperIngestTaskHandler:
    task_type = "papers.ingest_github_arxiv_daily"

    def __init__(self, paper_ingest_service: Any) -> None:
        self.paper_ingest_service = paper_ingest_service

    def handle(self, task: Task) -> TaskResult:
        result = self.paper_ingest_service.run_daily_ingest(
            candidate_limit=_optional_int(task.payload.get("candidate_limit")),
            min_github_stars=_optional_int(task.payload.get("min_github_stars")),
            run_id=task.payload.get("run_id"),
        )
        payload = result.to_dict()
        blocked = payload.get("status") == "blocked"
        failed = payload.get("status") == "failed"
        return TaskResult(
            task_id=task.task_id,
            success=not failed,
            status=TaskStatus.WAITING_FOR_APPROVAL if blocked else TaskStatus.SUCCEEDED if not failed else TaskStatus.FAILED,
            workflow_run_id=payload.get("runId"),
            run_status=str(payload.get("status") or "succeeded"),
            output=handler_output(payload, run_id=payload.get("runId")),
            error_type="paper_ingest_blocked" if blocked else None,
            error_message="paper ingest has credential, permission, or account blockers" if blocked else None,
        )


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
