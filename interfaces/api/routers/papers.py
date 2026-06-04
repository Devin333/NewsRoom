from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from threading import Thread
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field
from fastapi import APIRouter, Header, Query
from fastapi.responses import FileResponse

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.services.auth_service import AuthSessionInvalidError
from interfaces.services.paper_ingest_service import PAPER_INGEST_TASK_TYPE
from interfaces.services.paper_ops_run_repository import PaperOpsRunRepository, new_ops_run, ops_run_from_result
from interfaces.services.paper_visual_compiler_service import (
    PAPER_VISUAL_COMPILE_BACKFILL_TASK_TYPE,
    PAPER_VISUAL_COMPILE_TASK_TYPE,
)
from interfaces.services.paper_reader_interaction_service import ReaderSelectionNotFoundError
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

logger = logging.getLogger(__name__)
PAPER_CLASSIFICATION_BACKFILL_TASK_TYPE = "papers.classification_backfill"
PAPER_CITATION_BACKFILL_TASK_TYPE = "papers.citation_backfill"


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


class PaperVisualCompileRequest(BaseModel):
    force: bool = False
    runId: str | None = Field(default=None, min_length=1, max_length=120)


class PaperVisualCompileBackfillTriggerRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=100_000)
    force: bool = False
    runId: str | None = Field(default=None, min_length=1, max_length=120)


class PaperClassificationBackfillTriggerRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=100_000)
    batchSize: int = Field(default=25, ge=1, le=500)
    runId: str | None = Field(default=None, min_length=1, max_length=120)


class PaperCitationBackfillTriggerRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=100_000)
    batchSize: int = Field(default=50, ge=1, le=200)
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


class PaperReaderBlockTargetRequest(BaseModel):
    targetType: str = Field(..., pattern="^(text_selection|paragraph|figure|table|equation)$")
    blockId: str | None = Field(default=None, max_length=200)
    assetId: str | None = Field(default=None, max_length=200)
    sectionId: str | None = Field(default=None, max_length=200)
    paragraphId: str | None = Field(default=None, max_length=200)
    pageNumber: int | None = Field(default=None, ge=1)
    sourceBox: dict[str, float] | None = None
    metadata: dict[str, Any] | None = None


class PaperReaderEventRequest(BaseModel):
    type: str = Field(
        ...,
        pattern=(
            "^(selection_created|selection_discarded|selection_updated|note_updated|"
            "explanation_generated|example_generated|confusion_marked|confusion_unmarked|"
            "reader_settings_changed|drawer_resized|toc_navigated|reader_progress_sampled|"
            "figure_explanation_requested|figure_explanation_generated|"
            "table_explanation_requested|table_explanation_generated)$"
        ),
    )
    selectionId: str | None = Field(default=None, max_length=200)
    target: PaperReaderBlockTargetRequest | None = None
    sectionId: str | None = Field(default=None, max_length=200)
    paragraphId: str | None = Field(default=None, max_length=200)
    selectedText: str | None = Field(default=None, max_length=8000)
    surroundingText: str | None = Field(default=None, max_length=16000)
    payload: dict[str, Any] | None = None


class PaperReaderSelectionCreateRequest(BaseModel):
    selectionId: str | None = Field(default=None, max_length=200)
    target: PaperReaderBlockTargetRequest | None = None
    sectionId: str | None = Field(default=None, max_length=200)
    paragraphId: str | None = Field(default=None, max_length=200)
    selectedText: str | None = Field(default=None, max_length=8000)
    surroundingText: str | None = Field(default=None, max_length=16000)
    payload: dict[str, Any] | None = None


