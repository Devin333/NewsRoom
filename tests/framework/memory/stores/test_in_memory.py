from framework.memory import InMemoryMemoryStore, MemoryQuery, MemoryRecord


def test_in_memory_store_filters_invalidated_by_default() -> None:
    active = MemoryRecord(memory_id="active", content="active memory")
    invalidated = MemoryRecord(memory_id="invalid", content="invalid memory").mark_invalidated("test")
    store = InMemoryMemoryStore([active, invalidated])

    results = store.search(MemoryQuery(query="memory"))

    assert [result.memory_id for result in results] == ["active"]
