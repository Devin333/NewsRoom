from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolNamespace:
    namespace: str
    short_name: str | None = None

    @classmethod
    def parse(cls, tool_name: str) -> "ToolNamespace":
        namespace, separator, short_name = tool_name.partition(".")
        if not separator:
            return cls(namespace=tool_name, short_name=None)
        return cls(namespace=namespace, short_name=short_name)

    def matches(self, tool_name: str) -> bool:
        parsed = self.parse(tool_name)
        return parsed.namespace == self.namespace
