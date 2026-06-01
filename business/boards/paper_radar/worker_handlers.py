from __future__ import annotations

from typing import Any

from business.boards.paper_radar.reader_feedback import PaperReaderFeedbackService
from business.layers._worker_utils import handler_output
from framework.workers.models import Task, TaskResult, TaskStatus


PAPER_READER_FEEDBACK_TASK_TYPE = "paper_reader.feedback_ingest"
PAPER_VISUAL_COMPILE_TASK_TYPE = "papers.visual_compile"
PAPER_VISUAL_COMPILE_BACKFILL_TASK_TYPE = "papers.visual_compile_backfill"


class PaperIngestTaskHandler:
    task_type = "papers.ingest_github_arxiv_daily"

    def __init__(self, paper_ingest_service: Any, visual_compile_enqueue: Any | None = None) -> None:
        self.paper_ingest_service = paper_ingest_service
        self.visual_compile_enqueue = visual_compile_enqueue

    def handle(self, task: Task) -> TaskResult:
        result = self.paper_ingest_service.run_daily_ingest(
            candidate_limit=_optional_int(task.payload.get("candidate_limit")),
            min_github_stars=_optional_int(task.payload.get("min_github_stars")),
            run_id=task.payload.get("run_id"),
        )
        payload = result.to_dict()
        payload["visualCompileEnqueued"] = self._enqueue_visual_compile(payload)
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

    def _enqueue_visual_compile(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if self.visual_compile_enqueue is None:
            return []
        enqueued: list[dict[str, Any]] = []
        for paper_id in payload.get("publishedPaperIds") or []:
            if not isinstance(paper_id, str) or not paper_id.strip():
                continue
            try:
                result = self.visual_compile_enqueue(paper_id=paper_id)
            except Exception as exc:
                enqueued.append(
                    {
                        "paperId": paper_id,
                        "queued": False,
                        "reason": type(exc).__name__,
                        "message": str(exc),
                    }
                )
                continue
            to_dict = getattr(result, "to_dict", None)
            enqueued.append(
                {
                    "paperId": paper_id,
                    "queued": True,
                    "enqueued": to_dict() if callable(to_dict) else result,
                }
            )
        return enqueued


class PaperVisualCompileTaskHandler:
    task_type = PAPER_VISUAL_COMPILE_TASK_TYPE

    def __init__(self, paper_visual_compiler_service: Any) -> None:
        self.paper_visual_compiler_service = paper_visual_compiler_service

    def handle(self, task: Task) -> TaskResult:
        paper_id = _optional_text(task.payload.get("paper_id") or task.payload.get("paperId"))
        if not paper_id:
            raise ValueError("paper_id is required")
        force = _truthy(task.payload.get("force"))
        result = self.paper_visual_compiler_service.compile_paper(
            paper_id,
            force=force,
            run_id=_optional_text(task.payload.get("run_id") or task.payload.get("runId")),
        )
        payload = result.to_dict()
        status = payload.get("status")
        failed = status in {"compile_failed", "review_failed"}
        retryable = status != "review_failed"
        needs_review = payload.get("status") == "needs_review"
        return TaskResult(
            task_id=task.task_id,
            success=not failed,
            retryable=retryable,
            status=TaskStatus.WAITING_FOR_APPROVAL if needs_review else TaskStatus.FAILED if failed else TaskStatus.SUCCEEDED,
            workflow_run_id=f"paper-visual-compile:{paper_id}",
            run_status=str(payload.get("status") or "compiled"),
            output=handler_output(payload, run_id=f"paper-visual-compile:{paper_id}"),
            error_type=str(payload.get("status")) if failed or needs_review else None,
            error_message=_first_diagnostic_message(payload.get("diagnostics")) if failed or needs_review else None,
        )


class PaperVisualCompileBackfillTaskHandler:
    task_type = PAPER_VISUAL_COMPILE_BACKFILL_TASK_TYPE

    def __init__(self, paper_visual_compiler_service: Any, visual_compile_enqueue: Any) -> None:
        self.paper_visual_compiler_service = paper_visual_compiler_service
        self.visual_compile_enqueue = visual_compile_enqueue

    def handle(self, task: Task) -> TaskResult:
        limit = _optional_positive_int(task.payload.get("limit"), field_name="limit")
        force = _truthy(task.payload.get("force"))
        run_id = _optional_text(task.payload.get("run_id") or task.payload.get("runId"))
        plan = self.paper_visual_compiler_service.plan_visual_compile_backfill(
            limit=limit,
            force=force,
            run_id=run_id,
        )
        enqueued: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for candidate in plan.candidates:
            try:
                result = self.visual_compile_enqueue(
                    paper_id=candidate.paper_id,
                    force=force,
                    run_id=run_id,
                )
            except Exception as exc:
                error = {
                    "paperId": candidate.paper_id,
                    "queued": False,
                    "reason": type(exc).__name__,
                    "message": str(exc),
                }
                errors.append(error)
                enqueued.append(error)
                continue
            to_dict = getattr(result, "to_dict", None)
            enqueued.append(
                {
                    "paperId": candidate.paper_id,
                    "queued": True,
                    "reason": candidate.reason,
                    "enqueued": to_dict() if callable(to_dict) else result,
                }
            )
        payload = plan.to_dict()
        payload.update(
            {
                "enqueued": enqueued,
                "enqueuedCount": sum(1 for item in enqueued if item.get("queued")),
                "errorCount": len(errors),
                "errors": errors,
            }
        )
        return TaskResult(
            task_id=task.task_id,
            success=not errors,
            retryable=bool(errors),
            status=TaskStatus.FAILED if errors else TaskStatus.SUCCEEDED,
            workflow_run_id=run_id or f"paper-visual-compile-backfill:{task.task_id}",
            run_status="failed" if errors else "succeeded",
            output=handler_output(payload, run_id=run_id),
            error_type="paper_visual_compile_backfill_enqueue_failed" if errors else None,
            error_message=errors[0]["message"] if errors else None,
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


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)


def _first_diagnostic_message(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("message"), str):
                return item["message"]
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


def _optional_positive_int(value: Any, *, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    return _positive_int(value, default=1, field_name=field_name)


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
