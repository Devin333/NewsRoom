from __future__ import annotations


def test_public_imports_are_available() -> None:
    from framework.workers import (  # noqa: PLC0415
        InMemoryScheduleStore,
        InMemoryTaskQueue,
        ScheduleRecord,
        Task,
        TaskHandler,
        TaskQueue,
        WorkerHeartbeat,
        WorkerMetrics,
    )

    assert Task is not None
    assert TaskQueue is not None
    assert TaskHandler is not None
    assert InMemoryTaskQueue is not None
    assert InMemoryScheduleStore is not None
    assert ScheduleRecord is not None
    assert WorkerHeartbeat is not None
    assert WorkerMetrics is not None
