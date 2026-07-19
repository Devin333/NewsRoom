from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from threading import Condition, Lock
from typing import Any

from business.research.application.analyze_paper import AnalyzePaperUseCase
from business.research.application.ask_paper import AskPaperUseCase
from business.research.application.bounded_document_rag import (
    BoundedDocumentRAGRuntime,
)
from business.research.application.single_paper_runtime import (
    ResearchAnalysisResult,
    ResearchSinglePaperRuntime,
)
from business.research.document.chunk_storage import PaperChunkStoreAdapter
from business.research.document.cascade_parser import (
    CascadeDocumentParser,
    PyMuPDFTextDocumentParser,
)
from business.research.document.latex_compiler import ArxivLatexDocumentCompiler
from business.research.document.marker_pdf_parser import MarkerPdfDocumentParser
from business.research.document.mineru_pdf_parser import MinerUPdfDocumentParser
from business.research.ports.chunk_store import ChunkStorePort
from framework.llm.clients.openai_compatible import (
    LLMRetryPolicy,
    OpenAICompatibleClient,
    OpenAICompatibleConfig,
)
from framework.harness.ports import HarnessTransitionPort
from infrastructure.external.sources.arxiv import (
    ArxivConnector,
    ArxivSourceConnector,
)
from infrastructure.external.sources.fetch_policy import SourceFetchPolicy
from infrastructure.external.sources.github import GithubConnector
from infrastructure.research.artifact_port import FilesystemHarnessArtifactPort
from infrastructure.research.candidate_worker import (
    StructuredResearchCandidateWorker,
)
from infrastructure.research.document_compiler import (
    ResearchDocumentCompilerAdapter,
)
from infrastructure.research.filesystem_run_store import (
    FilesystemResearchRunStore,
)
from infrastructure.research.github_repository import (
    GithubResearchRepositoryAdapter,
)
from infrastructure.research.local_chunk_store import LocalChunkPayloadStore
from infrastructure.research.source_provider import ArxivResearchSourceProvider
from infrastructure.storage.events.factory import durable_event_storage_from_env
from interfaces.composition.research_errors import (
    ResearchCapability,
    ResearchCompositionError,
    ResearchRuntimeUnavailableError,
)
from interfaces.composition.research_settings import (
    ResearchParserSettings,
    ResearchRAGSettings,
    ResearchRuntimeSettings,
)
from interfaces.services.research_service import (
    ResearchApplicationService,
    ResearchRunRecord,
    ResearchServiceError,
)
from interfaces.services.source_runtime import SourceRuntimeProvider


_RESEARCH_EVENT_TENANT_ID = "research-runtime"


