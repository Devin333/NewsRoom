from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.services.research_service import ResearchAnalyzeInput, ResearchAskInput, ResearchServiceError


class ResearchAnalyzeRequest(BaseModel):
    paperId: str = Field(min_length=1)
    sourceUrl: str | None = None
    pdfUrl: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
    runId: str | None = None
    userId: str | None = None


class ResearchAskRequest(BaseModel):
    question: str = Field(min_length=1)
    locale: str | None = None
    selection: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)


class ResearchRagAskRequest(BaseModel):
    question: str = Field(min_length=1)
    sectionIndex: int = 0
    limit: int = Field(default=5, ge=1, le=20)
    generate: bool = False


# Process-wide singleton: the chunk-RAG service holds the resident reranker.
_RAG_SERVICE = None


def _rag_service():
    global _RAG_SERVICE
    if _RAG_SERVICE is None:
        from interfaces.services.paper_rag_service import PaperRagApplicationService
        _RAG_SERVICE = PaperRagApplicationService()
    return _RAG_SERVICE


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/research/papers/analyze")
    def analyze_paper(request: ResearchAnalyzeRequest):
        return _service_response(
            helpers,
            lambda: services.research_service_factory().analyze_paper(
                ResearchAnalyzeInput(
                    paper_id=request.paperId,
                    source_url=request.sourceUrl,
                    pdf_url=request.pdfUrl,
                    run_id=request.runId,
                    user_id=request.userId,
                    metadata=request.metadata,
                    options=request.options,
                )
            ),
        )

    @router.get("/api/v1/research/papers/{paper_id}/analysis")
    def get_analysis(paper_id: str):
        return _service_response(helpers, lambda: services.research_service_factory().get_analysis(paper_id))

    @router.get("/api/v1/research/papers/{paper_id}/reader")
    def get_reader(paper_id: str):
        return _service_response(helpers, lambda: services.research_service_factory().get_reader(paper_id))

    @router.post("/api/v1/research/papers/{paper_id}/ask")
    def ask_paper(paper_id: str, request: ResearchAskRequest):
        return _service_response(
            helpers,
            lambda: services.research_service_factory().ask_paper(
                paper_id,
                ResearchAskInput(
                    question=request.question,
                    locale=request.locale,
                    selection=request.selection,
                    options=request.options,
                ),
            ),
        )

    @router.post("/api/v1/research/papers/{paper_id}/rag-ask")
    def rag_ask_paper(paper_id: str, request: ResearchRagAskRequest):
        # chunk-based RAG (vector recall → rerank → position-aware → parent expansion),
        # distinct from the legacy /ask endpoint.
        return _service_response(
            helpers,
            lambda: _rag_service().rag_ask(
                paper_id,
                request.question,
                section_index=request.sectionIndex,
                limit=request.limit,
                generate=request.generate,
            ),
        )

    @router.get("/api/v1/research/runs/{run_id}/trace")
    def get_trace(run_id: str):
        return _service_response(helpers, lambda: services.research_service_factory().get_trace(run_id))

    return router


def _service_response(helpers: ApiRouteHelpers, call):
    try:
        return helpers.success(call())
    except ResearchServiceError as exc:
        return helpers.error(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
            retryable=exc.retryable,
            user_action_required=exc.user_action_required,
        )
    except ValueError as exc:
        return helpers.error(status_code=400, code="invalid_request", message=str(exc), user_action_required=True)


__all__ = ["ResearchAnalyzeRequest", "ResearchAskRequest", "ResearchRagAskRequest", "create_router"]
