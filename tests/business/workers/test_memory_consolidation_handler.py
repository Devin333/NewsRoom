from business.memory.consolidation import MemoryConsolidationResult
from business.workers.memory_consolidation_handler import MemoryConsolidationTaskHandler, handle_memory_consolidation_task
from framework.workers.models import Task


def test_memory_consolidation_handler_uses_injected_service() -> None:
    service = _Service()

    payload = handle_memory_consolidation_task(
        {"task_type": "event_dedupe", "topic": "AI", "dry_run": True},
        service=service,
    )

    assert payload["task_type"] == "event_dedupe"
    assert service.calls[0].topic == "AI"


def test_memory_consolidation_task_handler_returns_task_result() -> None:
    handler = MemoryConsolidationTaskHandler(service=_Service())

    result = handler.handle(Task(task_type="memory.consolidate", payload={"task_type": "event_dedupe"}))

    assert result.success is True
    assert result.output["changed"] == 1


class _Service:
    def __init__(self) -> None:
        self.calls = []

    def run_task(self, task):
        self.calls.append(task)
        return MemoryConsolidationResult(task_type=task.task_type, scanned=2, changed=1)
