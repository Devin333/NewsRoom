from __future__ import annotations

from framework.tool.registry.registry import RegisteredTool, ToolRegistry


class ToolResolver:
    def resolve(self, name: str, registry: ToolRegistry) -> RegisteredTool:
        return registry.require(name)

    def resolve_many(self, names: list[str], registry: ToolRegistry) -> list[RegisteredTool]:
        return [self.resolve(name, registry) for name in names]
