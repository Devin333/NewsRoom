from __future__ import annotations

from dataclasses import replace

from framework.harness.graph import (
    HarnessGraphSpec,
    HarnessStepSpec,
    HarnessWorkerType,
    ParallelAll,
    ParallelBranch,
    Sequence,
    StepRef,
    VerifiedAggregation,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec

from business.research.ports.artifact_publication import (
    RESEARCH_ARTIFACT_HANDLER_REF,
)
from business.research.graphs.contracts import (
    RESEARCH_ARTIFACT_NOT_REQUIRED_EVIDENCE_REF,
    RESEARCH_ARTIFACT_TERMINAL_POLICY_ID,
    RESEARCH_ARTIFACT_TERMINAL_POLICY_VERSION,
    RESEARCH_DYNAMIC_AGGREGATOR_REF,
    RESEARCH_DYNAMIC_CAPABILITY_REGISTRY_REF,
    RESEARCH_DYNAMIC_CANDIDATE_BUILDER_REF,
    RESEARCH_DYNAMIC_GATE_REGISTRY_REF,
    RESEARCH_DYNAMIC_OUTPUT_ROLES,
    RESEARCH_DYNAMIC_POLICY_REF,
    RESEARCH_DYNAMIC_RESULT_STORE_REF,
    RESEARCH_DYNAMIC_STAGE_ID,
    build_research_artifact_terminal_policy,
)


def build_paper_analysis_workflow_spec() -> HarnessWorkflowSpec:
    steps = (
        HarnessStepSpec(
            step_id="load_paper_source",
            worker_type=HarnessWorkerType.SCRIPT,
            output_key="paper_source",
            quality_gate="PaperSourceLineageGate@1",
        ),
        HarnessStepSpec(
            step_id="compile_document",
            worker_type=HarnessWorkerType.SCRIPT,
            input_keys=("paper_source",),
            output_key="document",
            quality_gate="ResearchDocumentSchemaGate@1",
        ),
        HarnessStepSpec(
            step_id="run_research_rag",
            worker_type=HarnessWorkerType.RETRIEVAL,
            input_keys=("document",),
            output_key="research_rag_context",
            quality_gate="ResearchRAGContextProjectionGate@1",
        ),
        HarnessStepSpec(
            step_id="build_evidence_pack",
            worker_type=HarnessWorkerType.SCRIPT,
            input_keys=("document", "research_rag_context"),
            output_key="evidence_pack",
            quality_gate="ResearchEvidenceCoverageGate@1",
        ),
        HarnessStepSpec(
            step_id="analyze_structure",
            worker_type=HarnessWorkerType.SUBAGENT,
            input_keys=("document", "evidence_pack"),
            output_key="structure_candidate",
            quality_gate="SummarySchemaGate@1",
        ),
        HarnessStepSpec(
            step_id="analyze_contribution",
            worker_type=HarnessWorkerType.SUBAGENT,
            input_keys=("document", "evidence_pack"),
            output_key="contribution_candidate",
            quality_gate="SummaryEvidenceCoverageGate@1",
        ),
        HarnessStepSpec(
            step_id="analyze_experiments",
            worker_type=HarnessWorkerType.SUBAGENT,
            input_keys=("document", "evidence_pack"),
            output_key="experiment_candidate",
            quality_gate="BenchmarkEvidenceLineageGate@1",
        ),
        HarnessStepSpec(
            step_id="verify_claims",
            worker_type=HarnessWorkerType.QUALITY_GATE,
            input_keys=("evidence_pack", "analysis_branch_refs"),
            output_key="claim_verification",
            quality_gate="ClaimEvidenceGate@1",
        ),
        HarnessStepSpec(
            step_id="quality_gate",
            worker_type=HarnessWorkerType.QUALITY_GATE,
            input_keys=("claim_verification",),
            output_key="research_quality",
            quality_gate="ResearchQualityGate@1",
        ),
        HarnessStepSpec(
            step_id="build_reader_payload",
            worker_type=HarnessWorkerType.SCRIPT,
            input_keys=("document", "evidence_pack", "research_quality"),
            output_key="reader_payload",
            quality_gate="ReaderPayloadSchemaGate@1",
        ),
        HarnessStepSpec(
            step_id="build_paper_card",
            worker_type=HarnessWorkerType.SCRIPT,
            input_keys=("paper_source", "reader_payload", "research_quality"),
            output_key="paper_card",
            quality_gate="ResearchPaperCardGate@1",
        ),
        HarnessStepSpec(
            step_id="publish_artifacts",
            worker_type=HarnessWorkerType.ARTIFACT,
            input_keys=("reader_payload", "paper_card", "research_quality"),
            output_key="artifact_refs",
            side_effect_handler=RESEARCH_ARTIFACT_HANDLER_REF,
            metadata={
                "output_schema": {
                    "required": ["artifact_bundle_ref", "artifact_types"],
                    "properties": {
                        "artifact_bundle_ref": {"type": "string"},
                        "artifact_types": {"type": "array"},
                    },
                },
                "approval_required": False,
            },
        ),
    )
    return HarnessWorkflowSpec(
        workflow_id="research.paper_analysis",
        steps=steps,
        entry_step_id="load_paper_source",
        graph=HarnessGraphSpec(
            graph_id="research.paper_analysis.graph",
            root=Sequence(
                (
                    StepRef("load_paper_source"),
                    StepRef("compile_document"),
                    StepRef("run_research_rag"),
                    StepRef("build_evidence_pack"),
                    ParallelAll(
                        fork_id="analysis_fork",
                        join_id="analysis_join",
                        branches=(
                            ParallelBranch("structure", StepRef("analyze_structure"), "analysis.structure"),
                            ParallelBranch("contribution", StepRef("analyze_contribution"), "analysis.contribution"),
                            ParallelBranch("experiments", StepRef("analyze_experiments"), "analysis.experiments"),
                        ),
                        merge=VerifiedAggregation(StepRef("verify_claims"), "analysis_branch_refs"),
                    ),
                    StepRef("quality_gate"),
                    StepRef("build_reader_payload"),
                    StepRef("build_paper_card"),
                    StepRef("publish_artifacts"),
                )
            ),
        ),
        terminal_policies={"publish_requires_verify": True},
        terminal_side_effect_policy=build_research_artifact_terminal_policy(),
        metadata={"scope": "harness_side_effect_authority"},
    )


def build_dynamic_paper_analysis_workflow_spec() -> HarnessWorkflowSpec:
    """Return the opt-in Research workflow with a stage-local TaskPlan DAG.

    The outer graph remains frozen and keeps the same evidence, claim
    verification, quality and publication boundaries as the static workflow.
    Only the analysis fan-out is replaced by the explicitly typed dynamic
    stage.
    """

    static = build_paper_analysis_workflow_spec()
    dynamic_step = HarnessStepSpec(
        step_id=RESEARCH_DYNAMIC_STAGE_ID,
        worker_type=HarnessWorkerType.TASK_PLAN,
        input_keys=("document", "evidence_pack"),
        output_key="analysis_branch_refs",
        metadata={
            "dynamic_stage": True,
            "task_plan_policy_ref": RESEARCH_DYNAMIC_POLICY_REF,
            "required_output_roles": list(RESEARCH_DYNAMIC_OUTPUT_ROLES),
            "task_plan_schema": "newsroom.harness-task-plan/v1",
            "task_plan_support": {
                "candidate_builder_ref": RESEARCH_DYNAMIC_CANDIDATE_BUILDER_REF,
                "capability_registry_ref": RESEARCH_DYNAMIC_CAPABILITY_REGISTRY_REF,
                "gate_registry_ref": RESEARCH_DYNAMIC_GATE_REGISTRY_REF,
                "aggregator_ref": RESEARCH_DYNAMIC_AGGREGATOR_REF,
                "event_schema": "newsroom.harness-task-plan-event/v1",
                "checkpoint_ref": "harness.graph-checkpoint@1",
                "result_store_ref": RESEARCH_DYNAMIC_RESULT_STORE_REF,
            },
        },
    )
    steps = tuple(
        step for step in static.steps
        if step.step_id not in {"analyze_structure", "analyze_contribution", "analyze_experiments"}
    )
    steps = steps[:4] + (dynamic_step,) + steps[4:]
    root = Sequence(
        (
            StepRef("load_paper_source"),
            StepRef("compile_document"),
            StepRef("run_research_rag"),
            StepRef("build_evidence_pack"),
            StepRef(RESEARCH_DYNAMIC_STAGE_ID),
            StepRef("verify_claims"),
            StepRef("quality_gate"),
            StepRef("build_reader_payload"),
            StepRef("build_paper_card"),
            StepRef("publish_artifacts"),
        )
    )
    return replace(
        static,
        workflow_id="research.paper_analysis.dynamic",
        steps=steps,
        graph=replace(
            static.graph,
            graph_id="research.paper_analysis.dynamic.graph",
            root=root,
        ),
        metadata={**static.metadata, "dynamic_task_plan": True, "version": "1"},
        workflow_version="1",
    )
__all__ = [
    "RESEARCH_ARTIFACT_NOT_REQUIRED_EVIDENCE_REF",
    "RESEARCH_ARTIFACT_TERMINAL_POLICY_ID",
    "RESEARCH_ARTIFACT_TERMINAL_POLICY_VERSION",
    "build_paper_analysis_workflow_spec",
    "build_dynamic_paper_analysis_workflow_spec",
]
