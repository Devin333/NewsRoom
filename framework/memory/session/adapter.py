"""Adapter that persists shared session state into MemoryRuntime."""

from __future__ import annotations

from typing import Any, Mapping

from framework.agent.session.models import AgentSessionEvent, AgentSessionItem, AgentSessionSnapshot
from framework.memory.models import MemoryQuery, MemoryWriteMode
from framework.memory.runtime import MemoryRuntime
from framework.memory.session.serializers import event_to_memory_record, item_to_memory_record, snapshot_to_memory_record


class AgentSessionMemoryAdapter:
    """Write and recall agent session records through MemoryRuntime."""

    def __init__(self, memory_runtime: MemoryRuntime | None = None) -> None:
        self._memory_runtime = memory_runtime

    @property
    def available(self) -> bool:
        """Return whether a real MemoryRuntime is configured."""

        return self._memory_runtime is not None

    def write_item(self, item: AgentSessionItem) -> dict[str, Any]:
        """Write one item to memory when runtime is available."""

        if self._memory_runtime is None:
            return {"available": False, "written_count": 0, "warnings": ["memory runtime unavailable"]}
        result = self._memory_runtime.write(
            records=[item_to_memory_record(item)],
            mode=MemoryWriteMode.UPSERT,
            actor=item.agent_id,
            run_id=item.run_id,
            namespace=f"agent_session:{item.session_id}",
        )
        return {"available": True, "written_count": result.written_count, "memory_ids": list(result.memory_ids), "errors": list(result.errors)}

    def write_snapshot(self, snapshot: AgentSessionSnapshot) -> dict[str, Any]:
        """Write one snapshot to memory when runtime is available."""

        if self._memory_runtime is None:
            return {"available": False, "written_count": 0, "warnings": ["memory runtime unavailable"]}
        result = self._memory_runtime.write(
            records=[snapshot_to_memory_record(snapshot)],
            mode=MemoryWriteMode.UPSERT,
            actor="agent-session-runtime",
            run_id=snapshot.run_id,
            namespace=f"agent_session_snapshot:{snapshot.session_id}",
        )
        return {"available": True, "written_count": result.written_count, "memory_ids": list(result.memory_ids), "errors": list(result.errors)}

    def write_event(self, event: AgentSessionEvent) -> dict[str, Any]:
        """Write one session event to memory when runtime is available."""

        if self._memory_runtime is None:
            return {"available": False, "written_count": 0, "warnings": ["memory runtime unavailable"]}
        result = self._memory_runtime.write(
            records=[event_to_memory_record(event)],
            mode=MemoryWriteMode.UPSERT,
            actor=event.agent_id or "agent-session-runtime",
            run_id=event.run_id,
            namespace=f"agent_session_event:{event.session_id}",
        )
        return {"available": True, "written_count": result.written_count, "memory_ids": list(result.memory_ids), "errors": list(result.errors)}

    def recall(
        self,
        *,
        session_id: str | None = None,
        role: str | None = None,
        refs: Mapping[str, Any] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Recall serialized session memories."""

        if self._memory_runtime is None:
            return []
        terms = ["agent_session"]
        filters: dict[str, Any] = {}
        if session_id:
            terms.append(session_id)
            filters["session_id"] = session_id
        if role:
            terms.append(role)
            filters["role"] = role
        filters["trace_kind"] = "agent_session_item"
        for key, value in dict(refs or {}).items():
            terms.append(f"{key}:{value}")
            filters[str(key)] = value
        result = self._memory_runtime.recall(
            MemoryQuery(
                query=" ".join(terms),
                filters=filters,
                namespace=f"agent_session:{session_id}" if session_id else None,
                limit=limit,
            )
        )
        return [
            record.to_dict()
            for record in result.results
            if record.record.metadata.get("trace_kind") == "agent_session_item"
        ]
