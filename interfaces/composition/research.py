from __future__ import annotations

from collections.abc import Callable, Iterable
from threading import Condition, Lock
from typing import Any

from business.research.document.chunk_storage import PaperChunkStoreAdapter
from business.research.ports.chunk_store import ChunkStorePort
from infrastructure.research.local_chunk_store import LocalChunkPayloadStore
from interfaces.composition.research_errors import (
    ResearchCapability,
    ResearchCompositionError,
    ResearchRuntimeUnavailableError,
)
from interfaces.composition.research_settings import (
    ResearchRAGSettings,
    ResearchRuntimeSettings,
)
from interfaces.services.research_service import (
    ResearchApplicationService,
    ResearchRunRecord,
    ResearchServiceError,
)
from interfaces.services.source_runtime import SourceRuntimeProvider


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


def _unavailable_composition(
    error: ResearchCompositionError,
    *,
    settings: ResearchRuntimeSettings | None,
    source_runtime_provider: SourceRuntimeProvider,
) -> ResearchRuntimeComposition:
    service = ResearchApplicationService(
        analyze_use_case=_UnavailableAnalyzeUseCase(error),
        run_store=_UnavailableResearchRunStore(error),
    )
    return ResearchRuntimeComposition(
        settings=settings,
        service=service,
        source_runtime_provider=source_runtime_provider,
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
    _settings: ResearchRuntimeSettings,
    _source_runtime_provider: SourceRuntimeProvider,
) -> ResearchRuntimeComposition:
    raise ResearchRuntimeUnavailableError(
        (
            ResearchCapability.CANDIDATE_WORKER,
            ResearchCapability.RAG,
            ResearchCapability.ARTIFACT,
            ResearchCapability.RUN_STORE,
            ResearchCapability.EVENT_LOG,
        )
    )


_DEFAULT_RESEARCH_RUNTIME_PROVIDER = ResearchRuntimeProvider()


__all__ = [
    "ConfiguredCompositionFactory",
    "ResearchRuntimeComposition",
    "ResearchRuntimeProvider",
    "build_research_application_service",
    "build_research_runtime_composition",
    "close_default_research_runtime",
    "default_research_runtime_provider",
    "reset_default_research_runtime",
]
