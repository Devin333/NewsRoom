from __future__ import annotations

from backend.research.rag import ResearchRetrievalGoal
from backend.research.graphs import build_paper_analysis_context_graph_identity
from backend.research.services import ResearchRAGPolicyBuilder


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
        graph_identity=build_paper_analysis_context_graph_identity(
            run_id="run-1",
            stage_id="run_research_rag",
        ),
        session_id="rag-1",
        goal=goal,
    )

    payload = spec.to_dict()

    assert payload["goal"]["metadata"]["paper_id"] == "paper-1"
    assert payload["source_policy"]["allowed_source_refs"] == ["paper://paper-1/sec-method"]
    assert payload["context_policy"]["stable_prefix"] is False
    assert payload["graph_identity"]["graph_id"] == "research.paper_analysis.graph"
    assert payload["budget"]["max_rounds"] > 0
