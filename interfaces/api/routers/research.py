from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator, model_validator

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.models import ActorContext
from interfaces.services.research_service import (
    ResearchActorInput,
    ResearchAnalyzeInput,
    ResearchAskInput,
    ResearchParseInput,
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


class ResearchParseRequest(BaseModel):
    source: str | None = Field(default=None, min_length=1)
    sourceUrl: str | None = Field(default=None, min_length=1)
    sourceType: str | None = Field(default=None, min_length=1)
    contentRef: str | None = Field(default=None, min_length=1)
    runId: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    tenantId: str | None = None
    userId: str | None = None
    memoryNamespace: str | None = None

    @field_validator("source", "sourceUrl", "contentRef", "runId", "tenantId", "userId", "memoryNamespace")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @model_validator(mode="after")
    def _require_source(self) -> "ResearchParseRequest":
        if not (self.source or self.sourceUrl or self.contentRef):
            raise ValueError("source, sourceUrl, or contentRef is required")
        return self


class ResearchCatalogRefreshRequest(BaseModel):
    paperId: str | None = None
    tenantId: str | None = None
    userId: str | None = None
    memoryNamespace: str | None = None


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/research/papers/parse")
    def parse_paper(request: Request, payload: ResearchParseRequest):
        def call():
            actor = _bound_research_actor(
                request,
                tenant_id=payload.tenantId,
                user_id=payload.userId,
                memory_namespace=payload.memoryNamespace,
                require_trusted_actor=True,
            )
            source = payload.source or payload.sourceUrl or payload.contentRef
            if not source:
                raise ValueError("source, sourceUrl, or contentRef is required")
            return services.research_service_factory().parse_paper(
                ResearchParseInput(
                    source=source,
                    source_url=payload.sourceUrl,
                    source_type=payload.sourceType,
                    content_ref=payload.contentRef,
                    run_id=payload.runId,
                    options=payload.options,
                    metadata=payload.metadata,
                    tenant_id=actor.tenant_id,
                    user_id=actor.user_id,
                    memory_namespace=actor.memory_namespace,
                )
            )

        return _service_response(helpers, call)

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

    @router.get("/api/v1/research/papers/{paper_id}/sources")
    def get_sources(
        request: Request,
        paper_id: str,
        tenantId: str | None = None,
        userId: str | None = None,
        memoryNamespace: str | None = None,
    ):
        def call():
            actor = _bound_research_actor(request, tenant_id=tenantId, user_id=userId, memory_namespace=memoryNamespace, require_trusted_actor=True)
            return services.research_service_factory().get_sources(paper_id, actor=actor)

        return _service_response(helpers, call)

    @router.get("/api/v1/research/papers/{paper_id}/document")
    def get_document(
        request: Request,
        paper_id: str,
        tenantId: str | None = None,
        userId: str | None = None,
        memoryNamespace: str | None = None,
    ):
        def call():
            actor = _bound_research_actor(request, tenant_id=tenantId, user_id=userId, memory_namespace=memoryNamespace, require_trusted_actor=True)
            return services.research_service_factory().get_document(paper_id, actor=actor)

        return _service_response(helpers, call)

    @router.get("/api/v1/research/papers/{paper_id}/catalog")
    def get_catalog(
        request: Request,
        paper_id: str,
        tenantId: str | None = None,
        userId: str | None = None,
        memoryNamespace: str | None = None,
    ):
        def call():
            actor = _bound_research_actor(request, tenant_id=tenantId, user_id=userId, memory_namespace=memoryNamespace, require_trusted_actor=True)
            return services.research_service_factory().get_catalog(paper_id, actor=actor)

        return _service_response(helpers, call)

    @router.get("/api/v1/research/papers/{paper_id}/code")
    def get_code(
        request: Request,
        paper_id: str,
        tenantId: str | None = None,
        userId: str | None = None,
        memoryNamespace: str | None = None,
    ):
        def call():
            actor = _bound_research_actor(request, tenant_id=tenantId, user_id=userId, memory_namespace=memoryNamespace, require_trusted_actor=True)
            return services.research_service_factory().get_code(paper_id, actor=actor)

        return _service_response(helpers, call)

    @router.get("/api/v1/research/papers/{paper_id}/benchmarks")
    def get_benchmarks(
        request: Request,
        paper_id: str,
        benchmarkId: str | None = None,
        metricId: str | None = None,
        datasetId: str | None = None,
        datasetVersion: str | None = None,
        split: str | None = None,
        evaluationProtocol: str | None = None,
        tenantId: str | None = None,
        userId: str | None = None,
        memoryNamespace: str | None = None,
    ):
        def call():
            actor = _bound_research_actor(request, tenant_id=tenantId, user_id=userId, memory_namespace=memoryNamespace, require_trusted_actor=True)
            return services.research_service_factory().get_benchmarks(
                paper_id,
                benchmark_id=benchmarkId,
                metric_id=metricId,
                dataset_id=datasetId,
                dataset_version=datasetVersion,
                split=split,
                evaluation_protocol=evaluationProtocol,
                actor=actor,
            )

        return _service_response(helpers, call)

    @router.get("/api/v1/research/catalog/papers")
    def list_catalog_papers(
        request: Request,
        query: str = "",
        limit: int = 50,
        cursor: str | None = None,
        sort: str = "observed_at desc, stable_id asc",
        includeDiagnostics: bool = False,
        tenantId: str | None = None,
        userId: str | None = None,
        memoryNamespace: str | None = None,
    ):
        def call():
            actor = _bound_research_actor(request, tenant_id=tenantId, user_id=userId, memory_namespace=memoryNamespace, require_trusted_actor=True)
            return services.research_service_factory().list_catalog_papers(
                query=query,
                limit=limit,
                cursor=cursor,
                sort=sort,
                include_diagnostics=includeDiagnostics,
                actor=actor,
            )

        return _service_response(helpers, call)

    @router.get("/api/v1/research/catalog/leaderboards")
    def get_leaderboards(
        request: Request,
        benchmarkId: str | None = None,
        metricId: str | None = None,
        datasetId: str | None = None,
        datasetVersion: str | None = None,
        split: str | None = None,
        evaluationProtocol: str | None = None,
        tenantId: str | None = None,
        userId: str | None = None,
        memoryNamespace: str | None = None,
    ):
        def call():
            actor = _bound_research_actor(request, tenant_id=tenantId, user_id=userId, memory_namespace=memoryNamespace, require_trusted_actor=True)
            return services.research_service_factory().get_leaderboards(
                benchmark_id=benchmarkId,
                metric_id=metricId,
                dataset_id=datasetId,
                dataset_version=datasetVersion,
                split=split,
                evaluation_protocol=evaluationProtocol,
                actor=actor,
            )

        return _service_response(helpers, call)

    @router.get("/api/v1/research/artifacts/{artifact_type}/{digest}")
    def get_artifact(
        request: Request,
        artifact_type: str,
        digest: str,
        includePayload: bool = False,
        maxChars: int = 200_000,
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
                require_trusted_actor=True,
            )
            return services.research_service_factory().get_artifact(
                f"artifact://research/{artifact_type}/{digest}",
                include_payload=includePayload,
                max_chars=maxChars,
                actor=actor,
            )

        return _service_response(helpers, call)

    @router.post("/api/v1/research/catalog/refresh")
    def refresh_catalog(request: Request, payload: ResearchCatalogRefreshRequest):
        def call():
            actor = _bound_research_actor(request, tenant_id=payload.tenantId, user_id=payload.userId, memory_namespace=payload.memoryNamespace, require_trusted_actor=True)
            return services.research_service_factory().refresh_catalog(payload.paperId, actor=actor)

        return _service_response(helpers, call)

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
            message=exc.public_message,
            details=exc.details,
            retryable=exc.retryable,
            user_action_required=exc.user_action_required,
        )
    except ValueError:
        return helpers.error(
            status_code=400,
            code="invalid_request",
            message="Research request is invalid",
            user_action_required=True,
        )
    except Exception as exc:  # noqa: BLE001 - public boundary must not leak adapter text
        return helpers.error(
            status_code=500,
            code="research_operation_failed",
            message="Research paper operation failed",
            details={"error_type": type(exc).__name__},
            retryable=True,
        )


def _bound_research_actor(
    request: Request,
    *,
    tenant_id: str | None,
    user_id: str | None,
    memory_namespace: str | None,
    require_trusted_actor: bool = False,
) -> ResearchActorInput:
    actor = getattr(request.state, "actor_context", None)
    if require_trusted_actor and not isinstance(actor, ActorContext):
        if any(value for value in (tenant_id, user_id, memory_namespace)):
            raise ResearchServiceError(
                "forbidden",
                "authenticated actor context is required for scoped Research Catalog access",
                status_code=403,
                user_action_required=True,
            )
    return bind_research_actor_input(
        ResearchActorInput(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_namespace=memory_namespace,
        ),
        actor if isinstance(actor, ActorContext) else None,
    )


__all__ = [
    "ResearchAnalyzeRequest",
    "ResearchAskRequest",
    "ResearchRagAskRequest",
    "ResearchParseRequest",
    "ResearchCatalogRefreshRequest",
    "create_router",
]
