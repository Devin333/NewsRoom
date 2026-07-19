from __future__ import annotations

from framework.harness.rag.models import RAGBudget, RAGSessionSpec, RetrievalGoal

from business.research.rag.models import ResearchRetrievalGoal


DEFAULT_MIN_RELEVANCE = 0.30
DEFAULT_MIN_RELEVANCE_BY_TYPE = {
    "formula": 0.20,
    "table": 0.20,
}


class ResearchRAGPolicyBuilder:
    def __init__(
        self,
        *,
        min_relevance: float = DEFAULT_MIN_RELEVANCE,
        min_relevance_by_type: dict[str, float] | None = None,
    ) -> None:
        self._min_relevance = float(min_relevance)
        self._min_relevance_by_type = dict(
            DEFAULT_MIN_RELEVANCE_BY_TYPE
            if min_relevance_by_type is None
            else min_relevance_by_type
        )

    def build_session_spec(
        self,
        *,
        run_id: str,
        workflow_id: str,
        step_id: str,
        session_id: str,
        goal: ResearchRetrievalGoal,
        allowed_corpora: tuple[str, ...] = ("research_papers",),
        allowed_tools: tuple[str, ...] = ("retrieval.search", "retrieval.read_source"),
        budget: RAGBudget | None = None,
        generation_policy: dict[str, object] | None = None,
    ) -> RAGSessionSpec:
        scope_metadata = _scope_metadata(goal)
        return RAGSessionSpec(
            session_id=session_id,
            run_id=run_id,
            workflow_id=workflow_id,
            step_id=step_id,
            goal=RetrievalGoal(
                goal_id=goal.goal_id,
                question=goal.question,
                required_evidence_types=tuple(goal.required_evidence_types),
                target_entities=tuple(goal.target_sections + goal.target_claims),
                known_context_refs=tuple(goal.allowed_source_refs),
                constraints=goal.constraints,
                metadata={
                    "paper_id": goal.paper_id,
                    "target_sections": list(goal.target_sections),
                    "target_claims": list(goal.target_claims),
                    **scope_metadata,
                    **goal.metadata,
                },
            ),
            allowed_corpora=allowed_corpora,
            allowed_memory_namespaces=tuple(goal.allowed_memory_namespaces),
            allowed_tools=allowed_tools,
            source_policy={
                "allowed_source_refs": list(goal.allowed_source_refs),
                "min_relevance": self._min_relevance,
                "min_relevance_by_type": dict(self._min_relevance_by_type),
                **scope_metadata,
            },
            budget=budget or RAGBudget.safe_default(),
            context_policy={"projection": "research_rag_context", "stable_prefix": False},
            generation_policy=dict(generation_policy or {}),
            metadata={"paper_id": goal.paper_id, "run_id": run_id, **scope_metadata},
        )


__all__ = [
    "DEFAULT_MIN_RELEVANCE",
    "DEFAULT_MIN_RELEVANCE_BY_TYPE",
    "ResearchRAGPolicyBuilder",
]


def _scope_metadata(goal: ResearchRetrievalGoal) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for key in ("tenant_id", "user_id", "memory_namespace"):
        value = str(goal.metadata.get(key) or "").strip()
        if value:
            metadata[key] = value
    return metadata
