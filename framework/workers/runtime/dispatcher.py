from __future__ import annotations

from dataclasses import dataclass, field

from framework.events import (
    EventTelemetry,
    TelemetryInstrumentationScope,
    TelemetryResource,
    TelemetrySpanLink,
    W3CTracePropagator,
    default_event_telemetry,
    trace_context_scope,
)
from framework.workers.models.result import TaskResult
from framework.workers.models.status import TaskStatus
from framework.workers.models.task import Task, TaskError
from framework.workers.registry.registry import TaskHandlerRegistry


@dataclass
class TaskDispatcher:
    registry: TaskHandlerRegistry
    trace_propagator: W3CTracePropagator = field(default_factory=W3CTracePropagator)
    telemetry: EventTelemetry = field(
        default_factory=lambda: default_event_telemetry(
            resource=TelemetryResource(service_name="newsroom-worker"),
            scope=TelemetryInstrumentationScope(
                name="framework.workers",
                version="1",
            ),
        )
    )

    def dispatch(self, task: Task) -> TaskResult:
        extracted = self.trace_propagator.extract_span(task.trace_carrier)
        local_context = extracted.child().context
        attempt_bucket = _attempt_bucket(task.attempts)
        link = TelemetrySpanLink.from_context(
            extracted.remote_context,
            relationship="worker_message",
            attempt_bucket=attempt_bucket,
        )
        handler = self.registry.get(task.task_type)
        if handler is None:
            return TaskResult(
                task_id=task.task_id,
                success=False,
                status=TaskStatus.FAILED,
                error_type="UnknownTaskType",
                error_message=f"no handler for {task.task_type}",
            )
        with trace_context_scope(local_context), self.telemetry.start_span(
            "newsroom.worker.consume",
            attributes={
                "newsroom.component": "worker",
                "newsroom.operation": "consume",
                "newsroom.transport": "worker",
                "newsroom.worker.task_type": task.task_type,
                "newsroom.worker.queue": task.queue_name,
                "newsroom.worker.attempt_bucket": attempt_bucket,
            },
            links=(link,),
        ):
            try:
                return handler.handle(task)
            except Exception as exc:
                error = TaskError(type(exc).__name__, str(exc))
                return TaskResult(
                    task_id=task.task_id,
                    success=False,
                    status=TaskStatus.FAILED,
                    error_type=error.error_type,
                    error_message=error.error_message,
                )


def _attempt_bucket(attempt: int) -> str:
    if attempt <= 1:
        return "first"
    if attempt <= 3:
        return "retry_low"
    return "retry_many"
