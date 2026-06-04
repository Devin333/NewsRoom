from __future__ import annotations

from business.research.rag import ResearchRetrievalGoal
from business.research.services import ResearchRAGPolicyBuilder


def test_rag_policy_builds_harness_session_spec_without_running_loop() -> None:
    goal = ResearchRetrievalGoal(
        goal_id="goal-1",
        paper_id="paper-1",
        question="Which evidence supports the method claim?",
        required_evidence_types=["section", "claim"],
        target_sections=["sec-method"],
        allowed_source_refs=["paper://paper-1/sec-method"],
        allowed_memory_namespaces=["research:user:user-1"],
    )

    spec = ResearchRAGPolicyBuilder().build_session_spec(
        run_id="run-1",
        workflow_id="research.paper_rag",
        step_id="run_research_rag",
        session_id="rag-1",
        goal=goal,
    )

    payload = spec.to_dict()

    assert payload["goal"]["metadata"]["paper_id"] == "paper-1"
    assert payload["source_policy"]["allowed_source_refs"] == ["paper://paper-1/sec-method"]
    assert payload["context_policy"]["stable_prefix"] is False
    assert payload["budget"]["max_rounds"] > 0
