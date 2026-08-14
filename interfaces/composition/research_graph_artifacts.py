from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from os import PathLike

from business.research.application.graph_artifact_governance import (
    ResearchGraphArtifactGovernanceService,
)
from framework.harness.artifacts import GraphArtifactGovernanceRuntime
from framework.harness.runtime import PersistencePolicy, ResultMaterializer
from infrastructure.research import (
    FilesystemGraphArtifactLifecycle,
    FilesystemHarnessArtifactPort,
)
from infrastructure.storage.artifacts import (
    LocalJsonArtifactCatalog,
    SQLiteGraphResultStore,
)
from interfaces.composition.research_errors import (
    ResearchCapability,
    ResearchCompositionError,
    ResearchRuntimeUnavailableError,
)
from interfaces.composition.research_settings import ResearchRuntimeSettings


@dataclass(frozen=True, slots=True)
class ResearchGraphArtifactRuntimeComponents:
    artifact_port: FilesystemHarnessArtifactPort
    catalog: LocalJsonArtifactCatalog
    store: SQLiteGraphResultStore
    lifecycle: FilesystemGraphArtifactLifecycle
    materializer: ResultMaterializer
    governance_runtime: GraphArtifactGovernanceRuntime
    governance_service: ResearchGraphArtifactGovernanceService

    def __post_init__(self) -> None:
        if self.lifecycle.artifact_port is not self.artifact_port:
            raise ValueError("graph artifact lifecycle must share artifact_port")
        if self.materializer._artifact_port is not self.artifact_port:
            raise ValueError("graph artifact materializer must share artifact_port")
        if self.materializer._catalog is not self.catalog:
            raise ValueError("graph artifact materializer must share catalog")
        for owner in (
            self.materializer._quota,
            self.materializer._usage,
            self.materializer._cache,
            self.materializer._attempts,
            self.governance_runtime._ledger,
        ):
            if owner is not self.store:
                raise ValueError("graph artifact components must share result store")
        if self.governance_runtime._catalog is not self.catalog:
            raise ValueError("graph artifact governance must share catalog")
        if self.governance_runtime._lifecycle is not self.lifecycle:
            raise ValueError("graph artifact governance must share lifecycle")
        if self.governance_service.runtime is not self.governance_runtime:
            raise ValueError("graph artifact service must share governance runtime")


def compose_research_graph_artifact_runtime(
    settings: ResearchRuntimeSettings,
    *,
    artifact_port: FilesystemHarnessArtifactPort | None = None,
) -> ResearchGraphArtifactRuntimeComponents:
    if not isinstance(settings, ResearchRuntimeSettings):
        raise TypeError("settings must be ResearchRuntimeSettings")
    try:
        actual_artifact_port = artifact_port or FilesystemHarnessArtifactPort(
            settings.artifact.root,
            max_write_bytes=settings.artifact.max_bytes,
        )
        config = settings.graph_artifact_persistence
        catalog = LocalJsonArtifactCatalog(
            settings.artifact.root / "_records" / "graph_artifact_catalog"
        )
        store = SQLiteGraphResultStore(
            settings.research_root / "graph-results.sqlite3",
            max_materialized_bytes_per_run=(
                config.max_materialized_bytes_per_run
            ),
            max_artifacts_per_run=config.max_artifacts_per_run,
            max_materialized_bytes_per_tenant=(
                config.max_materialized_bytes_per_tenant
            ),
            max_artifacts_per_tenant=config.max_artifacts_per_tenant,
            max_materialized_bytes_per_class=(
                config.max_materialized_bytes_per_class
            ),
            max_artifacts_per_class=config.max_artifacts_per_class,
        )
        lifecycle = FilesystemGraphArtifactLifecycle(
            settings.artifact.root,
            artifact_port=actual_artifact_port,
            max_physical_bytes=config.max_artifact_bytes,
        )
        materializer = ResultMaterializer(
            policy=PersistencePolicy(config),
            artifact_port=actual_artifact_port,
            catalog=catalog,
            quota=store,
            usage=store,
            cache=store,
            attempts=store,
        )
        governance_runtime = GraphArtifactGovernanceRuntime(
            catalog=catalog,
            lifecycle=lifecycle,
            ledger=store,
            config=config,
        )
        governance_service = ResearchGraphArtifactGovernanceService(
            governance_runtime
        )
        return ResearchGraphArtifactRuntimeComponents(
            artifact_port=actual_artifact_port,
            catalog=catalog,
            store=store,
            lifecycle=lifecycle,
            materializer=materializer,
            governance_runtime=governance_runtime,
            governance_service=governance_service,
        )
    except ResearchCompositionError:
        raise
    except Exception:
        raise ResearchRuntimeUnavailableError(
            (ResearchCapability.GRAPH_ARTIFACT_PERSISTENCE,),
            retryable=True,
        ) from None


def build_research_graph_artifact_governance_service(
    *,
    settings: ResearchRuntimeSettings | None = None,
    env: Mapping[str, str] | None = None,
    cwd: str | PathLike[str] | None = None,
) -> ResearchGraphArtifactGovernanceService:
    if settings is not None and (env is not None or cwd is not None):
        raise ValueError("settings cannot be combined with env or cwd")
    actual_settings = settings or ResearchRuntimeSettings.from_env(env, cwd=cwd)
    return compose_research_graph_artifact_runtime(
        actual_settings
    ).governance_service


__all__ = [
    "ResearchGraphArtifactRuntimeComponents",
    "build_research_graph_artifact_governance_service",
    "compose_research_graph_artifact_runtime",
]
