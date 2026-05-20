from __future__ import annotations

from dataclasses import dataclass

from framework.llm.models.request import LLMRequest


@dataclass(frozen=True)
class LLMCachePolicy:
    enabled: bool = False
    ttl_seconds: float | None = None
    cacheable_task_types: tuple[str, ...] = ()
    no_cache_agent_ids: tuple[str, ...] = ()

    def allows(self, request: LLMRequest) -> bool:
        if not self.enabled:
            return False
        agent_id = request.metadata.get("agent_id")
        if agent_id in self.no_cache_agent_ids:
            return False
        task_type = request.metadata.get("task_type")
        return isinstance(task_type, str) and task_type in self.cacheable_task_types

