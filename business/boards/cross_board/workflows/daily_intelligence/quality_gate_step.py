from __future__ import annotations

from typing import Any

from framework.workflow import DataBufferReadPermissionError, StepScopedDataBufferView
from business.boards.cross_board.workflows.daily_intelligence.quality_gate_usecase import (
    DailyQualityGateInput,
    evaluate_daily_quality_gate,
)
from business.boards.cross_board.workflows.daily_intelligence.workflow_buffer_access import (
    read_buffer_list,
)
from business.memory.intelligence_repository import IntelligenceMemoryQueryRepository


def quality_gate(
    buffer: StepScopedDataBufferView,
    *,
    memory_repository: IntelligenceMemoryQueryRepository | None = None,
) -> dict[str, Any]:
    return evaluate_daily_quality_gate(
        DailyQualityGateInput(
            report_draft=buffer.read("report_draft"),
            evidence_bundle=buffer.read("evidence_bundle"),
            verified_findings=buffer.read("verified_findings"),
            quality_events=read_buffer_list(buffer, "quality_events"),
            memory_context=_read_optional_dict(buffer, "memory_context"),
            historian_context=_read_optional_dict(buffer, "historian_context"),
            memory_repository=_read_memory_query_repository(buffer, memory_repository),
        )
    )


def _read_optional_dict(buffer: StepScopedDataBufferView, key: str) -> dict[str, Any] | None:
    try:
        if not buffer.exists(key):
            return None
        value = buffer.read(key, required=False)
    except DataBufferReadPermissionError:
        return None
    return dict(value) if isinstance(value, dict) else None


def _read_memory_query_repository(
    buffer: StepScopedDataBufferView,
    injected_repository: IntelligenceMemoryQueryRepository | None,
) -> IntelligenceMemoryQueryRepository | None:
    if injected_repository is not None:
        return injected_repository
    try:
        if not buffer.exists("memory_query_repository"):
            return None
        return buffer.read("memory_query_repository", required=False)
    except DataBufferReadPermissionError:
        return None