class PaperReaderSelectionPatchRequest(BaseModel):
    noteText: str | None = Field(default=None, max_length=12000)
    explained: bool | None = None
    exampled: bool | None = None
    confused: bool | None = None
    explainQuestion: str | None = Field(default=None, max_length=2000)
    exampleQuestion: str | None = Field(default=None, max_length=2000)
    question: str | None = Field(default=None, max_length=2000)
    answer: str | None = Field(default=None, max_length=20000)
    example: str | None = Field(default=None, max_length=20000)


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
        ops = dict(services.paper_ingest_service_factory().get_ops_state(limit=limit))
        ops["localRuns"] = PaperOpsRunRepository().list_runs(limit=limit)
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
            operation_key = _local_operation_key(
                PAPER_INGEST_TASK_TYPE,
                candidateLimit=request.candidateLimit,
                minGithubStars=request.minGithubStars,
            )
            queued, local_run = _try_queue_local_ops_run(
                run_id=run_id,
                task_type=PAPER_INGEST_TASK_TYPE,
                operation_key=operation_key,
            )
            resolved_run_id = str(local_run.get("runId") or run_id)
            if queued:
                _start_paper_ingest_background(
                    services.paper_ingest_service_factory,
                    services.paper_visual_compiler_service_factory,
                    candidate_limit=request.candidateLimit,
                    min_github_stars=request.minGithubStars,
                    run_id=resolved_run_id,
                )
            return helpers.success(
                {
                    "enqueued": {
                        "message_id": "local-background",
                        "task_id": f"{resolved_run_id}:local-background",
                        "task_type": PAPER_INGEST_TASK_TYPE,
                        "queue_name": "local:background",
                        "status": str(local_run.get("status") or "queued"),
                        "run_id": resolved_run_id,
                        "mode": "local_background",
                        "fallback_reason": "worker_queue_unavailable",
                        "already_running": not queued,
                    }
                }
            )
        return helpers.success({"enqueued": result.to_dict()})

    @router.post("/api/v1/papers/ops/classification-backfill/trigger")
    def trigger_paper_classification_backfill(request: PaperClassificationBackfillTriggerRequest):
        run_id = request.runId or f"paper-classification-backfill-local-{uuid4().hex[:12]}"
        queued, local_run = _try_queue_local_ops_run(
            run_id=run_id,
            task_type=PAPER_CLASSIFICATION_BACKFILL_TASK_TYPE,
            operation_key=_local_operation_key(
                PAPER_CLASSIFICATION_BACKFILL_TASK_TYPE,
                limit=request.limit,
                batchSize=request.batchSize,
            ),
        )
        resolved_run_id = str(local_run.get("runId") or run_id)
        if queued:
            _start_paper_classification_backfill_background(
                services.paper_ingest_service_factory,
                limit=request.limit,
                batch_size=request.batchSize,
                run_id=resolved_run_id,
            )
        return helpers.success(
            {
                "backfill": {
                    "runId": resolved_run_id,
                    "status": str(local_run.get("status") or "queued"),
                    "mode": "local_background",
                    "alreadyRunning": not queued,
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

    @router.post("/api/v1/papers/ops/citation-backfill/trigger")
    def trigger_paper_citation_backfill(request: PaperCitationBackfillTriggerRequest):
        run_id = request.runId or f"paper-citation-backfill-local-{uuid4().hex[:12]}"
        queued, local_run = _try_queue_local_ops_run(
            run_id=run_id,
            task_type=PAPER_CITATION_BACKFILL_TASK_TYPE,
            operation_key=_local_operation_key(
                PAPER_CITATION_BACKFILL_TASK_TYPE,
                limit=request.limit,
                batchSize=request.batchSize,
            ),
        )
        resolved_run_id = str(local_run.get("runId") or run_id)
        if queued:
            _start_paper_citation_backfill_background(
                services.paper_ingest_service_factory,
                limit=request.limit,
                batch_size=request.batchSize,
                run_id=resolved_run_id,
            )
        return helpers.success(
            {
                "backfill": {
                    "runId": resolved_run_id,
                    "status": str(local_run.get("status") or "queued"),
                    "mode": "local_background",
                    "alreadyRunning": not queued,
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

    @router.post("/api/v1/papers/ops/visual-compile/trigger")
    def trigger_paper_visual_compile_backfill(request: PaperVisualCompileBackfillTriggerRequest):
        try:
            result = services.worker_service_factory().enqueue_paper_visual_compile_backfill(
                limit=request.limit,
                force=request.force,
                run_id=request.runId,
            )
        except ValueError as exc:
            return helpers.error(
                status_code=400,
                code="paper_visual_compile_backfill_invalid",
                message=str(exc),
                user_action_required=True,
            )
        except Exception as exc:
            if not _is_worker_queue_unavailable(exc):
                return helpers.error(
                    status_code=503,
                    code="paper_visual_compile_backfill_unavailable",
                    message=str(exc),
                    retryable=True,
                )
            run_id = request.runId or f"paper-visual-compile-backfill-local-{uuid4().hex[:12]}"
            queued, local_run = _try_queue_local_ops_run(
                run_id=run_id,
                task_type=PAPER_VISUAL_COMPILE_BACKFILL_TASK_TYPE,
                operation_key=_local_operation_key(
                    PAPER_VISUAL_COMPILE_BACKFILL_TASK_TYPE,
                    limit=request.limit,
                    force=request.force,
                ),
            )
            resolved_run_id = str(local_run.get("runId") or run_id)
            if queued:
                _start_paper_visual_compile_backfill_background(
                    services.paper_visual_compiler_service_factory,
                    limit=request.limit,
                    force=request.force,
                    run_id=resolved_run_id,
                )
            return helpers.success(
                {
                    "enqueued": {
                        "message_id": "local-background",
                        "task_id": f"{resolved_run_id}:local-background",
                        "task_type": PAPER_VISUAL_COMPILE_BACKFILL_TASK_TYPE,
                        "queue_name": "local:background",
                        "status": str(local_run.get("status") or "queued"),
                        "run_id": resolved_run_id,
                        "force": request.force,
                        "limit": request.limit,
                        "mode": "local_background",
                        "fallback_reason": "worker_queue_unavailable",
                        "already_running": not queued,
                    }
                }
            )
        return helpers.success({"enqueued": result.to_dict()})

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

    @router.get("/api/v1/papers/{paper_id}/document")
    def get_paper_document(paper_id: str):
        try:
            payload = services.paper_visual_compiler_service_factory().get_document_payload(paper_id)
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
        return helpers.success(dict(payload))

    @router.get("/api/v1/papers/{paper_id}/compile-status")
    def get_paper_compile_status(paper_id: str):
        try:
            status = services.paper_visual_compiler_service_factory().get_compile_status(paper_id)
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
        return helpers.success({"status": status.to_dict()})

    @router.post("/api/v1/papers/{paper_id}/compile")
    def trigger_paper_visual_compile(paper_id: str, request: PaperVisualCompileRequest):
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
        try:
            result = services.worker_service_factory().enqueue_paper_visual_compile(
                paper_id=paper.id,
                force=request.force,
                run_id=request.runId,
            )
        except ValueError as exc:
            return helpers.error(
                status_code=400,
                code="paper_visual_compile_invalid",
                message=str(exc),
                user_action_required=True,
            )
        except Exception as exc:
            if not _is_worker_queue_unavailable(exc):
                return helpers.error(
                    status_code=503,
                    code="paper_visual_compile_trigger_unavailable",
                    message=str(exc),
                    retryable=True,
                )
            run_id = request.runId or f"paper-visual-compile-local-{uuid4().hex[:12]}"
            queued, local_run = _try_queue_local_ops_run(
                run_id=run_id,
                task_type=PAPER_VISUAL_COMPILE_TASK_TYPE,
                paper_id=paper.id,
                operation_key=_local_operation_key(
                    PAPER_VISUAL_COMPILE_TASK_TYPE,
                    paperId=paper.id,
                    force=request.force,
                ),
            )
            resolved_run_id = str(local_run.get("runId") or run_id)
            if queued:
                _start_paper_visual_compile_background(
                    services.paper_visual_compiler_service_factory,
                    paper_id=paper.id,
                    force=request.force,
                    run_id=resolved_run_id,
                )
            return helpers.success(
                {
                    "enqueued": {
                        "message_id": "local-background",
                        "task_id": f"{resolved_run_id}:local-background",
                        "task_type": PAPER_VISUAL_COMPILE_TASK_TYPE,
                        "queue_name": "local:background",
                        "status": str(local_run.get("status") or "queued"),
                        "paper_id": paper.id,
                        "run_id": resolved_run_id,
                        "mode": "local_background",
                        "fallback_reason": "worker_queue_unavailable",
                        "already_running": not queued,
                    }
                }
            )
        return helpers.success({"enqueued": result.to_dict()})

    @router.get("/api/v1/papers/{paper_id}/assets/{asset_id}")
    def get_paper_visual_asset(paper_id: str, asset_id: str):
        try:
            resolved = services.paper_visual_compiler_service_factory().resolve_asset(paper_id, asset_id)
        except PaperNotFoundError:
            return helpers.error(
                status_code=404,
                code="paper_not_found",
                message="paper was not found",
                user_action_required=True,
            )
        if resolved is None:
            return helpers.error(
                status_code=404,
                code="paper_asset_not_found",
                message="paper visual asset was not found",
                user_action_required=True,
            )
        path, media_type = resolved
        return FileResponse(path, media_type=media_type)

    @router.get("/api/v1/papers/{paper_id}/source-preview")
    def get_paper_source_preview(
        paper_id: str,
        page: int = Query(..., ge=1),
        bbox: str = Query(..., min_length=1, max_length=200),
    ):
        parsed_bbox = _parse_bbox_query(bbox)
        if parsed_bbox is None:
            return helpers.error(
                status_code=400,
                code="paper_source_preview_bbox_invalid",
                message="bbox must be x0,y0,x1,y1 or a JSON object with x0/y0/x1/y1",
                user_action_required=True,
            )
        try:
            path = services.paper_visual_compiler_service_factory().source_preview(
                paper_id,
                page_number=page,
                bbox=parsed_bbox,
            )
        except PaperNotFoundError:
            return helpers.error(
                status_code=404,
                code="paper_not_found",
                message="paper was not found",
                user_action_required=True,
            )
        except Exception as exc:
            return helpers.error(
                status_code=400,
                code="paper_source_preview_failed",
                message=str(exc),
                user_action_required=True,
            )
        if path is None:
            return helpers.error(
                status_code=404,
                code="paper_source_preview_not_found",
                message="paper source preview was not found",
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

    @router.post("/api/v1/papers/{paper_id}/reader/events")
    def record_paper_reader_event(
        paper_id: str,
        request: PaperReaderEventRequest,
        x_newsroom_session: str | None = Header(default=None),
    ):
        user_id = _session_user_id(services, helpers, x_newsroom_session)
        if not isinstance(user_id, str):
            return user_id
        try:
            result = services.paper_reader_interaction_service_factory().record_event(
                user_id=user_id,
                paper_id=paper_id,
                payload=request.model_dump(exclude_none=True),
            )
        except ValueError as exc:
            return helpers.error(
                status_code=400,
                code="paper_reader_event_invalid",
                message=str(exc),
                user_action_required=True,
            )
        payload = result.to_dict()
        payload["feedbackIngest"] = _enqueue_reader_feedback_best_effort(services, paper_id=paper_id, user_id=user_id)
        return helpers.success(payload)

    @router.post("/api/v1/papers/{paper_id}/reader/selections")
    def create_paper_reader_selection(
        paper_id: str,
        request: PaperReaderSelectionCreateRequest,
        x_newsroom_session: str | None = Header(default=None),
    ):
        user_id = _session_user_id(services, helpers, x_newsroom_session)
        if not isinstance(user_id, str):
            return user_id
        try:
            result = services.paper_reader_interaction_service_factory().create_selection(
                user_id=user_id,
                paper_id=paper_id,
                payload=request.model_dump(exclude_none=True),
            )
        except ValueError as exc:
            return helpers.error(
                status_code=400,
                code="paper_reader_selection_invalid",
                message=str(exc),
                user_action_required=True,
            )
        payload = result.to_dict()
        payload["feedbackIngest"] = _enqueue_reader_feedback_best_effort(services, paper_id=paper_id, user_id=user_id)
        return helpers.success(payload)

    @router.patch("/api/v1/papers/{paper_id}/reader/selections/{selection_id}")
    def patch_paper_reader_selection(
        paper_id: str,
        selection_id: str,
        request: PaperReaderSelectionPatchRequest,
        x_newsroom_session: str | None = Header(default=None),
    ):
        user_id = _session_user_id(services, helpers, x_newsroom_session)
        if not isinstance(user_id, str):
            return user_id
        try:
            result = services.paper_reader_interaction_service_factory().patch_selection(
                user_id=user_id,
                paper_id=paper_id,
                selection_id=selection_id,
                patch=request.model_dump(exclude_none=True),
            )
        except ReaderSelectionNotFoundError:
            return helpers.error(
                status_code=404,
                code="paper_reader_selection_not_found",
                message="paper reader selection was not found",
                user_action_required=True,
            )
        except ValueError as exc:
            return helpers.error(
                status_code=400,
                code="paper_reader_selection_invalid",
                message=str(exc),
                user_action_required=True,
            )
        payload = result.to_dict()
        payload["feedbackIngest"] = _enqueue_reader_feedback_best_effort(services, paper_id=paper_id, user_id=user_id)
        return helpers.success(payload)

    @router.get("/api/v1/papers/{paper_id}/reader/materials")
    def get_paper_reader_materials(
        paper_id: str,
        x_newsroom_session: str | None = Header(default=None),
    ):
        user_id = _session_user_id(services, helpers, x_newsroom_session)
        if not isinstance(user_id, str):
            return user_id
        summary = services.paper_reader_interaction_service_factory().material_summary(
            user_id=user_id,
            paper_id=paper_id,
        )
        return helpers.success({"materials": summary.to_dict()})

    @router.delete("/api/v1/papers/{paper_id}/reader/materials")
    def delete_paper_reader_materials(
        paper_id: str,
        x_newsroom_session: str | None = Header(default=None),
    ):
        user_id = _session_user_id(services, helpers, x_newsroom_session)
        if not isinstance(user_id, str):
            return user_id
        deleted = services.paper_reader_interaction_service_factory().delete_user_paper_materials(
            user_id=user_id,
            paper_id=paper_id,
        )
        return helpers.success({"deleted": deleted})

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
    paper_ingest_service_factory,
    paper_visual_compiler_service_factory,
    *,
    candidate_limit: int | None,
    min_github_stars: int | None,
    run_id: str,
) -> None:
    Thread(
        target=_run_paper_ingest_background,
        kwargs={
            "paper_ingest_service_factory": paper_ingest_service_factory,
            "paper_visual_compiler_service_factory": paper_visual_compiler_service_factory,
            "candidate_limit": candidate_limit,
            "min_github_stars": min_github_stars,
            "run_id": run_id,
        },
        daemon=True,
    ).start()


def _run_paper_ingest_background(
    paper_ingest_service_factory,
    paper_visual_compiler_service_factory,
    *,
    candidate_limit: int | None,
    min_github_stars: int | None,
    run_id: str,
) -> None:
    paper_ingest_service = None
    try:
        _record_local_ops_run(run_id=run_id, task_type=PAPER_INGEST_TASK_TYPE, status="running")
        paper_ingest_service = paper_ingest_service_factory()
        paper_visual_compiler_service = paper_visual_compiler_service_factory()
        result = paper_ingest_service.run_daily_ingest(
            candidate_limit=candidate_limit,
            min_github_stars=min_github_stars,
            run_id=run_id,
        )
        payload = result.to_dict() if hasattr(result, "to_dict") else {}
        if not isinstance(payload, dict):
            _record_local_ops_run(
                run_id=run_id,
                task_type=PAPER_INGEST_TASK_TYPE,
                status="failed",
                error=RuntimeError("paper ingest returned an invalid result payload"),
            )
            return
        for paper_id in payload.get("publishedPaperIds") or []:
            if isinstance(paper_id, str) and paper_id.strip():
                try:
                    paper_visual_compiler_service.compile_paper(paper_id, force=False, run_id=run_id)
                except Exception as exc:
                    logger.exception("paper ingest background visual compile failed", extra={"run_id": run_id, "paper_id": paper_id})
                    _record_visual_background_failure(
                        paper_visual_compiler_service,
                        paper_id=paper_id,
                        run_id=run_id,
                        task_type=PAPER_VISUAL_COMPILE_TASK_TYPE,
                        error=exc,
                    )
                    continue
        _record_local_ops_run(run_id=run_id, task_type=PAPER_INGEST_TASK_TYPE, status="succeeded")
    except Exception as exc:
        logger.exception("paper ingest background failed", extra={"run_id": run_id})
        _record_local_ops_run(run_id=run_id, task_type=PAPER_INGEST_TASK_TYPE, status="failed", error=exc)
        if paper_ingest_service is not None:
            _record_ingest_background_failure(
                paper_ingest_service,
                run_id=run_id,
                task_type=PAPER_INGEST_TASK_TYPE,
                step="background_ingest",
                error=exc,
            )


def _start_paper_classification_backfill_background(
    paper_ingest_service_factory,
    *,
    limit: int | None,
    batch_size: int,
    run_id: str,
) -> None:
    Thread(
        target=_run_paper_classification_backfill_background,
        kwargs={
            "paper_ingest_service_factory": paper_ingest_service_factory,
            "limit": limit,
            "batch_size": batch_size,
            "run_id": run_id,
        },
        daemon=True,
    ).start()


def _run_paper_classification_backfill_background(
    paper_ingest_service_factory,
    *,
    limit: int | None,
    batch_size: int,
    run_id: str,
) -> None:
    paper_ingest_service = None
    try:
        _record_local_ops_run(run_id=run_id, task_type=PAPER_CLASSIFICATION_BACKFILL_TASK_TYPE, status="running")
        paper_ingest_service = paper_ingest_service_factory()
        result = paper_ingest_service.backfill_published_classification(
            limit=limit,
            batch_size=batch_size,
            run_id=run_id,
        )
        _record_local_ops_run_result(
            run_id=run_id,
            task_type=PAPER_CLASSIFICATION_BACKFILL_TASK_TYPE,
            status="succeeded",
            result=result,
        )
    except Exception as exc:
        logger.exception("paper classification backfill background failed", extra={"run_id": run_id})
        _record_local_ops_run(run_id=run_id, task_type=PAPER_CLASSIFICATION_BACKFILL_TASK_TYPE, status="failed", error=exc)
        if paper_ingest_service is not None:
            _record_ingest_background_failure(
                paper_ingest_service,
                run_id=run_id,
                task_type=PAPER_CLASSIFICATION_BACKFILL_TASK_TYPE,
                step="classification_backfill",
                error=exc,
            )


def _start_paper_citation_backfill_background(
    paper_ingest_service_factory,
    *,
    limit: int | None,
    batch_size: int,
    run_id: str,
) -> None:
    Thread(
        target=_run_paper_citation_backfill_background,
        kwargs={
            "paper_ingest_service_factory": paper_ingest_service_factory,
            "limit": limit,
            "batch_size": batch_size,
            "run_id": run_id,
        },
        daemon=True,
    ).start()


def _run_paper_citation_backfill_background(
    paper_ingest_service_factory,
    *,
    limit: int | None,
    batch_size: int,
    run_id: str,
) -> None:
    paper_ingest_service = None
    try:
        _record_local_ops_run(run_id=run_id, task_type=PAPER_CITATION_BACKFILL_TASK_TYPE, status="running")
        paper_ingest_service = paper_ingest_service_factory()
        result = paper_ingest_service.backfill_published_citations(
            limit=limit,
            batch_size=batch_size,
            run_id=run_id,
        )
        _record_local_ops_run_result(
            run_id=run_id,
            task_type=PAPER_CITATION_BACKFILL_TASK_TYPE,
            status="succeeded",
            result=result,
        )
    except Exception as exc:
        logger.exception("paper citation backfill background failed", extra={"run_id": run_id})
        _record_local_ops_run(run_id=run_id, task_type=PAPER_CITATION_BACKFILL_TASK_TYPE, status="failed", error=exc)
        if paper_ingest_service is not None:
            _record_ingest_background_failure(
                paper_ingest_service,
                run_id=run_id,
                task_type=PAPER_CITATION_BACKFILL_TASK_TYPE,
                step="citation_backfill",
                error=exc,
            )


def _start_paper_visual_compile_background(
    paper_visual_compiler_service_factory,
    *,
    paper_id: str,
    force: bool,
    run_id: str,
) -> None:
    Thread(
        target=_run_paper_visual_compile_background,
        kwargs={
            "paper_visual_compiler_service_factory": paper_visual_compiler_service_factory,
            "paper_id": paper_id,
            "force": force,
            "run_id": run_id,
        },
        daemon=True,
    ).start()


def _run_paper_visual_compile_background(
    paper_visual_compiler_service_factory,
    *,
    paper_id: str,
    force: bool,
    run_id: str,
) -> None:
    paper_visual_compiler_service = None
    try:
        _record_local_ops_run(run_id=run_id, task_type=PAPER_VISUAL_COMPILE_TASK_TYPE, status="running", paper_id=paper_id)
        paper_visual_compiler_service = paper_visual_compiler_service_factory()
        paper_visual_compiler_service.compile_paper(paper_id, force=force, run_id=run_id)
        _record_local_ops_run(run_id=run_id, task_type=PAPER_VISUAL_COMPILE_TASK_TYPE, status="succeeded", paper_id=paper_id)
    except Exception as exc:
        logger.exception("paper visual compile background failed", extra={"run_id": run_id, "paper_id": paper_id})
        _record_local_ops_run(run_id=run_id, task_type=PAPER_VISUAL_COMPILE_TASK_TYPE, status="failed", paper_id=paper_id, error=exc)
        if paper_visual_compiler_service is not None:
            _record_visual_background_failure(
                paper_visual_compiler_service,
                paper_id=paper_id,
                run_id=run_id,
                task_type=PAPER_VISUAL_COMPILE_TASK_TYPE,
                error=exc,
            )


def _start_paper_visual_compile_backfill_background(
    paper_visual_compiler_service_factory,
    *,
    limit: int | None,
    force: bool,
    run_id: str,
) -> None:
    Thread(
        target=_run_paper_visual_compile_backfill_background,
        kwargs={
            "paper_visual_compiler_service_factory": paper_visual_compiler_service_factory,
            "limit": limit,
            "force": force,
            "run_id": run_id,
        },
        daemon=True,
    ).start()


def _run_paper_visual_compile_backfill_background(
    paper_visual_compiler_service_factory,
    *,
    limit: int | None,
    force: bool,
    run_id: str,
) -> None:
    paper_visual_compiler_service = None
    try:
        _record_local_ops_run(run_id=run_id, task_type=PAPER_VISUAL_COMPILE_BACKFILL_TASK_TYPE, status="running")
        paper_visual_compiler_service = paper_visual_compiler_service_factory()
        plan = paper_visual_compiler_service.plan_visual_compile_backfill(
            limit=limit,
            force=force,
            run_id=run_id,
        )
        errors: list[Exception] = []
        for candidate in plan.candidates:
            try:
                paper_visual_compiler_service.compile_paper(candidate.paper_id, force=force, run_id=run_id)
            except Exception as exc:
                errors.append(exc)
                logger.exception(
                    "paper visual compile backfill candidate failed",
                    extra={"run_id": run_id, "paper_id": candidate.paper_id},
                )
                _record_visual_background_failure(
                    paper_visual_compiler_service,
                    paper_id=candidate.paper_id,
                    run_id=run_id,
                    task_type=PAPER_VISUAL_COMPILE_BACKFILL_TASK_TYPE,
                    error=exc,
                )
        if errors:
            _record_local_ops_run(
                run_id=run_id,
                task_type=PAPER_VISUAL_COMPILE_BACKFILL_TASK_TYPE,
                status="partial_failed",
                error=RuntimeError(f"{len(errors)} paper visual compile backfill candidate(s) failed"),
            )
        else:
            _record_local_ops_run(run_id=run_id, task_type=PAPER_VISUAL_COMPILE_BACKFILL_TASK_TYPE, status="succeeded")
    except Exception as exc:
        logger.exception("paper visual compile backfill background failed", extra={"run_id": run_id})
        _record_local_ops_run(run_id=run_id, task_type=PAPER_VISUAL_COMPILE_BACKFILL_TASK_TYPE, status="failed", error=exc)


def _record_ingest_background_failure(
    paper_ingest_service,
    *,
    run_id: str,
    task_type: str,
    step: str,
    error: Exception,
) -> None:
    recorder = getattr(paper_ingest_service, "record_background_failure", None)
    if not callable(recorder):
        return
    try:
        recorder(run_id=run_id, task_type=task_type, step=step, error=error)
    except Exception:
        logger.exception("paper ingest background failure recording failed", extra={"run_id": run_id, "task_type": task_type})


def _try_queue_local_ops_run(
    *,
    run_id: str,
    task_type: str,
    paper_id: str | None = None,
    operation_key: str | None = None,
) -> tuple[bool, Mapping[str, Any]]:
    queued_run = new_ops_run(
        run_id=run_id,
        task_type=task_type,
        status="queued",
        paper_id=paper_id,
        operation_key=operation_key,
    )
    try:
        return PaperOpsRunRepository().try_enqueue_run(queued_run)
    except Exception:
        logger.exception("paper local ops run queue recording failed", extra={"run_id": run_id, "task_type": task_type})
        return True, queued_run


def _record_local_ops_run(
    *,
    run_id: str,
    task_type: str,
    status: str,
    paper_id: str | None = None,
    error: Exception | None = None,
) -> None:
    try:
        PaperOpsRunRepository().record_run(
            new_ops_run(
                run_id=run_id,
                task_type=task_type,
                status=status,
                paper_id=paper_id,
                error=error,
            )
        )
    except Exception:
        logger.exception("paper local ops run recording failed", extra={"run_id": run_id, "task_type": task_type, "status": status})


def _record_local_ops_run_result(
    *,
    run_id: str,
    task_type: str,
    status: str,
    result: Any,
) -> None:
    try:
        PaperOpsRunRepository().record_run(
            ops_run_from_result(
                run_id=run_id,
                task_type=task_type,
                status=status,
                result=result,
            )
        )
    except Exception:
        logger.exception("paper local ops run result recording failed", extra={"run_id": run_id, "task_type": task_type, "status": status})


def _local_operation_key(task_type: str, **params: Any) -> str:
    payload = {key: value for key, value in params.items() if value is not None}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"{task_type}:{encoded}"


def _record_visual_background_failure(
    paper_visual_compiler_service,
    *,
    paper_id: str,
    run_id: str,
    task_type: str,
    error: Exception,
) -> None:
    recorder = getattr(paper_visual_compiler_service, "record_background_failure", None)
    if not callable(recorder):
        return
    try:
        recorder(paper_id=paper_id, run_id=run_id, task_type=task_type, error=error)
    except Exception:
        logger.exception("paper visual background failure recording failed", extra={"run_id": run_id, "paper_id": paper_id})


def _enqueue_reader_feedback_best_effort(services: ApiServices, *, paper_id: str, user_id: str) -> dict[str, Any]:
    try:
        result = services.worker_service_factory().enqueue_paper_reader_feedback(
            paper_id=paper_id,
            user_id=user_id,
        )
    except Exception as exc:
        return {
            "queued": False,
            "reason": "worker_queue_unavailable" if _is_worker_queue_unavailable(exc) else type(exc).__name__,
        }
    return {"queued": True, "enqueued": result.to_dict()}


def _parse_bbox_query(value: str) -> tuple[float, float, float, float] | None:
    text = value.strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        coords = [_float(payload.get(key)) for key in ("x0", "y0", "x1", "y1")]
    else:
        coords = [_float(part) for part in text.split(",")]
    if len(coords) != 4 or any(item is None for item in coords):
        return None
    x0, y0, x1, y1 = coords
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)  # type: ignore[return-value]


def _float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


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
