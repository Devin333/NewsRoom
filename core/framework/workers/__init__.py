"""Worker and task queue primitives."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORT_MODULES = {
    "ApprovalAlreadyDecidedError": "core.framework.workers.approval",
    "ApprovalDecision": "core.framework.workers.approval",
    "ApprovalDecisionType": "core.framework.workers.approval",
    "ApprovalNotFoundError": "core.framework.workers.approval",
    "ApprovalRequest": "core.framework.workers.approval",
    "ApprovalResumeContext": "core.framework.workers.approval",
    "ApprovalStatus": "core.framework.workers.approval",
    "ApprovalStore": "core.framework.workers.approval",
    "BackpressurePolicy": "core.framework.workers.models",
    "DailyIntelligenceTaskHandler": "core.framework.workers.handlers",
    "DeadLetterRecord": "core.framework.workers.models",
    "EnqueuedScheduleTask": "core.framework.workers.scheduler",
    "InMemoryApprovalStore": "core.framework.workers.approval",
    "InMemoryScheduleStore": "core.framework.workers.schedule_store",
    "InMemoryTaskQueue": "core.framework.workers.in_memory",
    "LeasedTask": "core.framework.workers.models",
    "MemoryReindexTaskHandler": "core.framework.workers.handlers",
    "MisfirePolicy": "core.framework.workers.scheduler",
    "RedisStreamTaskQueue": "core.framework.workers.redis_queue",
    "RedisQueueConsumerStatus": "core.framework.workers.redis_queue",
    "RedisQueueStatus": "core.framework.workers.redis_queue",
    "RedisWorkerRegistry": "core.framework.workers.heartbeat",
    "QueueStatus": "core.framework.workers.models",
    "ScheduleEvaluation": "core.framework.workers.scheduler",
    "ScheduleNotFoundError": "core.framework.workers.schedule_store",
    "ScheduleRecord": "core.framework.workers.schedule_store",
    "ScheduleSpec": "core.framework.workers.scheduler",
    "ScheduleStore": "core.framework.workers.schedule_store",
    "ScheduleTriggerType": "core.framework.workers.scheduler",
    "Scheduler": "core.framework.workers.scheduler",
    "SchedulerTickResult": "core.framework.workers.scheduler",
    "SourceHealthCheckTaskHandler": "core.framework.workers.handlers",
    "Task": "core.framework.workers.models",
    "TaskEnqueueResult": "core.framework.workers.models",
    "TaskEvent": "core.framework.workers.models",
    "TaskError": "core.framework.workers.models",
    "TaskRecord": "core.framework.workers.models",
    "TaskRetryPolicy": "core.framework.workers.models",
    "TaskResult": "core.framework.workers.models",
    "TaskStatus": "core.framework.workers.models",
    "WorkerHeartbeat": "core.framework.workers.heartbeat",
    "WorkerHeartbeatStatus": "core.framework.workers.heartbeat",
    "WorkerLoop": "core.framework.workers.worker_loop",
    "WorkerLoopRunResult": "core.framework.workers.worker_loop",
    "WorkerMetrics": "core.framework.workers.models",
    "WorkerRecord": "core.framework.workers.models",
    "WorkerStatus": "core.framework.workers.heartbeat",
    "build_approval_resume_context": "core.framework.workers.approval",
}

__all__ = list(_EXPORT_MODULES)


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
