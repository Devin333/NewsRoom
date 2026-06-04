from __future__ import annotations

from business.research.agent_intelligence import AgentSkillToolIntelligence, validate_agent_intelligence


def test_agent_intelligence_expresses_graph_without_skill_mutation() -> None:
    intelligence = AgentSkillToolIntelligence(
        intelligence_id="agent-intel-1",
        task_type="paper analysis",
        representative_papers=["paper-1"],
        methods=["Harness Control"],
        benchmarks=["reader repair benchmark"],
        high_scoring_skills=["summary_candidate_worker"],
        tools=["retrieval.read_source"],
        failure_modes=["unsupported claim"],
        evidence_refs=["paper://paper-1/sec-agent"],
        confidence=0.8,
    )

    results = validate_agent_intelligence(intelligence)

    assert intelligence.to_dict()["task_type"] == "paper_analysis"
    assert all(result.passed for result in results)


def test_agent_intelligence_blocks_active_skill_mutation() -> None:
    intelligence = AgentSkillToolIntelligence(
        intelligence_id="agent-intel-2",
        task_type="paper analysis",
        evidence_refs=["paper://paper-1/sec-agent"],
        metadata={"active_skill_mutation": True},
    )

    results = validate_agent_intelligence(intelligence)

    assert any(result.gate_name == "AgentSkillMutationGate" and not result.passed for result in results)
