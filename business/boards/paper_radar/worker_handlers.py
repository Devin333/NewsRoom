from __future__ import annotations

from typing import Any

from business.boards.paper_radar.reader_feedback import PaperReaderFeedbackService
from business.layers._worker_utils import handler_output
from framework.workers.models import Task, TaskResult, TaskStatus


PAPER_READER_FEEDBACK_TASK_TYPE = "paper_reader.feedback_ingest"


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


class PaperReaderFeedbackTaskHandler:
    task_type = PAPER_READER_FEEDBACK_TASK_TYPE

    def __init__(
        self,
        *,
        event_repository: Any,
        feedback_service: PaperReaderFeedbackService | None = None,
    ) -> None:
        self.event_repository = event_repository
        self.feedback_service = feedback_service

    def handle(self, task: Task) -> TaskResult:
        result = handle_paper_reader_feedback_task(
            task.payload,
            event_repository=self.event_repository,
            feedback_service=self.feedback_service,
        )
        paper_id = str(task.payload.get("paper_id") or task.payload.get("paperId") or "all")
        return TaskResult(
            task_id=task.task_id,
            success=True,
            status=TaskStatus.SUCCEEDED,
            workflow_run_id=f"paper-reader-feedback:{paper_id}",
            run_status="succeeded",
            output=handler_output(result),
        )


def handle_paper_reader_feedback_task(
    payload: dict[str, Any],
    *,
    event_repository: Any,
    feedback_service: PaperReaderFeedbackService | None = None,
) -> dict[str, Any]:
    if event_repository is None:
        raise ValueError("event_repository is required")
    paper_id = _optional_text(payload.get("paper_id") or payload.get("paperId"))
    user_id = _optional_text(payload.get("user_id") or payload.get("userId"))
    limit = _positive_int(payload.get("limit"), default=100, field_name="limit")
    events = event_repository.list_unprocessed_events(
        limit=limit,
        user_id=user_id,
        paper_id=paper_id,
    )
    event_payloads = [_event_to_dict(event) for event in events]
    service = feedback_service or PaperReaderFeedbackService()
    result = service.ingest_reader_events(event_payloads)
    completed_event_ids = [*result.processed_event_ids, *result.skipped_event_ids]
    if completed_event_ids:
        event_repository.mark_events_processed(completed_event_ids)
    output = result.to_dict()
    output.update(
        {
            "event_count": len(event_payloads),
            "paper_id": paper_id,
            "user_id": user_id,
            "limit": limit,
            "marked_processed_event_ids": completed_event_ids,
        }
    )
    return output


def _event_to_dict(event: Any) -> dict[str, Any]:
    to_dict = getattr(event, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        return dict(payload) if isinstance(payload, dict) else {}
    return dict(event) if isinstance(event, dict) else {}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _positive_int(value: Any, *, default: int, field_name: str) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return parsed
