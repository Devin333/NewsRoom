from __future__ import annotations

from typing import Any

from framework.harness.workers.result import HarnessWorkerResult, HarnessWorkerStatus

from business.research.ports.llm_worker import ResearchCandidateWorkerPort


class ResearchRAGPlanWorker:
    """Adapts Research candidate workers to the Harness RAG planner worker shape."""

    def __init__(self, worker: ResearchCandidateWorkerPort) -> None:
        self._worker = worker

    def generate(self, request: dict[str, Any]) -> HarnessWorkerResult:
        try:
            output = self._worker.generate_candidate(
                task="rag_plan_candidate",
                payload=request,
            )
        except Exception as exc:  # pragma: no cover - defensive adapter boundary
            return HarnessWorkerResult(
                status=HarnessWorkerStatus.FAILED,
                output={},
                error=str(exc),
            )
        if not isinstance(output, dict):
            return HarnessWorkerResult(
                status=HarnessWorkerStatus.FAILED,
                output={},
                error="Research candidate worker returned a non-dict planner payload",
            )
        return HarnessWorkerResult(
            status=HarnessWorkerStatus.SUCCEEDED,
            output=output,
        )


__all__ = ["ResearchRAGPlanWorker"]
