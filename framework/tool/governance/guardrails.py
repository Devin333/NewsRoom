from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from framework.tool.models.call import ToolCall
from framework.tool.models.definition import ToolDefinition


class ToolGuardrail(Protocol):
    def check(self, call: ToolCall, definition: ToolDefinition) -> list[str]: ...


@dataclass(frozen=True)
class ToolGuardrailChain:
    guardrails: list[ToolGuardrail]

    def check(self, call: ToolCall, definition: ToolDefinition) -> list[str]:
        errors: list[str] = []
        for guardrail in self.guardrails:
            errors.extend(guardrail.check(call, definition))
        return errors
