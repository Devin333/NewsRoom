from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Header, Query

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.services.auth_service import AuthSessionInvalidError
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
