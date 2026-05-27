from __future__ import annotations

from threading import Thread
from uuid import uuid4

from pydantic import BaseModel, Field
from fastapi import APIRouter, Header, Query
from fastapi.responses import FileResponse

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.services.auth_service import AuthSessionInvalidError
from interfaces.services.paper_ingest_service import PAPER_INGEST_TASK_TYPE
from interfaces.services.paper_reader_notes_service import PaperReaderNoteNotFoundError
from interfaces.services.paper_service import (
    DEFAULT_LIMIT,
    DEFAULT_OPS_STATS_WINDOW_HOURS,
    MAX_LIMIT,
    MAX_OPS_STATS_WINDOW_HOURS,
    PaperCacheInvalidError,
    PaperCacheNotFoundError,
    PaperListQuery,
    PaperNotFoundError,
    PaperPeriod,
    PaperSort,
    PaperSummaryUnavailableError,
)


class PaperAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    locale: str = Field("en", pattern="^(zh|en)$")


class PaperStatePatchRequest(BaseModel):
    favorite: bool | None = None
    subscribed: bool | None = None
    readingStatus: str | None = Field(default=None, pattern="^(unread|reading|finished)$")
    currentPage: int | None = Field(default=None, ge=1)
    progressPercent: int | None = Field(default=None, ge=0, le=100)


class PaperIngestTriggerRequest(BaseModel):
    candidateLimit: int | None = Field(default=None, ge=1, le=500)
    minGithubStars: int | None = Field(default=None, ge=0, le=1_000_000)
    runId: str | None = Field(default=None, min_length=1, max_length=120)


class PaperClassificationBackfillTriggerRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=100_000)
    batchSize: int = Field(default=25, ge=1, le=500)
    runId: str | None = Field(default=None, min_length=1, max_length=120)


class PaperReaderNoteAnchorRequest(BaseModel):
    pageNumber: int | None = Field(default=None, ge=1)
    quote: str | None = Field(default=None, max_length=2000)
    rects: list[dict[str, float]] | None = None
    textStart: int | None = Field(default=None, ge=0)
    textEnd: int | None = Field(default=None, ge=0)


class PaperReaderNoteCreateRequest(BaseModel):
    kind: str = Field(..., pattern="^(bookmark|highlight|note)$")
    pageNumber: int = Field(..., ge=1)
    color: str = Field("yellow", pattern="^(yellow|green|blue|pink)$")
    quote: str | None = Field(default=None, max_length=2000)
    noteText: str | None = Field(default=None, max_length=4000)
    label: str | None = Field(default=None, max_length=200)
    anchor: PaperReaderNoteAnchorRequest | None = None


