from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from pathlib import Path
from typing import Any, Callable

from backend.layers.output.worker_handlers import MemoryReindexTaskHandler
from backend.layers.signal.worker_handlers import SourceHealthCheckTaskHandler
from framework.events import (
    EventTelemetry,
    TelemetryInstrumentationScope,
    TelemetryResource,
    TelemetrySpanLink,
    W3CTracePropagator,
    default_event_telemetry,
    trace_context_scope,
)
from framework.shared.attempts import (
    AdmissionResult,
    AttemptContext,
    AttemptLifecycleSink,
    AttemptOutcome,
    AttemptState,
    AttemptSupervisor,
    CompositeAttemptLifecycleSink,
    DeadlineAdmissionPolicy,
    ExecutionLimits,
    LocalRetryBudget,
    RetryCreditLedger,
    current_attempt_context,
)
from framework.shared.public_errors import project_public_error, sanitize_public_error_fields
from framework.execution_environment.composition import RuntimeExecutionComposition
from framework.workers import (
    LeasedTask,
    StaleTaskLeaseError,
    Task,
    TaskError,
    TaskResult,
    TaskStatus,
    WorkerExecutionScope,
    WorkerHeartbeat,
    WorkerHeartbeatStatus,
    WorkerExecutionPolicy,
    WorkerStatus,
)
from framework.workers.registry.handler import TaskHandler
from infrastructure.storage.workers import (
    RedisQueueStatus,
    RedisStreamTaskQueue,
    RedisWorkerRegistry,
)
from interfaces.services.memory_service import MemoryApplicationService
from interfaces.services.source_service import SourceApplicationService
from interfaces.services.source_runtime import SourceRuntimeProvider


DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
DEFAULT_MEMORY_QUEUE = "news:queue:memory"
DEFAULT_SOURCE_QUEUE = "news:queue:sources"
DEFAULT_DEAD_LETTER_QUEUE = "news:queue:dead-letter"
WORKER_STATUS_CHOICES = tuple(status.value for status in WorkerStatus)
DEFAULT_WORKER_STATUS = WorkerStatus.RUNNING.value


class _WorkerAttemptTelemetrySink:
    """Mirror worker attempt facts onto a failure-isolated telemetry span."""

    required = False

    def __init__(self, span: Any) -> None:
        self._span = span

    def _add_event(self, name: str, attributes: dict[str, Any]) -> None:
        try:
            self._span.add_event(name, attributes)
        except Exception:
            return

    def rejected(
        self,
        *,
        operation_id: str,
        operation_kind: str,
        idempotency_key: str,
        admission: AdmissionResult,
    ) -> None:
        if operation_kind != "worker_handler":
            return
        self._add_event(
            "attempt_admission_rejected",
            {
                "newsroom.attempt.operation_id": operation_id,
                "newsroom.attempt.operation_kind": operation_kind,
                "newsroom.attempt.idempotency_key": idempotency_key,
                "newsroom.attempt.started": False,
                "newsroom.attempt.reason_code": admission.reason_code or "unknown",
            },
        )

    def started(self, *, context: AttemptContext) -> None:
        if context.operation_kind != "worker_handler":
            return
        self._add_event(
            "attempt_started",
            {
                "newsroom.attempt.operation_id": context.operation_id or "unknown",
                "newsroom.attempt.operation_kind": context.operation_kind,
                "newsroom.attempt.idempotency_key": context.idempotency_key,
                "newsroom.attempt.attempt_id": context.attempt_id,
                "newsroom.attempt.local_attempt_no": context.local_attempt_no,
            },
        )

    def terminal(self, *, outcome: AttemptOutcome[object]) -> None:
        context = outcome.context
        if context is None or context.operation_kind != "worker_handler":
            return
        self._add_event(
            "attempt_terminal",
            {
                "newsroom.attempt.operation_id": context.operation_id or "unknown",
                "newsroom.attempt.operation_kind": context.operation_kind,
                "newsroom.attempt.attempt_id": context.attempt_id,
                "newsroom.attempt.state": outcome.state.value,
                "newsroom.attempt.termination_confirmed": (
                    outcome.termination_confirmed
                ),
                "newsroom.attempt.indeterminate": outcome.indeterminate,
            },
        )


