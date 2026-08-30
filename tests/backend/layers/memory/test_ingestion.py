from types import SimpleNamespace

from backend.layers.memory.ingestion import MemoryIngestionService
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
    assert result.counts["evidence"] == 0
    assert result.to_dict()["indexed_documents"] == 1
    memory = runtime.get("run-1:report_section:0")
    assert memory is not None
    assert memory.actor == "business.layers.memory.ingestion"


def test_memory_ingestion_marks_run_only_write_as_standalone() -> None:
    runtime = _CapturingMemoryRuntime()
    service = MemoryIngestionService(memory_runtime=runtime)

    service.ingest_report(
        {
            "title": "Standalone report",
            "sections": [{"title": "Summary", "content": "Content"}],
        },
        run_id="run-standalone",
    )

    assert runtime.write_kwargs["run_id"] == "run-standalone"
    assert runtime.write_kwargs["standalone"] is True


class _CapturingMemoryRuntime:
    def __init__(self) -> None:
        self.write_kwargs: dict[str, object] = {}

    def write(self, **kwargs: object) -> SimpleNamespace:
        self.write_kwargs = dict(kwargs)
        records = kwargs.get("records")
        return SimpleNamespace(
            written_count=len(records) if isinstance(records, list) else 0,
            memory_ids=(
                [record.memory_id for record in records]
                if isinstance(records, list)
                else []
            ),
        )
