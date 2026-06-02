"""MemoryRuntime-backed bridge store for shared agent sessions."""

from __future__ import annotations

from typing import Mapping

from framework.agent.session.in_memory_store import InMemoryAgentSessionStore
from framework.agent.session.models import AgentSessionEvent, AgentSessionItem, AgentSessionSnapshot
from framework.memory.runtime import MemoryRuntime
from framework.memory.session import AgentSessionMemoryAdapter


class MemoryRuntimeAgentSessionStore(InMemoryAgentSessionStore):
    """Session store that keeps operational state locally and writes through to MemoryRuntime."""

    def __init__(self, memory_runtime: MemoryRuntime | None = None) -> None:
        super().__init__()
        self.adapter = AgentSessionMemoryAdapter(memory_runtime)

    def append_item(self, item: AgentSessionItem) -> AgentSessionItem:
        stored = super().append_item(item)
        self.adapter.write_item(stored)
        return stored

    def append_event(self, event: AgentSessionEvent) -> AgentSessionEvent:
        stored = super().append_event(event)
        self.adapter.write_event(stored)
        return stored

    def create_snapshot(self, snapshot: AgentSessionSnapshot) -> AgentSessionSnapshot:
        stored = super().create_snapshot(snapshot)
        self.adapter.write_snapshot(stored)
        return stored

    def recall_memory(
        self,
        *,
        session_id: str | None = None,
        role: str | None = None,
        refs: Mapping[str, object] | None = None,
        limit: int = 10,
    ) -> list[dict[str, object]]:
        """Recall session memories from MemoryRuntime."""

        return self.adapter.recall(session_id=session_id, role=role, refs=refs, limit=limit)