class PaperReaderNotePatchRequest(BaseModel):
    color: str | None = Field(default=None, pattern="^(yellow|green|blue|pink)$")
    quote: str | None = Field(default=None, max_length=2000)
    noteText: str | None = Field(default=None, max_length=4000)
    label: str | None = Field(default=None, max_length=200)
    anchor: PaperReaderNoteAnchorRequest | None = None


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/papers")
    def list_papers(
        limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
        offset: int = Query(0, ge=0),
        q: str | None = Query(None, max_length=200),
        period: PaperPeriod = Query("all"),
        sort: PaperSort = Query("trending"),
        task: str | None = Query(None, max_length=100),
        method: str | None = Query(None, max_length=100),
    ):
        try:
            result = services.papers_service_factory().list_papers(
                PaperListQuery(
                    q=(q or "").strip(),
                    period=period,
                    sort=sort,
                    task=_optional_text(task),
                    method=_optional_text(method),
                    limit=limit,
                    offset=offset,
                )
            )
        except PaperCacheNotFoundError:
            return helpers.error(
                status_code=404,
                code="papers_cache_not_found",
                message="papers data cache was not found",
                user_action_required=True,
            )
        except PaperCacheInvalidError as exc:
            return helpers.error(
                status_code=500,
                code="papers_cache_invalid",
                message="papers data cache could not be read",
                details={"reason": str(exc)},
                retryable=True,
            )
        return helpers.success(result.to_dict())

    @router.get("/api/v1/papers/tasks")
    def list_tasks():
        try:
            tasks = services.papers_service_factory().list_tasks()
        except PaperCacheNotFoundError:
            return helpers.error(
                status_code=404,
                code="papers_cache_not_found",
                message="papers data cache was not found",
                user_action_required=True,
            )
        except PaperCacheInvalidError as exc:
            return helpers.error(
                status_code=500,
                code="papers_cache_invalid",
                message="papers data cache could not be read",
                details={"reason": str(exc)},
                retryable=True,
            )
        return helpers.success({"tasks": list(tasks)})

    @router.get("/api/v1/papers/methods")
    def list_methods():
        try:
            methods = services.papers_service_factory().list_methods()
        except PaperCacheNotFoundError:
            return helpers.error(
                status_code=404,
                code="papers_cache_not_found",
                message="papers data cache was not found",
                user_action_required=True,
            )
        except PaperCacheInvalidError as exc:
            return helpers.error(
                status_code=500,
                code="papers_cache_invalid",
                message="papers data cache could not be read",
                details={"reason": str(exc)},
                retryable=True,
            )
        return helpers.success({"methods": list(methods)})

    @router.get("/api/v1/papers/ops/stats")
    def get_paper_reader_ops_stats(
        window_hours: int = Query(
            DEFAULT_OPS_STATS_WINDOW_HOURS,
            alias="windowHours",
            ge=1,
            le=MAX_OPS_STATS_WINDOW_HOURS,
        )
    ):
        stats = services.papers_service_factory().get_ops_stats(window_hours=window_hours)
        return helpers.success({"stats": stats})

    @router.get("/api/v1/papers/ops/ingest")
    def get_paper_ingest_ops(limit: int = Query(20, ge=1, le=100)):
        ops = services.paper_ingest_service_factory().get_ops_state(limit=limit)
        return helpers.success({"ingest": ops})

    @router.get("/api/v1/papers/ops/ingest-runs")
    def get_paper_ingest_runs(limit: int = Query(20, ge=1, le=100)):
        ops = services.paper_ingest_service_factory().get_ops_state(limit=limit)
        return helpers.success({"runs": ops.get("runs", [])})

    @router.get("/api/v1/papers/ops/repair")
    def get_paper_ingest_repair_queue(limit: int = Query(20, ge=1, le=100)):
        ops = services.paper_ingest_service_factory().get_ops_state(limit=limit)
        return helpers.success({"items": ops.get("repairQueue", [])})

    @router.get("/api/v1/papers/ops/blocked")
    def get_paper_ingest_blocked_items(limit: int = Query(20, ge=1, le=100)):
        ops = services.paper_ingest_service_factory().get_ops_state(limit=limit)
        return helpers.success({"items": ops.get("blockedItems", [])})

    @router.get("/api/v1/papers/ops/taxonomy-events")
    def get_paper_ingest_taxonomy_events(limit: int = Query(20, ge=1, le=100)):
        ops = services.paper_ingest_service_factory().get_ops_state(limit=limit)
        return helpers.success({"events": ops.get("taxonomyEvents", [])})

    @router.post("/api/v1/papers/ops/ingest/trigger")
    def trigger_paper_ingest(request: PaperIngestTriggerRequest):
        try:
            result = services.worker_service_factory().enqueue_paper_ingest(
                candidate_limit=request.candidateLimit,
                min_github_stars=request.minGithubStars,
                run_id=request.runId,
            )
        except ValueError as exc:
            return helpers.error(
                status_code=400,
                code="paper_ingest_trigger_invalid",
                message=str(exc),
                user_action_required=True,
            )
        except Exception as exc:
            if not _is_worker_queue_unavailable(exc):
                return helpers.error(
                    status_code=503,
                    code="paper_ingest_trigger_unavailable",
                    message=str(exc),
                    retryable=True,
            )
            run_id = request.runId or f"paper-ingest-local-{uuid4().hex[:12]}"
            paper_ingest_service = services.paper_ingest_service_factory()
            _start_paper_ingest_background(
                paper_ingest_service,
                candidate_limit=request.candidateLimit,
                min_github_stars=request.minGithubStars,
                run_id=run_id,
            )
            return helpers.success(
                {
                    "enqueued": {
                        "message_id": "local-background",
                        "task_id": f"{run_id}:local-background",
                        "task_type": PAPER_INGEST_TASK_TYPE,
                        "queue_name": "local:background",
                        "status": "queued",
                        "run_id": run_id,
                        "mode": "local_background",
                        "fallback_reason": "worker_queue_unavailable",
                    }
                }
            )
        return helpers.success({"enqueued": result.to_dict()})

    @router.post("/api/v1/papers/ops/classification-backfill/trigger")
    def trigger_paper_classification_backfill(request: PaperClassificationBackfillTriggerRequest):
        run_id = request.runId or f"paper-classification-backfill-local-{uuid4().hex[:12]}"
        paper_ingest_service = services.paper_ingest_service_factory()
        _start_paper_classification_backfill_background(
            paper_ingest_service,
            limit=request.limit,
            batch_size=request.batchSize,
            run_id=run_id,
        )
        return helpers.success(
            {
                "backfill": {
                    "runId": run_id,
                    "status": "queued",
                    "mode": "local_background",
                    "limit": request.limit,
                    "batchSize": request.batchSize,
                    "scannedCount": 0,
                    "updatedCount": 0,
                    "skippedCount": 0,
                    "repairQueuedCount": 0,
                    "blockedCount": 0,
                    "updatedPaperIds": [],
                    "errors": [],
                }
            }
        )

    @router.get("/api/v1/papers/assets/thumbnails/{file_name}")
    def get_paper_thumbnail(file_name: str):
        path = services.paper_ingest_service_factory().get_thumbnail_path(file_name)
        if path is None:
            return helpers.error(
                status_code=404,
                code="paper_thumbnail_not_found",
                message="paper thumbnail was not found",
                user_action_required=True,
            )
        return FileResponse(path, media_type="image/png")

    @router.get("/api/v1/papers/me/state")
    def list_my_paper_state(
        paper_ids: str | None = Query(None, alias="paperIds", max_length=2000),
        x_newsroom_session: str | None = Header(default=None),
    ):
        user_id = _session_user_id(services, helpers, x_newsroom_session)
        if not isinstance(user_id, str):
            return user_id
        ids = [item.strip() for item in (paper_ids or "").split(",") if item.strip()] or None
        states = services.paper_user_state_service_factory().list_states(user_id=user_id, paper_ids=ids)
        return helpers.success({"states": [state.to_dict() for state in states]})

    @router.get("/api/v1/papers/{paper_id}")
    def get_paper(paper_id: str):
        try:
            paper = services.papers_service_factory().get_paper(paper_id)
        except PaperCacheNotFoundError:
            return helpers.error(
                status_code=404,
                code="papers_cache_not_found",
                message="papers data cache was not found",
                user_action_required=True,
            )
        except PaperCacheInvalidError as exc:
            return helpers.error(
                status_code=500,
                code="papers_cache_invalid",
                message="papers data cache could not be read",
                details={"reason": str(exc)},
                retryable=True,
            )
        except PaperNotFoundError:
            return helpers.error(
                status_code=404,
                code="paper_not_found",
                message="paper was not found",
                user_action_required=True,
            )
        return helpers.success({"paper": paper.to_dict()})

    @router.get("/api/v1/papers/{paper_id}/state")
    def get_paper_state(paper_id: str, x_newsroom_session: str | None = Header(default=None)):
        user_id = _session_user_id(services, helpers, x_newsroom_session)
        if not isinstance(user_id, str):
            return user_id
        state = services.paper_user_state_service_factory().get_state(user_id=user_id, paper_id=paper_id)
        return helpers.success({"state": state.to_dict()})

    @router.patch("/api/v1/papers/{paper_id}/state")
    def patch_paper_state(
        paper_id: str,
        request: PaperStatePatchRequest,
        x_newsroom_session: str | None = Header(default=None),
    ):
        user_id = _session_user_id(services, helpers, x_newsroom_session)
        if not isinstance(user_id, str):
            return user_id
        patch = request.model_dump(exclude_none=True)
        try:
            state = services.paper_user_state_service_factory().patch_state(
                user_id=user_id,
                paper_id=paper_id,
                patch=patch,
            )
        except ValueError as exc:
            return helpers.error(
                status_code=400,
                code="paper_state_invalid",
                message=str(exc),
                user_action_required=True,
            )
        return helpers.success({"state": state.to_dict()})

    @router.get("/api/v1/papers/{paper_id}/notes")
    def list_paper_notes(paper_id: str, x_newsroom_session: str | None = Header(default=None)):
        user_id = _session_user_id(services, helpers, x_newsroom_session)
        if not isinstance(user_id, str):
            return user_id
        notes = services.paper_reader_notes_service_factory().list_notes(user_id=user_id, paper_id=paper_id)
        return helpers.success({"notes": [note.to_dict() for note in notes]})

    @router.post("/api/v1/papers/{paper_id}/notes")
    def create_paper_note(
        paper_id: str,
        request: PaperReaderNoteCreateRequest,
        x_newsroom_session: str | None = Header(default=None),
    ):
        user_id = _session_user_id(services, helpers, x_newsroom_session)
        if not isinstance(user_id, str):
            return user_id
        try:
            note = services.paper_reader_notes_service_factory().create_note(
                user_id=user_id,
                paper_id=paper_id,
                payload=request.model_dump(exclude_none=True),
            )
        except ValueError as exc:
            return helpers.error(
                status_code=400,
                code="paper_reader_note_invalid",
                message=str(exc),
                user_action_required=True,
            )
        return helpers.success({"note": note.to_dict()})

    @router.patch("/api/v1/papers/{paper_id}/notes/{note_id}")
    def patch_paper_note(
        paper_id: str,
        note_id: str,
        request: PaperReaderNotePatchRequest,
        x_newsroom_session: str | None = Header(default=None),
    ):
        user_id = _session_user_id(services, helpers, x_newsroom_session)
        if not isinstance(user_id, str):
            return user_id
        try:
            note = services.paper_reader_notes_service_factory().patch_note(
                user_id=user_id,
                paper_id=paper_id,
                note_id=note_id,
                patch=request.model_dump(exclude_none=True),
            )
        except PaperReaderNoteNotFoundError:
            return helpers.error(
                status_code=404,
                code="paper_reader_note_not_found",
                message="paper reader note was not found",
                user_action_required=True,
            )
        except ValueError as exc:
            return helpers.error(
                status_code=400,
                code="paper_reader_note_invalid",
                message=str(exc),
                user_action_required=True,
            )
        return helpers.success({"note": note.to_dict()})

    @router.delete("/api/v1/papers/{paper_id}/notes/{note_id}")
    def delete_paper_note(
        paper_id: str,
        note_id: str,
        x_newsroom_session: str | None = Header(default=None),
    ):
        user_id = _session_user_id(services, helpers, x_newsroom_session)
        if not isinstance(user_id, str):
            return user_id
        try:
            services.paper_reader_notes_service_factory().delete_note(
                user_id=user_id,
                paper_id=paper_id,
                note_id=note_id,
            )
        except PaperReaderNoteNotFoundError:
            return helpers.error(
                status_code=404,
                code="paper_reader_note_not_found",
                message="paper reader note was not found",
                user_action_required=True,
            )
        return helpers.success({"deleted": True})

    @router.post("/api/v1/papers/{paper_id}/summary")
    def summarize_paper(
        paper_id: str,
        locale: str = Query("en", pattern="^(zh|en)$"),
        refresh: bool = Query(False),
    ):
        try:
            summary = services.papers_service_factory().get_or_generate_summary(
                paper_id,
                locale=locale,  # type: ignore[arg-type]
                refresh=refresh,
            )
        except PaperNotFoundError:
            return helpers.error(
                status_code=404,
                code="paper_not_found",
                message="paper was not found",
                user_action_required=True,
            )
        except PaperSummaryUnavailableError as exc:
            return helpers.error(
                status_code=503,
                code="paper_summary_unavailable",
                message="NewsRoom AI summary is unavailable",
                details={"reason": str(exc)},
                retryable=True,
            )
        except PaperCacheNotFoundError:
            return helpers.error(
                status_code=404,
                code="papers_cache_not_found",
                message="papers data cache was not found",
                user_action_required=True,
            )
        except PaperCacheInvalidError as exc:
            return helpers.error(
                status_code=500,
                code="papers_cache_invalid",
                message="papers data cache could not be read",
                details={"reason": str(exc)},
                retryable=True,
            )
        return helpers.success({"summary": summary.to_dict()})

    @router.get("/api/v1/papers/{paper_id}/reader")
    def get_reader_payload(paper_id: str, locale: str = Query("en", pattern="^(zh|en)$")):
        try:
            reader = services.papers_service_factory().get_reader_payload(
                paper_id,
                locale=locale,  # type: ignore[arg-type]
            )
        except PaperCacheNotFoundError:
            return helpers.error(
                status_code=404,
                code="papers_cache_not_found",
                message="papers data cache was not found",
                user_action_required=True,
            )
        except PaperCacheInvalidError as exc:
            return helpers.error(
                status_code=500,
                code="papers_cache_invalid",
                message="papers data cache could not be read",
                details={"reason": str(exc)},
                retryable=True,
            )
        except PaperNotFoundError:
            return helpers.error(
                status_code=404,
                code="paper_not_found",
                message="paper was not found",
                user_action_required=True,
            )
        return helpers.success({"reader": reader.to_dict()})

    @router.get("/api/v1/papers/{paper_id}/sections")
    def get_paper_sections(paper_id: str, locale: str = Query("en", pattern="^(zh|en)$")):
        try:
            sections = services.papers_service_factory().get_paper_sections(
                paper_id,
                locale=locale,  # type: ignore[arg-type]
            )
        except PaperCacheNotFoundError:
            return helpers.error(
                status_code=404,
                code="papers_cache_not_found",
                message="papers data cache was not found",
                user_action_required=True,
            )
        except PaperCacheInvalidError as exc:
            return helpers.error(
                status_code=500,
                code="papers_cache_invalid",
                message="papers data cache could not be read",
                details={"reason": str(exc)},
                retryable=True,
            )
        except PaperNotFoundError:
            return helpers.error(
                status_code=404,
                code="paper_not_found",
                message="paper was not found",
                user_action_required=True,
            )
        return helpers.success({"sections": list(sections)})

    @router.get("/api/v1/papers/{paper_id}/related")
    def get_related_papers(paper_id: str):
        try:
            related_papers = services.papers_service_factory().get_related_papers(paper_id)
        except PaperCacheNotFoundError:
            return helpers.error(
                status_code=404,
                code="papers_cache_not_found",
                message="papers data cache was not found",
                user_action_required=True,
            )
        except PaperCacheInvalidError as exc:
            return helpers.error(
                status_code=500,
                code="papers_cache_invalid",
                message="papers data cache could not be read",
                details={"reason": str(exc)},
                retryable=True,
            )
        except PaperNotFoundError:
            return helpers.error(
                status_code=404,
                code="paper_not_found",
                message="paper was not found",
                user_action_required=True,
            )
        return helpers.success({"relatedPapers": list(related_papers)})

    @router.get("/api/v1/papers/{paper_id}/graph")
    def get_paper_graph(paper_id: str):
        try:
            graph = services.papers_service_factory().get_paper_graph(paper_id)
        except PaperCacheNotFoundError:
            return helpers.error(
                status_code=404,
                code="papers_cache_not_found",
                message="papers data cache was not found",
                user_action_required=True,
            )
        except PaperCacheInvalidError as exc:
            return helpers.error(
                status_code=500,
                code="papers_cache_invalid",
                message="papers data cache could not be read",
                details={"reason": str(exc)},
                retryable=True,
            )
        except PaperNotFoundError:
            return helpers.error(
                status_code=404,
                code="paper_not_found",
                message="paper was not found",
                user_action_required=True,
            )
        return helpers.success({"graph": graph})

    @router.post("/api/v1/papers/{paper_id}/ask")
    def ask_paper(paper_id: str, request: PaperAskRequest):
        try:
            answer = services.papers_service_factory().ask_paper(
                paper_id,
                question=request.question,
                locale=request.locale,  # type: ignore[arg-type]
            )
        except ValueError as exc:
            return helpers.error(
                status_code=400,
                code="paper_question_invalid",
                message="paper question is invalid",
                details={"reason": str(exc)},
                user_action_required=True,
            )
        except PaperCacheNotFoundError:
            return helpers.error(
                status_code=404,
                code="papers_cache_not_found",
                message="papers data cache was not found",
                user_action_required=True,
            )
        except PaperCacheInvalidError as exc:
            return helpers.error(
                status_code=500,
                code="papers_cache_invalid",
                message="papers data cache could not be read",
                details={"reason": str(exc)},
                retryable=True,
            )
        except PaperNotFoundError:
            return helpers.error(
                status_code=404,
                code="paper_not_found",
                message="paper was not found",
                user_action_required=True,
            )
        return helpers.success({"answer": answer.to_dict()})

    return router


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _is_worker_queue_unavailable(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".casefold()
    return any(
        hint in text
        for hint in (
            "redis",
            "connection refused",
            "connectionerror",
            "error 10061",
            "no connection could be made",
            "max number of clients reached",
        )
    )


def _start_paper_ingest_background(
    paper_ingest_service,
    *,
    candidate_limit: int | None,
    min_github_stars: int | None,
    run_id: str,
) -> None:
    Thread(
        target=_run_paper_ingest_background,
        kwargs={
            "paper_ingest_service": paper_ingest_service,
            "candidate_limit": candidate_limit,
            "min_github_stars": min_github_stars,
            "run_id": run_id,
        },
        daemon=True,
    ).start()


def _run_paper_ingest_background(
    paper_ingest_service,
    *,
    candidate_limit: int | None,
    min_github_stars: int | None,
    run_id: str,
) -> None:
    try:
        paper_ingest_service.run_daily_ingest(
            candidate_limit=candidate_limit,
            min_github_stars=min_github_stars,
            run_id=run_id,
        )
    except Exception:
        return


def _start_paper_classification_backfill_background(
    paper_ingest_service,
    *,
    limit: int | None,
    batch_size: int,
    run_id: str,
) -> None:
    Thread(
        target=_run_paper_classification_backfill_background,
        kwargs={
            "paper_ingest_service": paper_ingest_service,
            "limit": limit,
            "batch_size": batch_size,
            "run_id": run_id,
        },
        daemon=True,
    ).start()


def _run_paper_classification_backfill_background(
    paper_ingest_service,
    *,
    limit: int | None,
    batch_size: int,
    run_id: str,
) -> None:
    try:
        paper_ingest_service.backfill_published_classification(
            limit=limit,
            batch_size=batch_size,
            run_id=run_id,
        )
    except Exception:
        return


def _session_user_id(services: ApiServices, helpers: ApiRouteHelpers, session_token: str | None):
    try:
        return services.auth_service_factory().get_session(session_token).user.userId
    except AuthSessionInvalidError:
        return helpers.error(
            status_code=401,
            code="auth_session_required",
            message="valid user session required",
            user_action_required=True,
        )
