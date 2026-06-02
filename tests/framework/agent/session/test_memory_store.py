from __future__ import annotations

from typing import Any

from framework.agent.session import AgentSessionItem, AgentSessionSnapshot, MemoryRuntimeAgentSessionStore
from framework.memory.models import MemoryQuery, MemoryRecallResult, MemorySearchResult, MemoryWriteMode, MemoryWriteResult


def test_memory_runtime_store_writes_items_and_snapshots_to_memory() -> None:
    runtime = _FakeMemoryRuntime()
    store = MemoryRuntimeAgentSessionStore(runtime)

    item = store.append_item(
        AgentSessionItem(
            session_id="session-1",
            run_id="run-1",
            agent_id="agent-a",
            role="final",
            content={"answer": "yes"},
            summary="Final answer.",
            refs={"paperId": "paper-1"},
            status="final",
        )
    )
    snapshot = store.create_snapshot(
        AgentSessionSnapshot(
            session_id="session-1",
            run_id="run-1",
            summary="final: 1",
            role_summaries={"final": {"count": 1}},
            final_items=(item.item_id,),
            source_event_ids=(),
        )
    )

    assert [call["namespace"] for call in runtime.write_calls] == [
        "agent_session_event:session-1",
        "agent_session:session-1",
        "agent_session_event:session-1",
        "agent_session_snapshot:session-1",
    ]
    assert runtime.write_calls[0]["mode"] == MemoryWriteMode.UPSERT
    assert runtime.records[0].memory_id.startswith("agent-session-event:")
    assert runtime.records[1].memory_id == f"agent-session-item:{item.item_id}"
    assert runtime.records[3].memory_id == f"agent-session-snapshot:{snapshot.snapshot_id}"


def test_memory_runtime_store_recalls_serialized_memory() -> None:
    runtime = _FakeMemoryRuntime()
    store = MemoryRuntimeAgentSessionStore(runtime)
    stored = store.append_item(
        AgentSessionItem(
            session_id="session-1",
            run_id="run-1",
            agent_id="agent-a",
            role="final",
            content={"answer": "yes"},
            summary="Final answer.",
            refs={"paperId": "paper-1"},
        )
    )

    recalled = store.recall_memory(session_id="session-1", role="final", refs={"paperId": "paper-1"}, limit=3)

    assert recalled[0]["memory_id"] == f"agent-session-item:{stored.item_id}"
    assert runtime.recall_calls[0].query == "agent_session session-1 final paperId:paper-1"
    assert runtime.recall_calls[0].filters["trace_kind"] == "agent_session_item"
    assert runtime.recall_calls[0].limit == 3


class _FakeMemoryRuntime:
    def __init__(self) -> None:
        self.records: list[Any] = []
        self.write_calls: list[dict[str, Any]] = []
        self.recall_calls: list[MemoryQuery] = []

    def write(self, *, records: list[Any], mode: MemoryWriteMode, actor: str, run_id: str, namespace: str) -> MemoryWriteResult:
        self.records.extend(records)
        self.write_calls.append({"mode": mode, "actor": actor, "run_id": run_id, "namespace": namespace})
        return MemoryWriteResult(
            accepted_count=len(records),
            written_count=len(records),
            memory_ids=[record.memory_id for record in records],
        )

    def recall(self, query: MemoryQuery) -> MemoryRecallResult:
        self.recall_calls.append(query)
        return MemoryRecallResult(
            query=query,
            results=[MemorySearchResult.from_record(record, relevance=0.9) for record in self.records],
        )
