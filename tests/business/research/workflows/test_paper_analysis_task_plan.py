from __future__ import annotations

from dataclasses import replace

import pytest

from business.research.workflows import (
    RESEARCH_DYNAMIC_AGGREGATOR_REF,
    RESEARCH_DYNAMIC_CAPABILITIES,
    RESEARCH_DYNAMIC_GATE_REFS,
    RESEARCH_DYNAMIC_GATES_BY_CAPABILITY,
    RESEARCH_DYNAMIC_OUTPUT_ROLES_BY_CAPABILITY,
    RESEARCH_DYNAMIC_OUTPUT_SCHEMA_REFS,
    RESEARCH_DYNAMIC_WORKER_CONTRACT_REFS,
    RESEARCH_DYNAMIC_WORKER_REFS,
    ResearchAnalysisPlanCandidateBuilder,
    build_paper_analysis_gate_registry,
    build_research_analysis_capability_registry,
    build_research_analysis_task_plan_aggregator,
    build_research_analysis_task_plan_policy,
    validate_research_analysis_candidate,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.task_plan import (
    PlanBuildRequest,
    PlanCandidate,
    TaskAcceptanceCriteria,
    TaskBudget,
    TaskLifecycle,
    TaskResultRecord,
)
from framework.harness.task_plan.canonical import canonical_payload_checksum
from framework.harness.graph.bindings import HarnessWorkerBinding
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
)
from framework.harness.graph.activity import HarnessWorkerType
from framework.harness.workers.result import HarnessWorkerResult


class _BoundResearchWorker:
    worker_version = "1"
    worker_type = HarnessWorkerType.SUBAGENT

    def __init__(self, capability: str) -> None:
        self.worker_id = capability

    def execute(self, _task):
        return HarnessWorkerResult(status="succeeded", output={"candidate": {}})


class _OutlineWorker:
    def __init__(self, outline: dict[str, object]) -> None:
        self.outline = outline
        self.calls: list[tuple[str, dict[str, object]]] = []

    def generate_candidate(self, *, task: str, payload: dict[str, object]):
        self.calls.append((task, payload))
        return self.outline


def test_policy_pins_existing_research_gates_workers_and_subagents() -> None:
    policy = build_research_analysis_task_plan_policy()
    gate_registry = build_paper_analysis_gate_registry()

    assert policy.pinned_capability_bindings == RESEARCH_DYNAMIC_WORKER_REFS
    assert (
        policy.required_worker_contract_refs
        == RESEARCH_DYNAMIC_WORKER_CONTRACT_REFS
    )
    assert policy.metadata["stage_aggregator_ref"] == RESEARCH_DYNAMIC_AGGREGATOR_REF
    assert all(gate_registry.bindings_for(ref) for ref in RESEARCH_DYNAMIC_GATE_REFS)
    assert set(policy.allowed_subagent_ids) == {
        "research_analysis_structure",
        "research_analysis_contribution",
        "research_analysis_experiments",
    }


def test_capability_registry_requires_every_exact_subagent_binding() -> None:
    bindings = _worker_bindings()
    registry = build_research_analysis_capability_registry(bindings)
    policy = build_research_analysis_task_plan_policy()

    for capability in RESEARCH_DYNAMIC_CAPABILITIES:
        resolved = registry.resolve(capability, policy)
        assert resolved.worker_ref == RESEARCH_DYNAMIC_WORKER_REFS[capability]
        assert resolved.worker_contract_ref == (
            RESEARCH_DYNAMIC_WORKER_CONTRACT_REFS[capability]
        )
        assert resolved.subagent_spec is not None
        assert resolved.subagent_spec.metadata["gate_refs"] == list(
            RESEARCH_DYNAMIC_GATES_BY_CAPABILITY[capability]
        )

    missing = dict(bindings)
    missing.pop(RESEARCH_DYNAMIC_CAPABILITIES[0])
    with pytest.raises(HarnessValidationError) as exc_info:
        build_research_analysis_capability_registry(missing)
    assert exc_info.value.code == (
        "research_task_plan_capability_bindings_incomplete"
    )


def test_candidate_builder_accepts_only_outline_and_pins_control_fields() -> None:
    worker = _OutlineWorker(_valid_outline())
    policy = build_research_analysis_task_plan_policy()
    builder = ResearchAnalysisPlanCandidateBuilder(worker)

    candidate = builder.build_candidate(_plan_build_request(policy))

    assert worker.calls[0][0] == "candidate_task_plan"
    assert candidate.generated_by == "research.task-plan-builder@1"
    assert set(candidate.required_output_roles) == set(policy.required_output_roles)
    for task in candidate.tasks:
        capability = task.worker_capability
        assert task.output_contract.output_role == (
            RESEARCH_DYNAMIC_OUTPUT_ROLES_BY_CAPABILITY[capability]
        )
        assert task.output_contract.schema_ref == (
            RESEARCH_DYNAMIC_OUTPUT_SCHEMA_REFS[capability]
        )
        assert task.acceptance_criteria.gate_refs == (
            RESEARCH_DYNAMIC_GATES_BY_CAPABILITY[capability]
        )
        assert task.requested_tools == ()
        assert task.requested_memory_namespaces == ()
        assert task.retry_policy.max_attempts == policy.max_task_attempts

    forbidden = _valid_outline()
    forbidden["quality_passed"] = True
    with pytest.raises(HarnessValidationError) as exc_info:
        ResearchAnalysisPlanCandidateBuilder(_OutlineWorker(forbidden)).build_candidate(
            _plan_build_request(policy)
        )
    assert exc_info.value.code == "research_task_plan_builder_output_invalid"


