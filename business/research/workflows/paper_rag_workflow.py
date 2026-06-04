from __future__ import annotations

from framework.harness.workflow import HarnessRoutingRule, HarnessStepSpec, HarnessWorkerType, HarnessWorkflowSpec


def build_paper_rag_workflow_spec() -> HarnessWorkflowSpec:
    steps = (
        HarnessStepSpec(
            step_id="build_retrieval_goal",
            worker_type=HarnessWorkerType.SCRIPT,
            output_key="research_retrieval_goal",
            quality_gate="ResearchRetrievalGoalGate",
        ),
        HarnessStepSpec(
            step_id="plan_retrieval",
            worker_type=HarnessWorkerType.SUBAGENT,
            input_keys=("research_retrieval_goal",),
            output_key="retrieval_plan_candidate",
            quality_gate="RetrievalPlanSchemaGate",
        ),
        HarnessStepSpec(
            step_id="verify_retrieval_plan",
            worker_type=HarnessWorkerType.QUALITY_GATE,
            input_keys=("research_retrieval_goal", "retrieval_plan_candidate"),
            output_key="retrieval_plan_verdict",
            quality_gate="ResearchRAGSourceScopeGate",
        ),
        HarnessStepSpec(
            step_id="execute_retrieval_round",
            worker_type=HarnessWorkerType.RETRIEVAL,
            input_keys=("retrieval_plan_verdict",),
            output_key="rag_round_result",
            quality_gate="BoundedRAGBudgetGate",
        ),
        HarnessStepSpec(
            step_id="verify_rag_sources",
            worker_type=HarnessWorkerType.QUALITY_GATE,
            input_keys=("research_retrieval_goal", "rag_round_result"),
            output_key="rag_source_verdict",
            quality_gate="ResearchRAGSourceScopeGate",
        ),
        HarnessStepSpec(
            step_id="assemble_research_context",
            worker_type=HarnessWorkerType.SCRIPT,
            input_keys=("rag_round_result", "rag_source_verdict"),
            output_key="research_rag_context",
            quality_gate="ResearchRAGContextProjectionGate",
        ),
        HarnessStepSpec(
            step_id="verify_research_context",
            worker_type=HarnessWorkerType.QUALITY_GATE,
            input_keys=("research_rag_context",),
            output_key="research_context_verdict",
            quality_gate="ResearchEvidenceCoverageGate",
        ),
        HarnessStepSpec(
            step_id="project_to_evidence_pack",
            worker_type=HarnessWorkerType.SCRIPT,
            input_keys=("research_rag_context",),
            output_key="evidence_pack",
            quality_gate="ResearchEvidencePackGate",
        ),
    )
    return HarnessWorkflowSpec(
        workflow_id="research.paper_rag",
        steps=steps,
        entry_step_id="build_retrieval_goal",
        routing_rules=tuple(HarnessRoutingRule(from_step=left.step_id, to_step=right.step_id) for left, right in zip(steps, steps[1:])),
        metadata={
            "scope": "business_projection_only",
            "generic_loop_owner": "framework.harness.rag",
        },
    )


__all__ = ["build_paper_rag_workflow_spec"]
