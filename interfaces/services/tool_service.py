from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business.tools import build_business_tool_registry
from framework.tool import ToolPolicy, build_tool_catalog
from interfaces.services.source_runtime import (
    SourceRuntimeComposition,
    SourceRuntimeProvider,
)


@dataclass(frozen=True)
class ToolCatalogApplicationResult:
    payload: dict[str, Any]
    registry_valid: bool

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


@dataclass(frozen=True)
class ToolSchemaApplicationResult:
    agent_id: str
    tools: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "tool_count": len(self.tools),
            "tools": list(self.tools),
        }


class ToolApplicationService:
    def __init__(
        self,
        *,
        source_runtime: SourceRuntimeComposition | None = None,
        source_runtime_provider: SourceRuntimeProvider | None = None,
    ) -> None:
        if source_runtime is not None and source_runtime_provider is not None:
            raise ValueError(
                "source_runtime and source_runtime_provider are mutually exclusive"
            )
        self._source_runtime = source_runtime
        self._source_runtime_provider = source_runtime_provider or SourceRuntimeProvider()

    def list_tools(
        self,
        *,
        allowed_tools: list[str] | None = None,
        blocked_tools: list[str] | None = None,
        allow_mcp: bool = False,
        include_dangerous: bool = False,
    ) -> ToolCatalogApplicationResult:
        source_runtime = self._resolved_source_runtime()
        registry = build_business_tool_registry(
            include_dangerous_tools=include_dangerous,
            source_registry=source_runtime.source_registry,
            source_fetch_policy=source_runtime.business_fetch_policy,
            source_tool_runtime=source_runtime.source_tool_runtime,
            source_rate_limiter=source_runtime.rate_limiter,
            source_health_manager=source_runtime.health_manager,
        )
        catalog = build_tool_catalog(
            registry,
            agent_id="cli",
            policy=self.tool_policy(
                allowed_tools=allowed_tools,
                blocked_tools=blocked_tools,
                allow_mcp=allow_mcp,
                include_dangerous=include_dangerous,
            ),
        )
        return ToolCatalogApplicationResult(
            payload=catalog.to_dict(),
            registry_valid=catalog.registry_valid,
        )

    def export_schema(
        self,
        *,
        agent_id: str = "cli",
        allowed_tools: list[str] | None = None,
        blocked_tools: list[str] | None = None,
        allow_mcp: bool = False,
        include_dangerous: bool = False,
    ) -> ToolSchemaApplicationResult:
        source_runtime = self._resolved_source_runtime()
        registry = build_business_tool_registry(
            include_dangerous_tools=include_dangerous,
            source_registry=source_runtime.source_registry,
            source_fetch_policy=source_runtime.business_fetch_policy,
            source_tool_runtime=source_runtime.source_tool_runtime,
            source_rate_limiter=source_runtime.rate_limiter,
            source_health_manager=source_runtime.health_manager,
        )
        tools = registry.export_schema_for_llm(
            agent_id,
            self.tool_policy(
                allowed_tools=allowed_tools,
                blocked_tools=blocked_tools,
                allow_mcp=allow_mcp,
                include_dangerous=include_dangerous,
            ),
        )
        return ToolSchemaApplicationResult(agent_id=agent_id, tools=tools)

    def _resolved_source_runtime(self) -> SourceRuntimeComposition:
        if self._source_runtime is not None:
            return self._source_runtime
        return self._source_runtime_provider.get()

    @staticmethod
    def tool_policy(
        *,
        allowed_tools: list[str] | None = None,
        blocked_tools: list[str] | None = None,
        allow_mcp: bool = False,
        include_dangerous: bool = False,
    ) -> ToolPolicy:
        allowed = list(allowed_tools or [])
        return ToolPolicy(
            allowed_tools=allowed,
            blocked_tools=list(blocked_tools or []),
            allow_mcp_tools=bool(allow_mcp),
            allow_dangerous_tools=bool(include_dangerous),
            require_explicit_allowlist=bool(allowed),
        )


__all__ = [
    "ToolApplicationService",
    "ToolCatalogApplicationResult",
    "ToolSchemaApplicationResult",
]
