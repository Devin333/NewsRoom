from __future__ import annotations

from importlib import import_module
from typing import Any

from framework.workers.runtime.backpressure import BackpressurePolicy


_EXPORT_MODULES = {
    "InMemoryWorkerHeartbeatStore": "framework.workers.runtime.heartbeat",
    "LeaseManager": "framework.workers.runtime.leasing",
    "TaskDispatcher": "framework.workers.runtime.dispatcher",
    "WorkerHeartbeat": "framework.workers.runtime.heartbeat",
    "WorkerHeartbeatStatus": "framework.workers.runtime.heartbeat",
    "WorkerLoop": "framework.workers.runtime.worker_loop",
    "WorkerLoopRunResult": "framework.workers.runtime.worker_loop",
    "WorkerRunner": "framework.workers.runtime.runner",
}

__all__ = ["BackpressurePolicy", *_EXPORT_MODULES]


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
