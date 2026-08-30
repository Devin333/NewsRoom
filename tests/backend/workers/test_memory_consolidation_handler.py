from backend.memory.consolidation import MemoryConsolidationResult
import pytest

from backend.workers.memory_consolidation_handler import (
    MemoryConsolidationTaskHandler,
    build_memory_consolidation_service,
    handle_memory_consolidation_task,
    parse_memory_consolidation_task,
)
from framework.workers.models import Task


def test_parse_memory_consolidation_task_defaults_to_dry_run() -> None:
    task = parse_memory_consolidation_task({"task_type": "event_dedupe", "topic": "AI"})

    assert task.task_type == "event_dedupe"
    assert task.topic == "AI"
    assert task.dry_run is True
    assert task.limit == 100


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("false", False),
        ("0", False),
        (True, True),
        ("yes", True),
    ],
)
def test_parse_memory_consolidation_task_parses_dry_run_bool_values(raw_value, expected) -> None:
    task = parse_memory_consolidation_task({"task_type": "event_dedupe", "dry_run": raw_value})

    assert task.dry_run is expected


def test_parse_memory_consolidation_task_rejects_invalid_dry_run_string() -> None:
    with pytest.raises(ValueError, match="dry_run must be a boolean"):
        parse_memory_consolidation_task({"task_type": "event_dedupe", "dry_run": "maybe"})


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


def test_memory_consolidation_service_builder_requires_explicit_postgres_env(monkeypatch) -> None:
    monkeypatch.delenv("NEWS_MEMORY_POSTGRES_ENABLED", raising=False)
    monkeypatch.delenv("NEWS_DATABASE_DSN", raising=False)

    with pytest.raises(ValueError, match="NEWS_MEMORY_POSTGRES_ENABLED"):
        build_memory_consolidation_service()


class _Service:
    def __init__(self) -> None:
        self.calls = []

    def run_task(self, task):
        self.calls.append(task)
        return MemoryConsolidationResult(task_type=task.task_type, scanned=2, changed=1)
