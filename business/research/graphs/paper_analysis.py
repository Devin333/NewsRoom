from __future__ import annotations

from framework.harness.graph import (
    HarnessContractKind,
    HarnessContractReference,
    HarnessGraphDefinition,
    HarnessGraphLeafBinding,
    HarnessGraphSpec,
    HarnessGraphTaskPlanStageBinding,
    HarnessLeafActivityKind,
    HarnessStepSpec,
    HarnessWorkerType,
    ParallelAll,
    ParallelBranch,
    Sequence,
    StepRef,
    VerifiedAggregation,
)
from framework.harness.task_plan.schema import (
    GRAPH_ONLY_VALIDATED_TASK_PLAN_SCHEMA,
)

from business.research.graphs.contracts import (
    RESEARCH_DYNAMIC_INPUT_REFS,
    RESEARCH_DYNAMIC_OUTPUT_ROLES,
    RESEARCH_DYNAMIC_PAPER_ANALYSIS_GRAPH_ID,
    RESEARCH_DYNAMIC_POLICY_REF,
    RESEARCH_DYNAMIC_STAGE_ID,
    RESEARCH_DYNAMIC_TASK_PLAN_SUPPORT_REFS,
    RESEARCH_PAPER_ANALYSIS_GRAPH_ID,
    RESEARCH_PAPER_ANALYSIS_GRAPH_VERSION,
    build_research_artifact_terminal_policy,
)
from business.research.ports.artifact_publication import (
    RESEARCH_ARTIFACT_HANDLER_REF,
)


_GRAPH_INPUT_KEYS = ("paper_id", "source_ref", "memory_namespace")
_GRAPH_TERMINAL_OUTPUT_KEYS = (
    "research_quality",
    "reader_payload",
    "paper_card",
    "artifact_candidate_bundle",
)


def build_paper_analysis_graph_definition() -> HarnessGraphDefinition:
    activities = (
        *_prefix_activities(),
        *_static_analysis_activities(),
        *_suffix_activities(),
    )
    root = HarnessGraphSpec(
        graph_id=RESEARCH_PAPER_ANALYSIS_GRAPH_ID,
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
                        ParallelBranch(
                            "structure",
                            StepRef("analyze_structure"),
                            "analysis.structure",
                        ),
                        ParallelBranch(
                            "contribution",
                            StepRef("analyze_contribution"),
                            "analysis.contribution",
                        ),
                        ParallelBranch(
                            "experiments",
                            StepRef("analyze_experiments"),
                            "analysis.experiments",
                        ),
                    ),
                    merge=VerifiedAggregation(
                        StepRef("verify_claims"),
                        "analysis_branch_refs",
                    ),
                ),
                StepRef("quality_gate"),
                StepRef("build_reader_payload"),
                StepRef("build_paper_card"),
                StepRef("publish_artifacts"),
            )
        ),
        input_keys=_GRAPH_INPUT_KEYS,
        terminal_output_keys=_GRAPH_TERMINAL_OUTPUT_KEYS,
        metadata={"domain": "research", "analysis_mode": "static"},
    )
    return _definition(root=root, activities=activities)


def build_dynamic_paper_analysis_graph_definition() -> (
    HarnessGraphDefinition
):
    activities = (
        *_prefix_activities(),
        HarnessStepSpec(
            step_id=RESEARCH_DYNAMIC_STAGE_ID,
            worker_type=HarnessWorkerType.TASK_PLAN,
            input_keys=RESEARCH_DYNAMIC_INPUT_REFS,
            output_key="analysis_branch_refs",
        ),
        *_suffix_activities(),
    )
    root = HarnessGraphSpec(
        graph_id=RESEARCH_DYNAMIC_PAPER_ANALYSIS_GRAPH_ID,
        root=Sequence(
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
        ),
        input_keys=_GRAPH_INPUT_KEYS,
        terminal_output_keys=_GRAPH_TERMINAL_OUTPUT_KEYS,
        metadata={"domain": "research", "analysis_mode": "dynamic"},
    )
    return _definition(
        root=root,
        activities=activities,
        task_plan_stage_bindings=(
            HarnessGraphTaskPlanStageBinding(
                activity_id=RESEARCH_DYNAMIC_STAGE_ID,
                worker_ref=_contract_reference(
                    HarnessContractKind.WORKER,
                    RESEARCH_DYNAMIC_STAGE_ID,
                ),
                activity_ref=_contract_reference(
                    HarnessContractKind.ACTIVITY,
                    RESEARCH_DYNAMIC_STAGE_ID,
                ),
                policy_ref=RESEARCH_DYNAMIC_POLICY_REF,
                task_plan_schema=GRAPH_ONLY_VALIDATED_TASK_PLAN_SCHEMA,
                required_output_roles=RESEARCH_DYNAMIC_OUTPUT_ROLES,
                support_refs=RESEARCH_DYNAMIC_TASK_PLAN_SUPPORT_REFS,
            ),
        ),
    )