@dataclass(frozen=True)
class EnqueuedTaskResult:
    task: Task
    message_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": str(self.message_id),
            "task_id": self.task.task_id,
            "task_type": self.task.task_type,
            "queue_name": self.task.queue_name,
            "status": self.task.status.value,
            "topic": self.task.payload.get("topic"),
            "run_id": self.task.payload.get("run_id"),
            "force": self.task.payload.get("force"),
            "limit": self.task.payload.get("limit"),
        }


@dataclass(frozen=True)
class WorkerRunOnceResult:
    processed: bool
    worker_id: str
    reclaimed: bool = False
    queue_name: str | None = None
    message_id: str | None = None
    task_id: str | None = None
    task_type: str | None = None
    success: bool | None = None
    retryable: bool | None = None
    task_status: TaskStatus | None = None
    graph_identity: Any | None = None
    error_type: str | None = None
    error_message: str | None = None
    error_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "processed": self.processed,
            "worker_id": self.worker_id,
            "reclaimed": self.reclaimed,
            "queue_name": self.queue_name,
            "message_id": self.message_id,
            "task_id": self.task_id,
            "task_type": self.task_type,
            "success": self.success,
            "retryable": self.retryable,
            "task_status": self.task_status.value if self.task_status else None,
            "graph_identity": (
                self.graph_identity.to_dict()
                if hasattr(self.graph_identity, "to_dict")
                else self.graph_identity
            ),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "error_id": self.error_id,
        }


@dataclass(frozen=True)
class WorkerHeartbeatResult:
    worker: WorkerHeartbeatStatus

    def to_dict(self) -> dict[str, Any]:
        return {"worker": self.worker.to_dict()}


@dataclass(frozen=True)
class WorkerStatusResult:
    workers: list[WorkerHeartbeatStatus]
    stale_after_seconds: int
    worker_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        worker_payloads = [worker.to_dict() for worker in self.workers]
        return {
            "worker_id": self.worker_id,
            "worker_count": len(worker_payloads),
            "unhealthy_count": sum(1 for worker in self.workers if worker.status == WorkerStatus.UNHEALTHY),
            "stale_after_seconds": self.stale_after_seconds,
            "workers": worker_payloads,
        }


@dataclass(frozen=True)
class WorkerQueueStatusResult:
    queues: list[RedisQueueStatus]

    def to_dict(self) -> dict[str, Any]:
        queue_payloads = [queue.to_dict() for queue in self.queues]
        return {
            "queue_count": len(queue_payloads),
            "total_stream_length": sum(queue["stream_length"] for queue in queue_payloads),
            "total_pending_count": sum(queue["pending_count"] for queue in queue_payloads),
            "queues": queue_payloads,
        }


@dataclass(frozen=True)
class WorkerRunLoopResult:
    worker_id: str
    iterations: int
    processed_count: int
    succeeded_count: int
    failed_count: int
    idle_count: int
    stop_reason: str
    last_result: WorkerRunOnceResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "iterations": self.iterations,
            "processed_count": self.processed_count,
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "idle_count": self.idle_count,
            "stop_reason": self.stop_reason,
            "last_result": self.last_result.to_dict() if self.last_result else None,
        }