def test_research_candidate_rejects_capability_gate_substitution() -> None:
    policy = build_research_analysis_task_plan_policy()
    candidate = ResearchAnalysisPlanCandidateBuilder(
        _OutlineWorker(_valid_outline())
    ).build_candidate(_plan_build_request(policy))
    structure = next(
        task
        for task in candidate.tasks
        if task.worker_capability == "research.analysis.structure"
    )
    substituted = replace(
        structure,
        acceptance_criteria=TaskAcceptanceCriteria(
            ("BenchmarkEvidenceLineageGate@1",)
        ),
    )
    altered = PlanCandidate(
        candidate_id="altered-research-analysis-plan",
        run_id=candidate.run_id,
        workflow_id=candidate.workflow_id,
        stage_id=candidate.stage_id,
        graph_checksum=candidate.graph_checksum,
        input_context_refs=candidate.input_context_refs,
        tasks=tuple(
            substituted if task.task_id == structure.task_id else task
            for task in candidate.tasks
        ),
        required_output_roles=candidate.required_output_roles,
        generated_by=candidate.generated_by,
        requested_plan_budget=candidate.requested_plan_budget,
        requested_max_parallelism=candidate.requested_max_parallelism,
    )

    with pytest.raises(HarnessValidationError) as exc_info:
        validate_research_analysis_candidate(altered)
    assert exc_info.value.code == "research_task_plan_candidate_contract_mismatch"


def test_research_aggregator_produces_existing_analysis_branch_contract() -> None:
    policy = build_research_analysis_task_plan_policy()
    aggregator = build_research_analysis_task_plan_aggregator()

    aggregate = aggregator.aggregate(_accepted_results(), policy)

    assert aggregator.registry.refs == (RESEARCH_DYNAMIC_AGGREGATOR_REF,)
    assert aggregate.branch_refs == (
        {
            "role": "analysis.structure",
            "output_ref": "result://structure",
            "producer_node_id": "analyze_structure",
            "output_key": "structure_candidate",
        },
        {
            "role": "analysis.contribution",
            "output_ref": "result://contribution",
            "producer_node_id": "analyze_contribution",
            "output_key": "contribution_candidate",
        },
        {
            "role": "analysis.experiments",
            "output_ref": "result://experiments",
            "producer_node_id": "analyze_experiments",
            "output_key": "experiment_candidate",
        },
    )

    with pytest.raises(HarnessValidationError) as exc_info:
        aggregator.aggregate(_accepted_results()[:-1], policy)
    assert exc_info.value.code == "task_plan_missing_required_role"


def _worker_bindings() -> dict[str, HarnessWorkerBinding]:
    return {
        capability: HarnessWorkerBinding(
            HarnessContractReference(
                HarnessContractKind.WORKER,
                capability,
                "1",
            ),
            HarnessWorkerType.SUBAGENT,
            _BoundResearchWorker(capability),
        )
        for capability in RESEARCH_DYNAMIC_CAPABILITIES
    }


def _plan_build_request(policy) -> PlanBuildRequest:
    return PlanBuildRequest(
        run_id="research-run",
        workflow_id="research.paper_analysis.dynamic",
        stage_id="dynamic_analysis_stage",
        graph_checksum=canonical_payload_checksum({"graph": "research-dynamic"}),
        context_refs={"document": "document", "evidence_pack": "evidence_pack"},
        policy=policy,
    )


def _valid_outline() -> dict[str, object]:
    tasks = []
    for index, capability in enumerate(RESEARCH_DYNAMIC_CAPABILITIES):
        tasks.append(
            {
                "task_id": f"analysis-task-{index + 1}",
                "objective": f"Produce {capability} from accepted evidence.",
                "worker_capability": capability,
                "input_refs": ["document", "evidence_pack"],
                "depends_on": [] if index < 2 else ["analysis-task-1"],
                "priority": 10 - index,
            }
        )
    return {"tasks": tasks, "requested_max_parallelism": 3}


def _accepted_results() -> tuple[TaskResultRecord, ...]:
    results = []
    for capability in RESEARCH_DYNAMIC_CAPABILITIES:
        suffix = capability.rsplit(".", 1)[-1]
        results.append(
            TaskResultRecord(
                run_id="research-run",
                workflow_id="research.paper_analysis.dynamic",
                stage_id="dynamic_analysis_stage",
                plan_id="research-plan",
                plan_version=1,
                task_id=f"task-{suffix}",
                task_instance_id=f"task-{suffix}-attempt-1",
                attempt=1,
                worker_ref=RESEARCH_DYNAMIC_WORKER_REFS[capability],
                task_checksum=canonical_payload_checksum(
                    {"task": suffix, "kind": "definition"}
                ),
                binding_checksum=canonical_payload_checksum(
                    {"task": suffix, "kind": "binding"}
                ),
                status=TaskLifecycle.SUCCEEDED,
                result_ref=f"result://{suffix}",
                output_roles=(
                    RESEARCH_DYNAMIC_OUTPUT_ROLES_BY_CAPABILITY[capability],
                ),
                output_schema_ref=RESEARCH_DYNAMIC_OUTPUT_SCHEMA_REFS[capability],
                usage=TaskBudget(max_turns=1).to_dict(),
            )
        )
    return tuple(results)
