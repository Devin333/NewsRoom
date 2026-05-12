from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.framework.artifacts import ArtifactManager
from core.framework.tools.arxiv_tools import register_arxiv_tools
from core.framework.tools.artifact_tools import register_artifact_tools
from core.framework.tools.control_tools import register_control_tools
from core.framework.tools.github_tools import register_github_tools
from core.framework.tools.local_json_tools import register_local_json_tools
from core.framework.tools.memory_tools import register_memory_tools
from core.framework.tools.notification_tools import register_notification_tools
from core.framework.tools.postgres_tools import register_postgres_tools
from core.framework.tools.quality_tools import register_quality_tools
from core.framework.tools.qdrant_tools import register_qdrant_tools
from core.framework.tools.registry import ToolRegistry
from core.framework.tools.report_tools import register_report_tools
from core.framework.tools.source_tools import FetchText, register_source_tools
from core.framework.tools.web_search_tools import WebSearchProvider, register_web_search_tools
from core.framework.tools.models import ToolDefinition, ToolPolicy
from sources import SourceRegistry
from sources.connectors import ArxivConnector, GithubConnector, SourceFetchPolicy
from sources.health import BasicSourceHealthManager
from storage.memory import MemoryIngestionService


@dataclass(frozen=True)
class ToolCatalogNamespace:
    namespace: str
    tool_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "tool_count": self.tool_count,
        }


@dataclass(frozen=True)
class ToolCatalog:
    tools: list[ToolDefinition]
    namespaces: list[ToolCatalogNamespace]
    registry_valid: bool
    registry_errors: list[str]
    agent_id: str | None = None

    @property
    def tool_count(self) -> int:
        return len(self.tools)

    @property
    def namespace_count(self) -> int:
        return len(self.namespaces)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "tool_count": self.tool_count,
            "namespace_count": self.namespace_count,
            "namespaces": [namespace.to_dict() for namespace in self.namespaces],
            "tools": [definition.to_dict() for definition in self.tools],
            "registry_valid": self.registry_valid,
            "registry_errors": list(self.registry_errors),
        }


def build_builtin_tool_registry(
    *,
    artifact_manager: ArtifactManager | None = None,
    run_id: str | None = None,
    local_json_root: str | Path | None = None,
    source_registry: SourceRegistry | None = None,
    source_fetch_text: FetchText | None = None,
    source_fetch_policy: SourceFetchPolicy | None = None,
    allowed_source_domains: list[str] | None = None,
    source_health_manager: BasicSourceHealthManager | None = None,
    arxiv_connector: ArxivConnector | None = None,
    github_connector: GithubConnector | None = None,
    web_search_provider: WebSearchProvider | None = None,
    vector_store: Any | None = None,
    memory_ingestion_service: MemoryIngestionService | None = None,
    qdrant_vector_store: Any | None = None,
    qdrant_document_store: Any | None = None,
    report_service: Any | None = None,
    persistence_repository: Any | None = None,
    postgres_repository: Any | None = None,
    postgres_source_health_repository: Any | None = None,
    approval_store: Any | None = None,
    task_queue: Any | None = None,
    notification_options: dict[str, Any] | None = None,
    include_network_tools: bool = True,
) -> ToolRegistry:
    registry = ToolRegistry()

    register_source_tools(
        registry,
        fetch_text=source_fetch_text,
        fetch_policy=source_fetch_policy,
        allowed_domains=allowed_source_domains,
        health_manager=source_health_manager,
        source_registry=source_registry,
    )
    register_report_tools(
        registry,
        artifact_manager=artifact_manager,
        run_id=run_id,
        persistence_repository=persistence_repository,
        report_service=report_service,
    )
    register_quality_tools(registry)
    register_control_tools(
        registry,
        approval_store=approval_store,
        task_queue=task_queue,
        run_id=run_id,
    )

    if include_network_tools:
        register_arxiv_tools(registry, connector=arxiv_connector)
        register_github_tools(registry, connector=github_connector)
        register_web_search_tools(registry, provider=web_search_provider)

    if artifact_manager is not None and run_id is not None:
        register_artifact_tools(registry, artifact_manager=artifact_manager, run_id=run_id)
    if local_json_root is not None:
        register_local_json_tools(registry, root=local_json_root)
    if vector_store is not None:
        register_memory_tools(
            registry,
            vector_store=vector_store,
            ingestion_service=memory_ingestion_service,
        )
    if qdrant_vector_store is not None:
        register_qdrant_tools(
            registry,
            vector_store=qdrant_vector_store,
            document_store=qdrant_document_store,
        )
    if postgres_repository is not None:
        register_postgres_tools(
            registry,
            repository=postgres_repository,
            source_health_repository=postgres_source_health_repository,
        )
    if notification_options is not None:
        register_notification_tools(registry, **dict(notification_options))

    return registry


def build_tool_catalog(
    registry: ToolRegistry,
    *,
    agent_id: str | None = None,
    policy: ToolPolicy | None = None,
) -> ToolCatalog:
    if policy is None:
        tools = registry.list_tools()
    else:
        tools = registry.list_tools_for_agent(agent_id or "", policy)
    sorted_tools = sorted(tools, key=lambda definition: (definition.namespace, definition.name))
    validation = registry.validate_no_conflicts()
    return ToolCatalog(
        tools=sorted_tools,
        namespaces=_catalog_namespaces(sorted_tools),
        registry_valid=validation.ok,
        registry_errors=list(validation.errors),
        agent_id=agent_id,
    )


def _catalog_namespaces(tools: list[ToolDefinition]) -> list[ToolCatalogNamespace]:
    counts: dict[str, int] = {}
    for definition in tools:
        counts[definition.namespace] = counts.get(definition.namespace, 0) + 1
    return [
        ToolCatalogNamespace(namespace=namespace, tool_count=counts[namespace])
        for namespace in sorted(counts)
    ]
