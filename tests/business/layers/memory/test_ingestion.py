from business.layers.memory.ingestion import MemoryIngestionService
from framework.memory import InMemoryMemoryStore, MemoryRuntime


def test_memory_ingestion_writes_through_framework_memory_runtime() -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore())
    service = MemoryIngestionService(memory_runtime=runtime)

    result = service.ingest_report(
        {
            "title": "Report",
            "sections": [
                {
                    "section_id": "summary",
                    "title": "Summary",
                    "content": "Framework memory stores business report output.",
                }
            ],
        },
        run_id="run-1",
        report_id="report-1",
        topic="AI",
    )

    assert result.memories_written == 1
    memory = runtime.get("run-1:report_section:0")
    assert memory is not None
    assert memory.actor == "business.layers.memory.ingestion"
