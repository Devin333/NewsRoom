from __future__ import annotations

from typing import Any

from framework.memory.models import MemoryContextBlock


class LLMMemoryContextInjector:
    def inject(
        self,
        *,
        messages: list[dict[str, Any]],
        context: MemoryContextBlock,
    ) -> list[dict[str, Any]]:
        if context.is_empty():
            return list(messages)
        return [self.system_message_from_context(context), *messages]

    def system_message_from_context(self, context: MemoryContextBlock) -> dict[str, Any]:
        return {"role": "system", "content": context.content}
