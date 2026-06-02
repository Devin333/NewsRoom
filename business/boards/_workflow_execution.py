from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from business.boards._workflow_runtime import BoardWorkflowExecution, stage_result


StageResultT = TypeVar("StageResultT")
StageMetric = int | None | Callable[[StageResultT], int | None]
StageWarnings = list[str] | None | Callable[[StageResultT], list[str] | None]
StageMetadata = dict[str, Any] | None | Callable[[StageResultT], dict[str, Any] | None]


@dataclass
class BoardWorkflowRunState:
    execution: BoardWorkflowExecution
    publish: Callable[[BoardWorkflowExecution], None]

    def __post_init__(self) -> None:
        self.publish(self.execution)

    def run_stage(
        self,
        stage_name: str,
        operation: Callable[[], StageResultT],
        *,
        input_count: int | None = None,
        output_count: StageMetric = None,
        warnings: StageWarnings = None,
        metadata: StageMetadata = None,
    ) -> StageResultT:
        started_at = _utc_now()
        try:
            result = operation()
        except Exception as exc:
            self._record_failed_stage(stage_name, started_at, exc)
            raise
        self._record_completed_stage(
            stage_name,
            started_at,
            input_count=input_count,
            output_count=_resolve_stage_value(output_count, result),
            warnings=_resolve_stage_value(warnings, result) or [],
            metadata=_resolve_stage_value(metadata, result) or {},
        )
        return result

    def finish(self) -> BoardWorkflowExecution:
        self.execution = self.execution.finish()
        self.publish(self.execution)
        return self.execution

    def _record_completed_stage(
        self,
        stage_name: str,
        started_at,
        *,
        input_count: int | None,
        output_count: int | None,
        warnings: list[str],
        metadata: dict[str, Any],
    ) -> None:
        self.execution = self.execution.add_stage(
            stage_result(
                stage_name,
                started_at=started_at,
                input_count=input_count,
                output_count=output_count,
                warnings=warnings,
                metadata=metadata,
            )
        )
        self.publish(self.execution)

    def _record_failed_stage(self, stage_name: str, started_at, exc: BaseException) -> None:
        self.execution = self.execution.add_stage(
            stage_result(
                stage_name,
                started_at=started_at,
                error=exc,
            )
        ).finish()
        self.publish(self.execution)


def _resolve_stage_value(
    value: StageMetric | StageWarnings | StageMetadata,
    result: StageResultT,
):
    if callable(value):
        return value(result)
    return value


def _utc_now():
    from datetime import datetime, timezone as _tz

    return datetime.now(_tz.utc)


__all__ = ["BoardWorkflowRunState"]
