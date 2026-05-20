from __future__ import annotations

from dataclasses import dataclass

from framework.workers.runtime.worker_loop import WorkerLoop, WorkerLoopRunResult


@dataclass
class WorkerRunner:
    loop: WorkerLoop

    def run_once(self) -> WorkerLoopRunResult:
        return self.loop.run_once_result()

    def run_forever(self) -> WorkerLoopRunResult:
        return self.loop.run_forever()
