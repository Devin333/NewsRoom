from __future__ import annotations

from framework.tool.models.call import ToolCall
from framework.tool.models.definition import ToolDefinition
from framework.tool.models.policy import ToolPolicy


class ToolSandbox:
    def check(
        self,
        definition: ToolDefinition,
        call: ToolCall,
        policy: ToolPolicy,
    ) -> list[str]:
        _ = call
        allowed, reason = policy.can_call(definition)
        return [] if allowed else [reason or f"tool is not allowed: {definition.name}"]
