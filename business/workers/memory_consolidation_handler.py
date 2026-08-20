from __future__ import annotations

import os
from typing import Any

from business.memory.consolidation import MemoryConsolidationService, MemoryConsolidationTask
from framework.workers.models import Task, TaskResult, TaskStatus


class MemoryConsolidationTaskHandler:
    task_type = "memory.consolidate"

    def __init__(self, service: MemoryConsolidationService | None = None) -> None:
        self.service = service

    def handle(self, task: Task) -> TaskResult:
        result = handle_memory_consolidation_task(task.payload, service=self.service)
        return TaskResult(
            task_id=task.task_id,
            success=True,
            status=TaskStatus.SUCCEEDED,
            execution_scope=task.execution_scope,
            graph_identity=task.graph_identity,
            run_status="succeeded",
            output=result,
        )


def handle_memory_consolidation_task(
    payload: dict[str, Any],
    *,
    service: MemoryConsolidationService | None = None,
) -> dict[str, Any]:
    task = parse_memory_consolidation_task(payload)
    resolved_service = service or build_memory_consolidation_service()
    return resolved_service.run_task(task).to_dict()


def parse_memory_consolidation_task(payload: dict[str, Any]) -> MemoryConsolidationTask:
    return MemoryConsolidationTask(
        task_type=payload["task_type"],
        topic=payload.get("topic"),
        entity_id=payload.get("entity_id"),
        dry_run=_parse_bool(payload.get("dry_run", True), field_name="dry_run"),
        limit=int(payload.get("limit", 100)),
        metadata=dict(payload.get("metadata") or {}),
    )


def build_memory_consolidation_service() -> MemoryConsolidationService:
    if os.environ.get("NEWS_MEMORY_POSTGRES_ENABLED", "").lower() not in {"1", "true", "yes", "on"}:
        raise ValueError("NEWS_MEMORY_POSTGRES_ENABLED is required for memory consolidation")
    dsn = os.environ.get("NEWS_DATABASE_DSN")
    if not dsn:
        raise ValueError("NEWS_DATABASE_DSN is required for memory consolidation")
    from infrastructure.storage.postgres.memory_repository import PostgresIntelligenceMemoryRepository
    from infrastructure.storage.postgres.repository import PostgresRepository

    return MemoryConsolidationService(PostgresIntelligenceMemoryRepository(PostgresRepository(dsn)))


def _parse_bool(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    raise ValueError(f"{field_name} must be a boolean")


__all__ = [
    "MemoryConsolidationTaskHandler",
    "build_memory_consolidation_service",
    "handle_memory_consolidation_task",
    "parse_memory_consolidation_task",
]
