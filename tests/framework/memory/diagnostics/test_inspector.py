from framework.memory import InMemoryMemoryStore, MemoryRecord, MemoryRuntime, MemoryRuntimeInspector


def test_runtime_inspector_reports_metrics() -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore([MemoryRecord(content="diagnostic memory")]))

    inspection = MemoryRuntimeInspector().inspect(runtime)

    assert inspection.metrics.total_records == 1
    assert inspection.health.status.value == "healthy"
