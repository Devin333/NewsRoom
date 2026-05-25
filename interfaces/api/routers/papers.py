from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Query

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.services.paper_service import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
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

    @router.post("/api/v1/papers/{paper_id}/summary")
    def summarize_paper(paper_id: str, locale: str = Query("en", pattern="^(zh|en)$")):
        try:
            summary = services.papers_service_factory().get_or_generate_summary(
                paper_id,
                locale=locale,  # type: ignore[arg-type]
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
