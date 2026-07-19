from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.models import ActorContext
from interfaces.services.research_service import (
    ResearchActorInput,
    ResearchAnalyzeInput,
    ResearchAskInput,
    ResearchServiceError,
    bind_research_actor_input,
)


class ResearchAnalyzeRequest(BaseModel):
    paperId: str = Field(min_length=1)
    sourceUrl: str | None = None
    pdfUrl: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
    runId: str | None = None
    userId: str | None = None
    tenantId: str | None = None
    memoryNamespace: str | None = None


class ResearchAskRequest(BaseModel):
    question: str = Field(min_length=1)
    locale: str | None = None
    selection: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
    tenantId: str | None = None
    userId: str | None = None
    memoryNamespace: str | None = None


class ResearchRagAskRequest(BaseModel):
    question: str = Field(min_length=1)
    sectionIndex: int = 0
    limit: int = Field(default=5, ge=1, le=20)
    generate: bool = False
    gated: bool = True
    tenantId: str | None = None
    userId: str | None = None
    memoryNamespace: str | None = None


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/research/papers/analyze")
    def analyze_paper(request: Request, payload: ResearchAnalyzeRequest):
        def call():
            actor = _bound_research_actor(
                request,
                tenant_id=payload.tenantId,
                user_id=payload.userId,
                memory_namespace=payload.memoryNamespace,
            )
            return services.research_service_factory().analyze_paper(
                ResearchAnalyzeInput(
                    paper_id=payload.paperId,
                    source_url=payload.sourceUrl,
                    pdf_url=payload.pdfUrl,
                    run_id=payload.runId,
                    user_id=actor.user_id,
                    metadata=payload.metadata,
                    options=payload.options,
                    tenant_id=actor.tenant_id,
                    memory_namespace=actor.memory_namespace,
                )
            )

        return _service_response(
            helpers,
            call,
        )

    @router.get("/api/v1/research/papers/{paper_id}/analysis")
    def get_analysis(
        request: Request,
        paper_id: str,
        tenantId: str | None = None,
        userId: str | None = None,
        memoryNamespace: str | None = None,
    ):
        def call():
            actor = _bound_research_actor(
                request,
                tenant_id=tenantId,
                user_id=userId,
                memory_namespace=memoryNamespace,
            )
            return services.research_service_factory().get_analysis(
                paper_id,
                actor=actor,
            )

        return _service_response(
            helpers,
            call,
        )

    @router.get("/api/v1/research/papers/{paper_id}/reader")
    def get_reader(
        request: Request,
        paper_id: str,
        tenantId: str | None = None,
        userId: str | None = None,
        memoryNamespace: str | None = None,
    ):
        def call():
            actor = _bound_research_actor(
                request,
                tenant_id=tenantId,
                user_id=userId,
                memory_namespace=memoryNamespace,
            )
            return services.research_service_factory().get_reader(
                paper_id,
                actor=actor,
            )

        return _service_response(
            helpers,
            call,
        )

    @router.post("/api/v1/research/papers/{paper_id}/ask")
    def ask_paper(request: Request, paper_id: str, payload: ResearchAskRequest):
        def call():
            actor = _bound_research_actor(
                request,
                tenant_id=payload.tenantId,
                user_id=payload.userId,
                memory_namespace=payload.memoryNamespace,
            )
            return services.research_service_factory().ask_paper(
                paper_id,
                ResearchAskInput(
                    question=payload.question,
                    locale=payload.locale,
                    selection=payload.selection,
                    options=payload.options,
                    tenant_id=actor.tenant_id,
                    user_id=actor.user_id,
                    memory_namespace=actor.memory_namespace,
                ),
            )

        return _service_response(
            helpers,
            call,
        )

    @router.post("/api/v1/research/papers/{paper_id}/rag-ask")
    def rag_ask_paper(
        request: Request,
        paper_id: str,
        payload: ResearchRagAskRequest,
    ):
        def call():
            actor = _bound_research_actor(
                request,
                tenant_id=payload.tenantId,
                user_id=payload.userId,
                memory_namespace=payload.memoryNamespace,
            )
            return services.research_service_factory().ask_paper(
                paper_id,
                ResearchAskInput(
                    question=payload.question,
                    mode="chunk_rag",
                    section_index=payload.sectionIndex,
                    limit=payload.limit,
                    generate=payload.generate,
                    gated=payload.gated,
                    tenant_id=actor.tenant_id,
                    user_id=actor.user_id,
                    memory_namespace=actor.memory_namespace,
                ),
            )

        return _service_response(
            helpers,
            call,
        )

    @router.get("/api/v1/research/runs/{run_id}/trace")
    def get_trace(
        request: Request,
        run_id: str,
        tenantId: str | None = None,
        userId: str | None = None,
        memoryNamespace: str | None = None,
    ):
        def call():
            actor = _bound_research_actor(
                request,
                tenant_id=tenantId,
                user_id=userId,
                memory_namespace=memoryNamespace,
            )
            return services.research_service_factory().get_trace(
                run_id,
                actor=actor,
            )

        return _service_response(
            helpers,
            call,
        )

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


def _bound_research_actor(
    request: Request,
    *,
    tenant_id: str | None,
    user_id: str | None,
    memory_namespace: str | None,
) -> ResearchActorInput:
    actor = getattr(request.state, "actor_context", None)
    return bind_research_actor_input(
        ResearchActorInput(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_namespace=memory_namespace,
        ),
        actor if isinstance(actor, ActorContext) else None,
    )


__all__ = ["ResearchAnalyzeRequest", "ResearchAskRequest", "ResearchRagAskRequest", "create_router"]
