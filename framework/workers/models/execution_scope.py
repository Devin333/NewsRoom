from __future__ import annotations

from enum import StrEnum


class WorkerExecutionScope(StrEnum):
    """Execution authority carried by a worker task.

    Graph work must be admitted by the Graph worker runtime. Standalone work is
    reserved for explicit background capabilities that are not Graph nodes.
    """

    GRAPH = "graph"
    STANDALONE = "standalone"


__all__ = ["WorkerExecutionScope"]