class ResearchRuntimeComposition:
    """Own one composed Research service and its process-scoped resources."""

    __slots__ = (
        "_availability_error",
        "_close_lock",
        "_closed",
        "_resources",
        "_service",
        "_settings",
        "_source_runtime_provider",
    )

    def __init__(
        self,
        *,
        settings: ResearchRuntimeSettings | None,
        service: ResearchApplicationService,
        source_runtime_provider: SourceRuntimeProvider,
        resources: Iterable[Any] = (),
        availability_error: ResearchCompositionError | None = None,
    ) -> None:
        if settings is not None and not isinstance(settings, ResearchRuntimeSettings):
            raise TypeError("settings must be ResearchRuntimeSettings")
        if not isinstance(service, ResearchApplicationService):
            raise TypeError("service must be ResearchApplicationService")
        if not isinstance(source_runtime_provider, SourceRuntimeProvider):
            raise TypeError("source_runtime_provider must be SourceRuntimeProvider")
        if availability_error is not None and not isinstance(
            availability_error,
            ResearchCompositionError,
        ):
            raise TypeError("availability_error must be ResearchCompositionError")
        if settings is None and availability_error is None:
            raise ValueError("available Research composition requires settings")

        unique_resources: list[Any] = []
        seen: set[int] = set()
        for resource in resources:
            if resource is None or id(resource) in seen:
                continue
            seen.add(id(resource))
            unique_resources.append(resource)

        self._settings = settings
        self._service = service
        self._source_runtime_provider = source_runtime_provider
        self._resources = tuple(unique_resources)
        self._availability_error = availability_error
        self._close_lock = Lock()
        self._closed = False

    @property
    def settings(self) -> ResearchRuntimeSettings | None:
        return self._settings

    @property
    def service(self) -> ResearchApplicationService:
        return self._service

    @property
    def source_runtime_provider(self) -> SourceRuntimeProvider:
        return self._source_runtime_provider

    @property
    def resources(self) -> tuple[Any, ...]:
        return self._resources

    @property
    def availability_error(self) -> ResearchCompositionError | None:
        return self._availability_error

    @property
    def available(self) -> bool:
        return self._availability_error is None

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True

        first_error: Exception | None = None
        for resource in reversed(self._resources):
            close = getattr(resource, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except Exception as exc:  # close every owned resource before reporting
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error


class _PaperRagUseCaseProvider:
    """Own the chunk-RAG service under the Research composition lifecycle."""

    __slots__ = (
        "_ask_use_case",
        "_closed",
        "_lock",
        "_runtime_resources",
        "_service",
    )

    def __init__(self, ask_use_case: AskPaperUseCase) -> None:
        self._ask_use_case = ask_use_case
        self._closed = False
        self._lock = Lock()
        self._runtime_resources: Any | None = None
        self._service: Any | None = None

    def rag_ask(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._get().rag_ask(*args, **kwargs)

    def get_reranker(self) -> Any:
        return self._get().get_reranker()

    def preload_reranker(self) -> None:
        self._get().preload_reranker()

    def runtime_resources(self) -> Any:
        self._get()
        with self._lock:
            if self._closed or self._runtime_resources is None:
                raise RuntimeError("Research chunk RAG provider is closed")
            return self._runtime_resources

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            service = self._service
            self._service = None
            runtime_resources = self._runtime_resources
            self._runtime_resources = None

        first_error: Exception | None = None
        for resource in (service, runtime_resources):
            close = getattr(resource, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def _get(self) -> Any:
        with self._lock:
            if self._closed:
                raise RuntimeError("Research chunk RAG provider is closed")
            if self._service is None:
                from interfaces.services.paper_rag_service import (
                    PaperRagApplicationService,
                )
                from interfaces.services.paper_rag_factory import (
                    PaperRagRuntimeResources,
                )

                runtime_resources = PaperRagRuntimeResources()
                try:
                    service = PaperRagApplicationService(
                        ask_use_case=self._ask_use_case,
                        runtime_resources=runtime_resources,
                    )
                except BaseException:
                    _close_quietly(runtime_resources)
                    raise
                self._runtime_resources = runtime_resources
                self._service = service
            return self._service


SettingsFactory = Callable[[], ResearchRuntimeSettings]
ConfiguredCompositionFactory = Callable[
    [ResearchRuntimeSettings, SourceRuntimeProvider],
    ResearchRuntimeComposition,
]
CompositionFactory = Callable[[], ResearchRuntimeComposition]


def build_research_runtime_composition(
    *,
    settings: ResearchRuntimeSettings | None = None,
    settings_factory: SettingsFactory | None = None,
    source_runtime_provider: SourceRuntimeProvider | None = None,
    configured_factory: ConfiguredCompositionFactory | None = None,
) -> ResearchRuntimeComposition:
    if settings is not None and settings_factory is not None:
        raise ValueError("settings and settings_factory are mutually exclusive")
    provider = source_runtime_provider or SourceRuntimeProvider()

    actual_settings = settings
    if actual_settings is None:
        try:
            actual_settings = (settings_factory or ResearchRuntimeSettings.from_env)()
        except ResearchCompositionError as exc:
            return _unavailable_composition(
                exc,
                settings=None,
                source_runtime_provider=provider,
            )

    try:
        composition = (configured_factory or _build_configured_composition)(
            actual_settings,
            provider,
        )
    except ResearchCompositionError as exc:
        return _unavailable_composition(
            exc,
            settings=actual_settings,
            source_runtime_provider=provider,
        )
    if not isinstance(composition, ResearchRuntimeComposition):
        raise TypeError("configured_factory must return ResearchRuntimeComposition")
    if composition.settings != actual_settings:
        raise ValueError("configured_factory returned a composition for different settings")
    if composition.source_runtime_provider is not provider:
        raise ValueError(
            "configured_factory must use the supplied SourceRuntimeProvider"
        )
    return composition


class ResearchRuntimeProvider:
    """Lazily cache one explicit Research composition for an owning process."""

    def __init__(
        self,
        factory: CompositionFactory | None = None,
        *,
        settings_factory: SettingsFactory | None = None,
        configured_factory: ConfiguredCompositionFactory | None = None,
        source_runtime_provider: SourceRuntimeProvider | None = None,
    ) -> None:
        if factory is not None and (
            settings_factory is not None or configured_factory is not None
        ):
            raise ValueError(
                "factory cannot be combined with settings_factory or configured_factory"
            )
        self._source_runtime_provider = source_runtime_provider or SourceRuntimeProvider()
        self._factory = factory or (
            lambda: build_research_runtime_composition(
                settings_factory=settings_factory,
                source_runtime_provider=self._source_runtime_provider,
                configured_factory=configured_factory,
            )
        )
        self._composition: ResearchRuntimeComposition | None = None
        self._condition = Condition(Lock())
        self._transitioning = False
        self._closed = False

    @property
    def source_runtime_provider(self) -> SourceRuntimeProvider:
        return self._source_runtime_provider

    @property
    def initialized(self) -> bool:
        with self._condition:
            self._wait_for_transition()
            return self._composition is not None

    @property
    def closed(self) -> bool:
        with self._condition:
            self._wait_for_transition()
            return self._closed

    def get(self) -> ResearchRuntimeComposition:
        with self._condition:
            self._wait_for_transition()
            if self._closed:
                raise RuntimeError("ResearchRuntimeProvider is closed")
            if self._composition is not None:
                return self._composition
            self._transitioning = True

        try:
            composition = self._factory()
            if not isinstance(composition, ResearchRuntimeComposition):
                raise TypeError("factory must return ResearchRuntimeComposition")
            if composition.source_runtime_provider is not self._source_runtime_provider:
                raise ValueError(
                    "factory must use the provider's SourceRuntimeProvider"
                )
        except BaseException:
            with self._condition:
                self._transitioning = False
                self._condition.notify_all()
            raise

        with self._condition:
            self._composition = composition
            self._transitioning = False
            self._condition.notify_all()
            return composition

    def service_factory(self) -> ResearchApplicationService:
        return self.get().service

    def reset(self) -> None:
        with self._condition:
            self._wait_for_transition()
            self._transitioning = True
            composition = self._composition
            self._composition = None
        try:
            if composition is not None:
                composition.close()
        finally:
            with self._condition:
                self._closed = False
                self._transitioning = False
                self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._wait_for_transition()
            if self._closed:
                return
            self._transitioning = True
            composition = self._composition
            self._composition = None
        try:
            if composition is not None:
                composition.close()
        finally:
            with self._condition:
                self._closed = True
                self._transitioning = False
                self._condition.notify_all()

    def _wait_for_transition(self) -> None:
        while self._transitioning:
            self._condition.wait()


def default_research_runtime_provider() -> ResearchRuntimeProvider:
    return _DEFAULT_RESEARCH_RUNTIME_PROVIDER


def build_research_application_service() -> ResearchApplicationService:
    return _DEFAULT_RESEARCH_RUNTIME_PROVIDER.service_factory()


def reset_default_research_runtime() -> None:
    _DEFAULT_RESEARCH_RUNTIME_PROVIDER.reset()


def close_default_research_runtime() -> None:
    _DEFAULT_RESEARCH_RUNTIME_PROVIDER.close()


def get_default_research_reranker() -> Any:
    provider = _default_paper_rag_use_case_provider()
    return provider.get_reranker()


def get_default_paper_rag_runtime_resources() -> Any:
    provider = _default_paper_rag_use_case_provider()
    return provider.runtime_resources()


def preload_default_research_reranker() -> None:
    provider = _default_paper_rag_use_case_provider()
    provider.preload_reranker()


def _default_paper_rag_use_case_provider() -> _PaperRagUseCaseProvider:
    rag_use_case = _DEFAULT_RESEARCH_RUNTIME_PROVIDER.service_factory()._rag_ask_use_case
    if not isinstance(rag_use_case, _PaperRagUseCaseProvider):
        raise RuntimeError(
            "default Research composition does not own a Paper RAG provider"
        )
    return rag_use_case


class _UnavailableAnalyzeUseCase:
    def __init__(self, error: ResearchCompositionError) -> None:
        self._error = error

    def analyze(self, _request: Any) -> Any:
        raise _research_service_error(self._error)


class _UnavailableResearchRunStore:
    def __init__(self, error: ResearchCompositionError) -> None:
        self._error = error

    def save(self, _record: ResearchRunRecord) -> None:
        raise _research_service_error(self._error)

    def get_by_run_id(self, _run_id: str) -> ResearchRunRecord | None:
        raise _research_service_error(self._error)

    def get_latest_by_paper_id(self, _paper_id: str) -> ResearchRunRecord | None:
        raise _research_service_error(self._error)

    def list_by_paper_id(self, _paper_id: str) -> list[ResearchRunRecord]:
        raise _research_service_error(self._error)


def _unavailable_composition(
    error: ResearchCompositionError,
    *,
    settings: ResearchRuntimeSettings | None,
    source_runtime_provider: SourceRuntimeProvider,
) -> ResearchRuntimeComposition:
    ask_use_case = AskPaperUseCase()
    rag_ask_provider = _PaperRagUseCaseProvider(ask_use_case)
    service = ResearchApplicationService(
        analyze_use_case=_UnavailableAnalyzeUseCase(error),
        ask_use_case=ask_use_case,
        rag_ask_use_case=rag_ask_provider,
        run_store=_UnavailableResearchRunStore(error),
    )
    return ResearchRuntimeComposition(
        settings=settings,
        service=service,
        source_runtime_provider=source_runtime_provider,
        resources=(rag_ask_provider,),
        availability_error=error,
    )


def _research_service_error(error: ResearchCompositionError) -> ResearchServiceError:
    public = error.to_public_dict()
    return ResearchServiceError(
        str(public["code"]),
        str(public["message"]),
        status_code=503,
        details={
            "capabilities": list(public["capabilities"]),
            "remediation": dict(public["remediation"]),
        },
        retryable=bool(public["retryable"]),
        user_action_required=True,
    )


def _build_research_chunk_store(
    settings: ResearchRAGSettings,
    *,
    qdrant_client_factory: Callable[..., Any] | None = None,
    embedding_model_factory: Callable[..., Any] | None = None,
) -> tuple[ChunkStorePort, tuple[Any, ...]]:
    if not isinstance(settings, ResearchRAGSettings):
        raise TypeError("settings must be ResearchRAGSettings")

    client: Any | None = None
    try:
        if settings.backend == "local":
            payload_store = LocalChunkPayloadStore(
                settings.local_root,
                collection=settings.collection,
            )
            store = PaperChunkStoreAdapter(payload_store)
            resources: tuple[Any, ...] = ()
        else:
            # Qdrant is optional for baseline readiness. Keep every Qdrant import
            # inside this selected branch so the local backend remains importable
            # without the optional client/runtime.
            from qdrant_client import QdrantClient

            from infrastructure.storage.vector.embeddings import embedding_model_from_env
            from infrastructure.storage.vector.paper_chunk_store import PaperChunkStore
            from infrastructure.storage.vector.qdrant_store import QdrantVectorStore

            client_builder = qdrant_client_factory or QdrantClient
            embedding_builder = embedding_model_factory or embedding_model_from_env
            client = client_builder(url=settings.qdrant_url)
            embedding_model = embedding_builder(vector_size=settings.vector_size)
            vector_store = QdrantVectorStore(
                client,
                embedding_model=embedding_model,
                vector_size=settings.vector_size,
            )
            store = PaperChunkStoreAdapter(
                PaperChunkStore(vector_store, collection=settings.collection)
            )
            resources = (client,)
        store.ensure_collection()
        return store, resources
    except ResearchCompositionError:
        _close_quietly(client)
        raise
    except Exception:
        _close_quietly(client)
        capability = (
            ResearchCapability.RAG_LOCAL_ROOT
            if settings.backend == "local"
            else ResearchCapability.RAG_VECTOR_BACKEND
        )
        raise ResearchRuntimeUnavailableError(
            (capability,),
            retryable=True,
        ) from None


def _close_quietly(resource: Any | None) -> None:
    close = getattr(resource, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:
        return


def _build_configured_composition(
    settings: ResearchRuntimeSettings,
    source_runtime_provider: SourceRuntimeProvider,
) -> ResearchRuntimeComposition:
    owned_resources: list[Any] = []
    try:
        source_runtime = _compose_component(
            ResearchCapability.SOURCE,
            source_runtime_provider.get,
        )
        metadata_policy = _research_source_policy(
            source_runtime.fetch_policy,
            timeout_seconds=settings.source.timeout_seconds,
            max_bytes=settings.source.metadata_max_bytes,
        )
        package_policy = _research_source_policy(
            ArxivSourceConnector.default_fetch_policy(),
            timeout_seconds=settings.source.timeout_seconds,
            max_bytes=min(
                settings.source.package_max_bytes,
                settings.parser.max_document_bytes,
            ),
            rate_limit_per_domain_per_minute=(
                source_runtime.fetch_policy.rate_limit_per_domain_per_minute
            ),
        )
        metadata_connector = ArxivConnector(
            fetch_policy=metadata_policy,
            rate_limiter=source_runtime.reservation_ledger,
        )
        package_connector = _configure_research_source_connector(
            source_runtime.research_arxiv_connector,
            package_policy,
        )
        source_provider = ArxivResearchSourceProvider(
            metadata_connector,
            api_url=settings.source.api_url,
            cache_size=settings.source.cache_size,
        )
        document_compiler = _compose_component(
            ResearchCapability.DOCUMENT_COMPILER,
            lambda: ResearchDocumentCompilerAdapter(
                package_connector,
                latex_compiler=ArxivLatexDocumentCompiler(package_connector),
                pdf_parser=_build_research_pdf_parser(settings.parser),
                allow_abstract_fallback=settings.parser.allow_abstract_fallback,
            ),
        )

        llm_client = OpenAICompatibleClient(
            OpenAICompatibleConfig(
                provider=settings.llm.provider,
                base_url=settings.llm.base_url,
                model=settings.llm.model,
                api_key_env=settings.llm.api_key_env,
                timeout_seconds=settings.llm.timeout_seconds,
            ),
            retry_policy=LLMRetryPolicy(
                max_attempts=settings.llm.max_attempts,
            ),
        )
        candidate_worker = _compose_component(
            ResearchCapability.CANDIDATE_WORKER,
            lambda: StructuredResearchCandidateWorker(
                llm_client,
                max_input_tokens=settings.llm.max_input_tokens,
                max_output_tokens=settings.llm.max_output_tokens,
            ),
        )
        github_repository = GithubResearchRepositoryAdapter(
            GithubConnector(
                fetch_policy=metadata_policy,
                rate_limiter=source_runtime.reservation_ledger,
            )
        )

        chunk_store, chunk_resources = _build_research_chunk_store(settings.rag)
        owned_resources.extend(chunk_resources)
        rag_runtime = BoundedDocumentRAGRuntime(chunk_store)
        artifact_port = _compose_component(
            ResearchCapability.ARTIFACT,
            lambda: FilesystemHarnessArtifactPort(
                settings.artifact.root,
                max_write_bytes=settings.artifact.max_bytes,
            ),
        )
        run_store = _compose_component(
            ResearchCapability.RUN_STORE,
            lambda: FilesystemResearchRunStore(
                settings.run_store.root,
                result_decoder=ResearchAnalysisResult.from_dict,
                max_record_bytes=settings.run_store.max_record_bytes,
            ),
        )

        durable_events = _compose_component(
            ResearchCapability.EVENT_LOG,
            lambda: durable_event_storage_from_env(
                artifact_root=settings.artifact.root,
            ),
        )
        owned_resources.extend(
            resource
            for resource in (
                durable_events.event_store,
                durable_events.replay_checkpoint_store,
                durable_events.activity_store,
            )
            if resource is not None
        )

        def event_port_factory(_run_id: str) -> HarnessTransitionPort:
            return durable_events.create_harness_transition_port(
                tenant_id=_RESEARCH_EVENT_TENANT_ID,
            )

        # Validate secure activity storage at composition time. This keeps a
        # missing encryption capability on the typed unavailable path rather
        # than failing the first production request after startup.
        _compose_component(
            ResearchCapability.EVENT_LOG,
            lambda: event_port_factory("research-composition-validation"),
        )

        runtime = ResearchSinglePaperRuntime(
            source_provider=source_provider,
            document_compiler=document_compiler,
            llm_worker=candidate_worker,
            github_repository=github_repository,
            rag_runtime=rag_runtime,
            artifact_port=artifact_port,
            event_port_factory=event_port_factory,
        )
        ask_use_case = AskPaperUseCase()
        rag_ask_provider = _PaperRagUseCaseProvider(ask_use_case)
        owned_resources.append(rag_ask_provider)
        service = ResearchApplicationService(
            analyze_use_case=AnalyzePaperUseCase(runtime),
            ask_use_case=ask_use_case,
            rag_ask_use_case=rag_ask_provider,
            run_store=run_store,
        )
        return ResearchRuntimeComposition(
            settings=settings,
            service=service,
            source_runtime_provider=source_runtime_provider,
            resources=owned_resources,
        )
    except BaseException:
        for resource in reversed(owned_resources):
            _close_quietly(resource)
        raise


def _research_source_policy(
    base: SourceFetchPolicy,
    *,
    timeout_seconds: float,
    max_bytes: int,
    rate_limit_per_domain_per_minute: int | None = None,
) -> SourceFetchPolicy:
    return replace(
        base,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        rate_limit_per_domain_per_minute=(
            base.rate_limit_per_domain_per_minute
            if rate_limit_per_domain_per_minute is None
            else rate_limit_per_domain_per_minute
        ),
    )


def _configure_research_source_connector(
    connector: Any,
    policy: SourceFetchPolicy,
) -> ArxivSourceConnector:
    if not isinstance(connector, ArxivSourceConnector):
        raise ResearchRuntimeUnavailableError(
            (ResearchCapability.SOURCE_PROVIDER,),
            retryable=False,
        )
    # SourceRuntimeComposition owns this Research-specific connector. Applying
    # the validated policy here preserves its shared reservation ledger while
    # keeping parser/package limits settings-driven.
    connector.fetch_policy = policy
    return connector


def _build_research_pdf_parser(
    settings: ResearchParserSettings,
) -> CascadeDocumentParser:
    factories: dict[str, Callable[[], Any]] = {
        "marker": MarkerPdfDocumentParser,
        "mineru": MinerUPdfDocumentParser,
    }
    backends = [
        (backend, factories[backend]())
        for backend in settings.backends
        if backend != "pymupdf"
    ]
    return CascadeDocumentParser(
        backends,
        fallback=PyMuPDFTextDocumentParser(),
    )


def _compose_component(
    capability: ResearchCapability,
    factory: Callable[[], Any],
) -> Any:
    try:
        return factory()
    except ResearchCompositionError:
        raise
    except Exception:
        raise ResearchRuntimeUnavailableError(
            (capability,),
            retryable=True,
        ) from None


_DEFAULT_RESEARCH_RUNTIME_PROVIDER = ResearchRuntimeProvider()


__all__ = [
    "ConfiguredCompositionFactory",
    "ResearchRuntimeComposition",
    "ResearchRuntimeProvider",
    "build_research_application_service",
    "build_research_runtime_composition",
    "close_default_research_runtime",
    "default_research_runtime_provider",
    "get_default_paper_rag_runtime_resources",
    "get_default_research_reranker",
    "preload_default_research_reranker",
    "reset_default_research_runtime",
]