class WorkerApplicationService:
    def __init__(
        self,
        *,
        artifact_root: str | Path = ".newsroom/runs",
        redis_url: str | None = None,
        queue: RedisStreamTaskQueue | None = None,
        worker_registry: RedisWorkerRegistry | None = None,
        handlers: dict[str, TaskHandler] | None = None,
        source_service_factory: Callable[[], SourceApplicationService] | None = None,
        source_runtime_provider: SourceRuntimeProvider | None = None,
        trace_propagator: W3CTracePropagator | None = None,
        telemetry: EventTelemetry | None = None,
        attempt_event_sink_factory: Callable[
            [LeasedTask, ExecutionLimits], AttemptLifecycleSink | None
        ]
        | None = None,
        runtime_execution_composition: RuntimeExecutionComposition | None = None,
    ) -> None:
        if source_service_factory is not None and source_runtime_provider is not None:
            raise ValueError(
                "source_service_factory and source_runtime_provider are mutually exclusive"
            )
        if runtime_execution_composition is None:
            from interfaces.composition.runtime_execution import (
                build_process_execution_composition,
            )

            runtime_execution_composition = build_process_execution_composition()
        if not isinstance(runtime_execution_composition, RuntimeExecutionComposition):
            raise TypeError(
                "runtime_execution_composition must be RuntimeExecutionComposition"
            )
        runtime_execution_composition.verify_integrity()
        self._runtime_execution_composition = runtime_execution_composition
        self.artifact_root = Path(artifact_root)
        redis_client = None
        if queue is None:
            redis_client = _redis_client_from_url(redis_url)
        self.queue = queue or RedisStreamTaskQueue(redis_client, dead_letter_queue_name=DEFAULT_DEAD_LETTER_QUEUE)
        self.worker_registry = worker_registry
        if self.worker_registry is None and queue is None:
            self.worker_registry = RedisWorkerRegistry(redis_client)
        self._handlers = handlers
        self._source_runtime_provider = source_runtime_provider
        if source_service_factory is None:
            self._source_runtime_provider = (
                source_runtime_provider or SourceRuntimeProvider()
            )
            self._source_service_factory = (
                self._source_runtime_provider.source_service_factory
            )
        else:
            self._source_service_factory = source_service_factory
        self._trace_propagator = trace_propagator or W3CTracePropagator()
        self._telemetry = telemetry or default_event_telemetry(
            resource=TelemetryResource(service_name="newsroom-worker"),
            scope=TelemetryInstrumentationScope(
                name="interfaces.worker-service",
                version="1",
            ),
        )
        self._attempt_event_sink_factory = attempt_event_sink_factory

    @property
    def runtime_execution_composition(self) -> RuntimeExecutionComposition:
        return self._runtime_execution_composition

    @property
    def handlers(self) -> dict[str, TaskHandler]:
        if self._handlers is None:
            self._handlers = self._build_default_handlers()
        return self._handlers

    def _build_default_handlers(self) -> dict[str, TaskHandler]:
        return {
            MemoryReindexTaskHandler.task_type: MemoryReindexTaskHandler(
                memory_service=MemoryApplicationService(artifact_root=self.artifact_root)
            ),
            SourceHealthCheckTaskHandler.task_type: SourceHealthCheckTaskHandler(
                source_service=self._source_service_factory()
            ),
        }

    def enqueue_memory_reindex(
        self,
        *,
        run_id: str,
        topic: str | None = None,
        queue_name: str = DEFAULT_MEMORY_QUEUE,
    ) -> EnqueuedTaskResult:
        payload: dict[str, Any] = {"run_id": run_id}
        if topic:
            payload["topic"] = topic
        _reject_secret_payload_keys(payload)
        task = Task(
            task_type=MemoryReindexTaskHandler.task_type,
            queue_name=queue_name,
            payload=payload,
            execution_scope=WorkerExecutionScope.STANDALONE,
        )
        message_id = self.queue.enqueue(task)
        return EnqueuedTaskResult(task=task, message_id=str(message_id))

    def enqueue_source_health_check(
        self,
        *,
        source_id: str | None = None,
        include_disabled: bool = False,
        limit: int | None = None,
        force: bool = False,
        queue_name: str = DEFAULT_SOURCE_QUEUE,
    ) -> EnqueuedTaskResult:
        payload: dict[str, Any] = {
            "include_disabled": include_disabled,
            "force": force,
        }
        if source_id:
            payload["source_id"] = source_id
        if limit is not None:
            if limit <= 0:
                raise ValueError("limit must be greater than zero")
            payload["limit"] = limit
        _reject_secret_payload_keys(payload)
        task = Task(
            task_type=SourceHealthCheckTaskHandler.task_type,
            queue_name=queue_name,
            payload=payload,
            execution_scope=WorkerExecutionScope.STANDALONE,
        )
        message_id = self.queue.enqueue(task)
        return EnqueuedTaskResult(task=task, message_id=str(message_id))

    def run_once(
        self,
        *,
        worker_id: str,
        queue_names: list[str] | None = None,
        block_ms: int = 1000,
        reclaim_stale_ms: int | None = None,
    ) -> WorkerRunOnceResult:
        queues = queue_names or [DEFAULT_MEMORY_QUEUE]
        self._record_worker_heartbeat(
            worker_id=worker_id,
            queue_names=queues,
            status=WorkerStatus.RUNNING,
        )
        leased = self.queue.lease_one(worker_id, queues, block_ms=block_ms)
        reclaimed = False
        if leased is None and reclaim_stale_ms is not None:
            leased = self.queue.reclaim_stale_one(
                worker_id,
                queues,
                min_idle_ms=reclaim_stale_ms,
            )
            reclaimed = leased is not None
        if leased is None:
            self._record_worker_heartbeat(
                worker_id=worker_id,
                queue_names=queues,
                status=WorkerStatus.RUNNING,
            )
            return WorkerRunOnceResult(processed=False, worker_id=worker_id)

        self._record_worker_heartbeat(
            worker_id=worker_id,
            queue_names=queues,
            status=WorkerStatus.RUNNING,
            current_task_id=leased.task.task_id,
        )
        result, lease_failure = self._handle_leased_task(leased)
        if lease_failure is not None:
            result = _task_result_from_exception(leased.task, lease_failure, retryable=False)
        else:
            try:
                if result.success:
                    self._ack_leased_task(leased)
                else:
                    self._fail_leased_task(leased, result)
            except StaleTaskLeaseError as exc:
                result = _task_result_from_exception(leased.task, exc, retryable=False)
        self._record_worker_heartbeat(
            worker_id=worker_id,
            queue_names=queues,
            status=WorkerStatus.RUNNING,
            processed_increment=1 if result.success else 0,
            failed_increment=0 if result.success else 1,
        )
        return WorkerRunOnceResult(
            processed=True,
            worker_id=worker_id,
            reclaimed=reclaimed,
            queue_name=leased.queue_name,
            message_id=leased.message_id,
            task_id=leased.task.task_id,
            task_type=leased.task.task_type,
            success=result.success,
            retryable=result.retryable,
            task_status=result.status,
            graph_identity=result.graph_identity,
            error_type=result.error_type,
            error_message=result.error_message,
            error_id=result.error_id,
        )

    def record_heartbeat(
        self,
        *,
        worker_id: str,
        queue_names: list[str] | None = None,
        status: WorkerStatus | str = WorkerStatus.RUNNING,
        current_task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> WorkerHeartbeatResult:
        worker = self._record_worker_heartbeat(
            worker_id=worker_id,
            queue_names=queue_names or [DEFAULT_MEMORY_QUEUE],
            status=status,
            current_task_id=current_task_id,
            metadata=metadata,
            now=now,
        )
        return WorkerHeartbeatResult(
            worker=WorkerHeartbeatStatus.from_record(
                worker,
                now=now,
                stale_after_seconds=60,
            )
        )

    def list_worker_status(
        self,
        *,
        worker_id: str | None = None,
        stale_after_seconds: int = 60,
        now: datetime | None = None,
    ) -> WorkerStatusResult:
        registry = self._require_worker_registry()
        if stale_after_seconds < 0:
            raise ValueError("stale_after_seconds must be non-negative")
        if worker_id:
            record = registry.get(worker_id)
            records = [record] if record else []
        else:
            records = registry.list()
        reference = _coerce_datetime(now)
        return WorkerStatusResult(
            worker_id=worker_id,
            stale_after_seconds=stale_after_seconds,
            workers=[
                WorkerHeartbeatStatus.from_record(
                    record,
                    now=reference,
                    stale_after_seconds=stale_after_seconds,
                )
                for record in records
            ],
        )

    def queue_status(self, *, queue_names: list[str] | None = None) -> WorkerQueueStatusResult:
        queues = _unique_queue_names(
            queue_names
            or [DEFAULT_MEMORY_QUEUE, DEFAULT_SOURCE_QUEUE, DEFAULT_DEAD_LETTER_QUEUE]
        )
        return WorkerQueueStatusResult(queues=self.queue.status(queues))

    def run_loop(
        self,
        *,
        worker_id: str,
        queue_names: list[str] | None = None,
        block_ms: int = 1000,
        reclaim_stale_ms: int | None = None,
        max_tasks: int | None = None,
        max_idle_polls: int | None = None,
        idle_sleep_seconds: float = 1.0,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> WorkerRunLoopResult:
        if max_tasks is not None and max_tasks <= 0:
            raise ValueError("max_tasks must be greater than zero")
        if max_idle_polls is not None and max_idle_polls <= 0:
            raise ValueError("max_idle_polls must be greater than zero")
        if idle_sleep_seconds < 0:
            raise ValueError("idle_sleep_seconds must be non-negative")

        actual_sleep = sleep_fn or time.sleep
        iterations = 0
        processed_count = 0
        succeeded_count = 0
        failed_count = 0
        idle_count = 0
        last_result: WorkerRunOnceResult | None = None

        while True:
            result = self.run_once(
                worker_id=worker_id,
                queue_names=queue_names,
                block_ms=block_ms,
                reclaim_stale_ms=reclaim_stale_ms,
            )
            last_result = result
            iterations += 1
            if result.processed:
                processed_count += 1
                if result.success:
                    succeeded_count += 1
                else:
                    failed_count += 1
                if max_tasks is not None and processed_count >= max_tasks:
                    return WorkerRunLoopResult(
                        worker_id=worker_id,
                        iterations=iterations,
                        processed_count=processed_count,
                        succeeded_count=succeeded_count,
                        failed_count=failed_count,
                        idle_count=idle_count,
                        stop_reason="max_tasks",
                        last_result=last_result,
                    )
                continue

            idle_count += 1
            if max_idle_polls is not None and idle_count >= max_idle_polls:
                return WorkerRunLoopResult(
                    worker_id=worker_id,
                    iterations=iterations,
                    processed_count=processed_count,
                    succeeded_count=succeeded_count,
                    failed_count=failed_count,
                    idle_count=idle_count,
                    stop_reason="max_idle_polls",
                    last_result=last_result,
                )
            if idle_sleep_seconds:
                actual_sleep(idle_sleep_seconds)

    def _handle_leased_task(self, leased: LeasedTask) -> tuple[TaskResult, BaseException | None]:
        if (
            leased.task.execution_scope is not WorkerExecutionScope.STANDALONE
            or leased.task.graph_identity is not None
        ):
            return _sanitize_task_result(
                TaskResult(
                    task_id=leased.task.task_id,
                    success=False,
                    retryable=False,
                    status=TaskStatus.FAILED,
                    execution_scope=leased.task.execution_scope,
                    graph_identity=leased.task.graph_identity,
                    error_type="WorkerExecutionScopeMismatch",
                    error_message=(
                        "WorkerApplicationService only executes explicitly standalone tasks"
                    ),
                )
            ), None
        handler = self.handlers.get(leased.task.task_type)
        if handler is None:
            return _sanitize_task_result(
                TaskResult(
                    task_id=leased.task.task_id,
                    success=False,
                    retryable=False,
                    status=TaskStatus.FAILED,
                    execution_scope=leased.task.execution_scope,
                    graph_identity=leased.task.graph_identity,
                    error_type="UnknownTaskType",
                    error_message=f"no handler for {leased.task.task_type}",
                )
            ), None
        try:
            if "max_total_attempts" in leased.task.metadata:
                raise ValueError(
                    "legacy max_total_attempts requires explicit migration to "
                    "max_total_retries"
                )
            raw_policy = leased.task.metadata.get("execution_policy")
            if raw_policy is not None and not isinstance(raw_policy, dict):
                raise ValueError("worker execution_policy must be an object")
            policy = WorkerExecutionPolicy.from_mapping(raw_policy)
            timeout_seconds = (
                float(leased.task.timeout_seconds)
                if leased.task.timeout_seconds is not None
                else None
            )
            policy.validate_timeout(timeout_seconds)
        except (TypeError, ValueError) as exc:
            return _sanitize_task_result(
                TaskResult(
                    task_id=leased.task.task_id,
                    success=False,
                    retryable=False,
                    status=TaskStatus.FAILED,
                    execution_scope=leased.task.execution_scope,
                    graph_identity=leased.task.graph_identity,
                    error_type="InvalidWorkerExecutionPolicy",
                    error_message=str(exc),
                )
            ), exc

        logical_key = leased.effect_key or f"task:{leased.task.task_id}"
        execution_limits = ExecutionLimits(
            execution_id=f"worker:{leased.task.task_id}:{leased.lease_id or leased.message_id}",
            hard_deadline=(
                time.monotonic() + timeout_seconds
                if timeout_seconds is not None
                else None
            ),
            retry_credits=RetryCreditLedger(
                max_total_retries=policy.max_total_retries
            ),
            cancellation_grace_seconds=policy.cancellation_grace_seconds,
            verify_reserve_seconds=policy.verify_reserve_seconds,
            commit_reserve_seconds=policy.commit_reserve_seconds,
        )
        extracted_trace = self._trace_propagator.extract_span(
            leased.task.trace_carrier
        )
        consumer_trace = extracted_trace.child().context
        attempt_bucket = _worker_attempt_bucket(leased.task.attempts)
        trace_link = TelemetrySpanLink.from_context(
            extracted_trace.remote_context,
            relationship="worker_message",
            attempt_bucket=attempt_bucket,
        )
        stop_renewal = threading.Event()
        renewal_failures: list[BaseException] = []
        renewal_thread_holder: list[threading.Thread] = []
        renewal_cleanup_lock = threading.Lock()
        renewal_cleanup_done = False

        def stop_lease_renewal_once() -> None:
            nonlocal renewal_cleanup_done
            with renewal_cleanup_lock:
                if renewal_cleanup_done:
                    return
                stop_renewal.set()
                unconfirmed_threads: list[str] = []
                for renewal_thread in tuple(renewal_thread_holder):
                    renewal_thread.join(timeout=1.0)
                    if renewal_thread.is_alive():
                        unconfirmed_threads.append(renewal_thread.name)
                if unconfirmed_threads:
                    raise RuntimeError(
                        "worker lease renewal cleanup did not terminate: "
                        + ", ".join(unconfirmed_threads)
                    )
                renewal_cleanup_done = True

        def prepare_handler(_identity: Any) -> Callable[[], None]:
            renewal_thread = self._start_lease_renewer(
                leased,
                cancel_event=execution_limits.cancel_event,
                stop_event=stop_renewal,
                failures=renewal_failures,
            )
            if renewal_thread is not None:
                renewal_thread_holder.append(renewal_thread)
            return stop_lease_renewal_once

        def invoke_handler() -> TaskResult:
            context = current_attempt_context()
            if context is None:
                raise RuntimeError("worker handler is missing attempt context")
            with trace_context_scope(consumer_trace), self._telemetry.start_span(
                "newsroom.worker.consume",
                attributes={
                    "newsroom.component": "worker",
                    "newsroom.operation": "consume",
                    "newsroom.transport": "worker",
                    "newsroom.worker.task_type": leased.task.task_type,
                    "newsroom.worker.queue": leased.task.queue_name,
                    "newsroom.worker.attempt_bucket": attempt_bucket,
                },
                links=(trace_link,),
            ):
                result = handler.handle(leased.task)
                context.raise_if_cancelled()
                return result

        def finalize_handler_attempt(
            outcome: AttemptOutcome[TaskResult],
        ) -> AttemptOutcome[TaskResult]:
            stop_lease_renewal_once()
            if renewal_failures:
                failure = renewal_failures[0]
                return replace(
                    outcome,
                    state=AttemptState.INDETERMINATE,
                    value=None,
                    error=failure,
                    indeterminate=True,
                    reason_code=type(failure).__name__,
                )
            if outcome.state is not AttemptState.SUCCEEDED:
                return outcome
            result = outcome.value
            if not isinstance(result, TaskResult):
                error = TypeError("worker handler must return TaskResult")
                return replace(
                    outcome,
                    state=AttemptState.FAILED,
                    value=None,
                    error=error,
                    reason_code=type(error).__name__,
                )
            if result.success and result.status is TaskStatus.SUCCEEDED:
                if (
                    result.execution_scope is not leased.task.execution_scope
                    or result.graph_identity != leased.task.graph_identity
                ):
                    error = ValueError(
                        "worker handler result identity does not match the leased task"
                    )
                    normalized = TaskResult(
                        task_id=leased.task.task_id,
                        success=False,
                        retryable=False,
                        status=TaskStatus.FAILED,
                        execution_scope=leased.task.execution_scope,
                        graph_identity=leased.task.graph_identity,
                        error_type="WorkerTaskIdentityMismatch",
                        error_message=str(error),
                    )
                    return replace(
                        outcome,
                        state=AttemptState.FAILED,
                        value=normalized,
                        error=error,
                        reason_code="worker_task_identity_mismatch",
                    )
                return outcome
            if result.success or result.status is not TaskStatus.FAILED:
                error = ValueError(
                    "worker handler returned inconsistent TaskResult success/status"
                )
                normalized = TaskResult(
                    task_id=leased.task.task_id,
                    success=False,
                    retryable=False,
                    status=TaskStatus.FAILED,
                    execution_scope=leased.task.execution_scope,
                    graph_identity=leased.task.graph_identity,
                    error_type="WorkerTaskResultInconsistent",
                    error_message=(
                        "worker handler result must use success=true/status=succeeded "
                        "or success=false/status=failed"
                    ),
                )
                return replace(
                    outcome,
                    state=AttemptState.FAILED,
                    value=normalized,
                    error=error,
                    reason_code="worker_task_result_inconsistent",
                )
            error = RuntimeError(
                result.error_message
                or result.error_type
                or "worker handler returned a failed TaskResult"
            )
            return replace(
                outcome,
                state=AttemptState.FAILED,
                value=result,
                error=error,
                reason_code=result.error_type or "worker_task_failed",
            )

        try:
            custom_attempt_sink = (
                self._attempt_event_sink_factory(leased, execution_limits)
                if self._attempt_event_sink_factory is not None
                else None
            )
            with self._telemetry.start_span(
                "newsroom.worker.attempt",
                attributes={
                    "newsroom.component": "worker",
                    "newsroom.operation": "attempt",
                    "newsroom.transport": "worker",
                    "newsroom.worker.task_type": leased.task.task_type,
                    "newsroom.worker.queue": leased.task.queue_name,
                    "newsroom.worker.attempt_bucket": attempt_bucket,
                },
                links=(trace_link,),
            ) as attempt_span:
                telemetry_attempt_sink = _WorkerAttemptTelemetrySink(attempt_span)
                attempt_sink = (
                    CompositeAttemptLifecycleSink(
                        (custom_attempt_sink, telemetry_attempt_sink)
                    )
                    if custom_attempt_sink is not None
                    else telemetry_attempt_sink
                )
                outcome = AttemptSupervisor(
                    cancellation_grace_seconds=policy.cancellation_grace_seconds
                ).run(
                    invoke_handler,
                    timeout_seconds=timeout_seconds,
                    idempotency_key=logical_key,
                    operation_id=logical_key,
                    operation_kind="worker_handler",
                    local_budget=LocalRetryBudget(max_attempts=1),
                    admission_policy=DeadlineAdmissionPolicy(
                        timeout_seconds=timeout_seconds,
                        min_start_window_seconds=policy.min_start_window_seconds,
                        cancellation_grace_seconds=policy.cancellation_grace_seconds,
                        completion_reserve_seconds=policy.completion_reserve_seconds,
                        admission_details={
                            "task_id": leased.task.task_id,
                            "task_type": leased.task.task_type,
                        },
                    ),
                    execution_limits=execution_limits,
                    cancel_event=execution_limits.cancel_event,
                    prepare=prepare_handler,
                    finalize=finalize_handler_attempt,
                    event_sink=attempt_sink,
                )
            if outcome.state is AttemptState.REJECTED:
                exc = outcome.error or RuntimeError(
                    "worker handler admission rejected without an error"
                )
                return _task_result_from_exception(
                    leased.task,
                    exc,
                    retryable=False,
                ), exc
            if outcome.state is AttemptState.SUCCEEDED:
                result = outcome.value
                if not isinstance(result, TaskResult):
                    raise TypeError("worker handler must return TaskResult")
            elif outcome.state is AttemptState.FAILED:
                if isinstance(outcome.value, TaskResult):
                    result = outcome.value
                else:
                    exc = outcome.error or RuntimeError(
                        "worker handler failed without an error"
                    )
                    result = _task_result_from_exception(leased.task, exc)
            else:
                exc = outcome.error or TimeoutError(
                    "worker handler did not terminate deterministically"
                )
                result = _task_result_from_exception(
                    leased.task,
                    exc,
                    retryable=(
                        outcome.termination_confirmed
                        and not outcome.indeterminate
                    ),
                )
        finally:
            stop_lease_renewal_once()
        if renewal_failures:
            return _task_result_from_exception(
                leased.task,
                renewal_failures[0],
                retryable=False,
            ), renewal_failures[0]
        return _sanitize_task_result(result), None

    def _start_lease_renewer(
        self,
        leased: LeasedTask,
        *,
        cancel_event: threading.Event,
        stop_event: threading.Event,
        failures: list[BaseException],
    ) -> threading.Thread | None:
        renew = getattr(self.queue, "renew", None)
        if not leased.is_fenced or not callable(renew):
            return None
        interval_fn = getattr(self.queue, "renewal_interval_seconds", None)
        interval = float(interval_fn(leased)) if callable(interval_fn) else 1.0
        if interval <= 0:
            raise ValueError("lease renewal interval must be greater than zero")

        def renewal_loop() -> None:
            while not stop_event.wait(interval):
                try:
                    renew(leased)
                except BaseException as exc:  # noqa: BLE001 - ownership loss is fail-closed
                    failures.append(exc)
                    cancel_event.set()
                    return

        thread = threading.Thread(
            target=renewal_loop,
            daemon=True,
            name=f"worker-lease-renewer:{leased.task.task_id[:24]}",
        )
        thread.start()
        return thread

    def _ack_leased_task(self, leased: LeasedTask) -> None:
        if leased.is_fenced:
            self.queue.ack(leased)
            return
        self.queue.ack(leased.queue_name, leased.message_id)

    def _fail_leased_task(self, leased: LeasedTask, result: TaskResult) -> None:
        if leased.is_fenced:
            self.queue.fail(
                leased,
                TaskError(
                    result.error_type or "WorkerInternalError",
                    result.error_message or "task execution failed",
                    retryable=result.retryable,
                    error_id=result.error_id,
                ),
            )
            return
        self._requeue_or_dead_letter(leased.task, result)
        self.queue.ack(leased.queue_name, leased.message_id)

    def _requeue_or_dead_letter(self, task: Task, result: TaskResult) -> None:
        reason = result.error_message or result.error_type or "task failed"
        if not result.retryable or task.attempts >= task.max_attempts:
            self.queue.move_to_dead_letter(task, reason)
            return
        task.status = TaskStatus.FAILED
        self.queue.enqueue(task)

    def _record_worker_heartbeat(
        self,
        *,
        worker_id: str,
        queue_names: list[str],
        status: WorkerStatus | str,
        current_task_id: str | None = None,
        processed_increment: int = 0,
        failed_increment: int = 0,
        metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> WorkerHeartbeat:
        registry = self.worker_registry
        if registry is None:
            return WorkerHeartbeat(
                worker_id=worker_id,
                queue_names=_unique_queue_names(queue_names),
                status=WorkerStatus(status),
                started_at=_coerce_datetime(now),
                last_heartbeat_at=_coerce_datetime(now),
                current_task_id=current_task_id,
            )
        reference = _coerce_datetime(now)
        existing = registry.get(worker_id)
        previous_metadata = existing.metadata if existing else {}
        worker = WorkerHeartbeat(
            worker_id=worker_id,
            queue_names=_unique_queue_names(queue_names or (existing.queue_names if existing else [])),
            status=WorkerStatus(status),
            started_at=existing.started_at if existing else reference,
            last_heartbeat_at=reference,
            current_task_id=current_task_id,
            processed_count=(existing.processed_count if existing else 0) + processed_increment,
            failed_count=(existing.failed_count if existing else 0) + failed_increment,
            metadata={**previous_metadata, **(metadata or {})},
        )
        registry.save(worker)
        return worker

    def _require_worker_registry(self) -> RedisWorkerRegistry:
        if self.worker_registry is None:
            raise RuntimeError("worker registry is not configured")
        return self.worker_registry


def _redis_client_from_url(redis_url: str | None):
    import redis

    url = redis_url or os.environ.get("NEWS_REDIS_URL", DEFAULT_REDIS_URL)
    return redis.from_url(url, decode_responses=True)


def _coerce_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _worker_attempt_bucket(attempt: int) -> str:
    if attempt <= 1:
        return "first"
    if attempt <= 3:
        return "retry_low"
    return "retry_many"


def _unique_queue_names(queue_names: list[str]) -> list[str]:
    return list(dict.fromkeys(str(queue_name) for queue_name in queue_names))


def _task_result_from_exception(
    task: Task,
    exc: BaseException,
    *,
    retryable: bool = True,
) -> TaskResult:
    projection = project_public_error(exc, context="worker", operation=task.task_type)
    return TaskResult(
        task_id=task.task_id,
        success=False,
        retryable=retryable,
        status=TaskStatus.FAILED,
        execution_scope=task.execution_scope,
        graph_identity=task.graph_identity,
        error_type=projection.error_type,
        error_message=projection.error_message,
        error_id=projection.error_id,
    )


def _sanitize_task_result(result: TaskResult) -> TaskResult:
    if result.success:
        return result
    fields = sanitize_public_error_fields(
        error_type=result.error_type,
        error_message=result.error_message,
        error_id=result.error_id,
        context="worker",
    )
    return TaskResult(
        task_id=result.task_id,
        success=False,
        retryable=result.retryable,
        status=result.status,
        execution_scope=result.execution_scope,
        graph_identity=result.graph_identity,
        task_status=result.task_status,
        run_status=result.run_status,
        report_status=result.report_status,
        output={},
        error_type=str(fields["error_type"]),
        error_message=str(fields["error_message"]),
        error_id=fields["error_id"],
        finished_at=result.finished_at,
    )


def _reject_secret_payload_keys(payload: dict[str, Any]) -> None:
    secret_fragments = (
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
    )
    for key in payload:
        normalized = key.lower().replace("-", "_")
        if any(fragment in normalized for fragment in secret_fragments):
            raise ValueError(f"task payload key is not allowed: {key}")
