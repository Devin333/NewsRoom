from __future__ import annotations

from framework.memory.models import MemoryRecallResult, MemoryRecord, MemoryWriteResult


def assert_memory_record_equal(left: MemoryRecord, right: MemoryRecord) -> None:
    assert left.to_dict() == right.to_dict()


def assert_recall_contains(result: MemoryRecallResult, memory_id: str) -> None:
    assert memory_id in [item.memory_id for item in result.results]


def assert_write_success(result: MemoryWriteResult, *, written_count: int | None = None) -> None:
    assert result.success is True
    if written_count is not None:
        assert result.written_count == written_count
