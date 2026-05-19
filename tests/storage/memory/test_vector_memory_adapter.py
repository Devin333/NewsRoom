from core.framework.memory import MemoryKind, MemoryQuery, MemoryRecord, MemoryScope
from storage.memory import VectorMemoryStoreAdapter
from storage.vector import InMemoryVectorStore


def test_vector_memory_store_adapter_writes_and_searches_memory_records() -> None:
    vector_store = InMemoryVectorStore()
    adapter = VectorMemoryStoreAdapter(vector_store)
    record = MemoryRecord(
        memory_id="mem-1",
        content="Workflow memory runtime uses a vector-backed store.",
        kind=MemoryKind.SEMANTIC,
        scope=MemoryScope.WORKFLOW,
        refs={"run_id": "run-1"},
        metadata={"workflow_id": "wf-1"},
    )

    write = adapter.write(record)
    results = adapter.search(
        MemoryQuery(
            query="workflow vector memory",
            scopes=[MemoryScope.WORKFLOW],
            kinds=[MemoryKind.SEMANTIC],
            limit=3,
        )
    )
    fetched = adapter.get("mem-1")

    assert write.written_count == 1
    assert results[0].record.memory_id == "mem-1"
    assert results[0].record.refs["run_id"] == "run-1"
    assert fetched is not None
    assert fetched.memory_id == record.memory_id
    assert fetched.content == record.content
    assert fetched.refs["run_id"] == "run-1"