def _definition(
    *,
    root: HarnessGraphSpec,
    activities: tuple[HarnessStepSpec, ...],
    task_plan_stage_bindings: tuple[
        HarnessGraphTaskPlanStageBinding, ...
    ] = (),
) -> HarnessGraphDefinition:
    return HarnessGraphDefinition(
        graph_id=root.graph_id,
        graph_version=RESEARCH_PAPER_ANALYSIS_GRAPH_VERSION,
        root=root,
        activities=activities,
        leaf_activity_bindings=tuple(
            _leaf_binding(activity)
            for activity in activities
            if activity.worker_type is not HarnessWorkerType.TASK_PLAN
        ),
        task_plan_stage_bindings=task_plan_stage_bindings,
        committed_output_bindings=(),
        repair_bindings=(),
        terminal_side_effect_policy=(
            build_research_artifact_terminal_policy()
        ),
    )


def _prefix_activities() -> tuple[HarnessStepSpec, ...]:
    return (
        HarnessStepSpec(
            step_id="load_paper_source",
            worker_type=HarnessWorkerType.FUNCTION,
            input_keys=("paper_id", "source_ref"),
            output_key="paper_source",
            quality_gate="PaperSourceLineageGate@1",
        ),
        HarnessStepSpec(
            step_id="compile_document",
            worker_type=HarnessWorkerType.FUNCTION,
            input_keys=("paper_source",),
            output_key="document",
            quality_gate="ResearchDocumentSchemaGate@1",
        ),
        HarnessStepSpec(
            step_id="run_research_rag",
            worker_type=HarnessWorkerType.FUNCTION,
            input_keys=("document", "memory_namespace"),
            output_key="research_rag_context",
            quality_gate="ResearchRAGContextProjectionGate@1",
        ),
        HarnessStepSpec(
            step_id="build_evidence_pack",
            worker_type=HarnessWorkerType.FUNCTION,
            input_keys=("document", "research_rag_context"),
            output_key="evidence_pack",
            quality_gate="ResearchEvidenceCoverageGate@1",
        ),
    )


def _static_analysis_activities() -> tuple[HarnessStepSpec, ...]:
    return (
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
    )


def _suffix_activities() -> tuple[HarnessStepSpec, ...]:
    return (
        HarnessStepSpec(
            step_id="verify_claims",
            worker_type=HarnessWorkerType.FUNCTION,
            input_keys=("evidence_pack", "analysis_branch_refs"),
            output_key="claim_verification",
            quality_gate="ClaimEvidenceGate@1",
        ),
        HarnessStepSpec(
            step_id="quality_gate",
            worker_type=HarnessWorkerType.FUNCTION,
            input_keys=("claim_verification",),
            output_key="research_quality",
            quality_gate="ResearchQualityGate@1",
        ),
        HarnessStepSpec(
            step_id="build_reader_payload",
            worker_type=HarnessWorkerType.FUNCTION,
            input_keys=("document", "evidence_pack", "research_quality"),
            output_key="reader_payload",
            quality_gate="ReaderPayloadSchemaGate@1",
        ),
        HarnessStepSpec(
            step_id="build_paper_card",
            worker_type=HarnessWorkerType.FUNCTION,
            input_keys=("paper_source", "reader_payload", "research_quality"),
            output_key="paper_card",
            quality_gate="ResearchPaperCardGate@1",
        ),
        HarnessStepSpec(
            step_id="publish_artifacts",
            worker_type=HarnessWorkerType.FUNCTION,
            input_keys=("reader_payload", "paper_card", "research_quality"),
            output_key="artifact_candidate_bundle",
            side_effect_handler=RESEARCH_ARTIFACT_HANDLER_REF,
            metadata={
                "candidate_only": True,
                "output_schema": {
                    "required": ["artifact_bundle_ref", "artifact_types"],
                    "properties": {
                        "artifact_bundle_ref": {"type": "string"},
                        "artifact_types": {"type": "array"},
                    },
                },
            },
        ),
    )


def _leaf_binding(activity: HarnessStepSpec) -> HarnessGraphLeafBinding:
    return HarnessGraphLeafBinding(
        activity_id=activity.step_id,
        leaf_activity_kind=HarnessLeafActivityKind(
            activity.worker_type.value
        ),
        worker_ref=_contract_reference(
            HarnessContractKind.WORKER,
            activity.step_id,
        ),
        activity_ref=_contract_reference(
            HarnessContractKind.ACTIVITY,
            activity.step_id,
        ),
    )


def _contract_reference(
    kind: HarnessContractKind,
    activity_id: str,
) -> HarnessContractReference:
    return HarnessContractReference(
        kind,
        f"research.paper_analysis.{activity_id}",
        "1",
    )


__all__ = [
    "build_dynamic_paper_analysis_graph_definition",
    "build_paper_analysis_graph_definition",
]
