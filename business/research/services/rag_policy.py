from __future__ import annotations

from framework.harness.rag.models import RAGBudget, RAGSessionSpec, RetrievalGoal

from business.research.rag.models import ResearchRetrievalGoal


class ResearchRAGPolicyBuilder:
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
                metadata={"paper_id": goal.paper_id, **goal.metadata},
            ),
            allowed_corpora=allowed_corpora,
            allowed_memory_namespaces=tuple(goal.allowed_memory_namespaces),
            allowed_tools=allowed_tools,
            source_policy={"allowed_source_refs": list(goal.allowed_source_refs)},
            budget=budget or RAGBudget.safe_default(),
            context_policy={"projection": "research_rag_context", "stable_prefix": False},
            generation_policy=dict(generation_policy or {}),
            metadata={"paper_id": goal.paper_id},
        )


__all__ = ["ResearchRAGPolicyBuilder"]
