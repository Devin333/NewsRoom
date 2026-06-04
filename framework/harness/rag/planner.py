from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.rag.models import (
    RetrievalOperation,
    RetrievalPlanCandidate,
    RetrievalStepSpec,
    RAGSessionSpec,
)
from framework.harness.workers.result import HarnessWorkerResult, HarnessWorkerStatus


@runtime_checkable
class RAGPlanner(Protocol):
    def plan(self, spec: RAGSessionSpec, *, round_index: int, gap_report: dict[str, Any]) -> RetrievalPlanCandidate:
        ...


class DeterministicRAGPlanner:
    def plan(self, spec: RAGSessionSpec, *, round_index: int, gap_report: dict[str, Any]) -> RetrievalPlanCandidate:
        suffix = f"round-{round_index + 1}"
        query_text = spec.goal.question
        if gap_report.get("missing_evidence_types"):
            query_text = f"{query_text} {' '.join(gap_report['missing_evidence_types'])}"
        query_step = RetrievalStepSpec(
            step_id=f"{spec.session_id}:query:{suffix}",
            operation=RetrievalOperation.SEARCH_CORPUS,
            query=query_text,
            corpus=spec.allowed_corpora[0],
            max_results=min(5, max(spec.budget.max_queries, 1)),
            metadata={"scope_ref": spec.source_policy.get("scope_ref")},
        )
        memory_step = RetrievalStepSpec(
            step_id=f"{spec.session_id}:memory:{suffix}",
            operation=RetrievalOperation.RECALL_MEMORY,
            query=query_text,
            memory_namespace=spec.allowed_memory_namespaces[0],
            max_results=_per_round_limit(spec.budget.max_memory_hits, spec.budget.max_rounds, ceiling=3),
            metadata={"scope_ref": spec.source_policy.get("scope_ref")},
        )
        return RetrievalPlanCandidate(
            candidate_id=f"{spec.session_id}:plan:{suffix}",
            queries=(query_step,),
            memory_recall_plan=(memory_step,),
            expected_evidence=spec.goal.required_evidence_types,
            expected_gaps=tuple(gap_report.get("missing_evidence_types", ())),
            risks=("bounded_retrieval_budget",),
            confidence=0.6,
            metadata={"planner": "deterministic"},
        )


class WorkerRAGPlanner:
    def __init__(self, worker: Any, fallback: RAGPlanner | None = None) -> None:
        self.worker = worker
        self.fallback = fallback or DeterministicRAGPlanner()
        self.requests: list[dict[str, Any]] = []

    def plan(self, spec: RAGSessionSpec, *, round_index: int, gap_report: dict[str, Any]) -> RetrievalPlanCandidate:
        request = {
            "task_type": "rag_plan_candidate",
            "session": spec.to_dict(),
            "round_index": round_index,
            "gap_report": dict(gap_report),
            "forbidden_fields": [
                "next_step",
                "quality_passed",
                "write_memory",
                "publish_artifact",
                "halt_workflow",
                "promote_skill",
            ],
        }
        self.requests.append(request)
        result = self._call_worker(request)
        if result.status != HarnessWorkerStatus.SUCCEEDED:
            return self.fallback.plan(spec, round_index=round_index, gap_report=gap_report)
        candidate_payload = result.output.get("candidate") or result.output.get("retrieval_plan_candidate")
        if candidate_payload is None:
            return self.fallback.plan(spec, round_index=round_index, gap_report=gap_report)
        if isinstance(candidate_payload, RetrievalPlanCandidate):
            return candidate_payload
        if not isinstance(candidate_payload, dict):
            raise HarnessValidationError("RAG planner worker returned unsupported candidate payload")
        return RetrievalPlanCandidate.from_dict(candidate_payload)

    def _call_worker(self, request: dict[str, Any]) -> HarnessWorkerResult:
        generate = getattr(self.worker, "generate", None)
        if callable(generate):
            return generate(request)
        execute = getattr(self.worker, "execute", None)
        if callable(execute):
            return execute(request)
        raise HarnessValidationError("RAG planner worker must expose generate or execute")


def _per_round_limit(total: int, rounds: int, *, ceiling: int) -> int:
    return max(1, min(ceiling, total // max(rounds, 1) or total or 1))


__all__ = ["DeterministicRAGPlanner", "RAGPlanner", "WorkerRAGPlanner"]
