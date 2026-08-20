from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.gate_registry import DeterministicGateRegistry
from framework.harness.control_plane.gates import GateContext
from framework.harness.control_plane.activity_execution import (
    HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY,
    HarnessGraphActivityTaskContext,
)
from framework.harness.subagents.models import SubAgentSpec
from framework.harness.task_plan.aggregator import (
    TaskPlanAggregateResult,
    TaskPlanAggregator,
    TaskPlanAggregatorRegistry,
)
from framework.harness.task_plan.canonical import canonical_payload_checksum
from framework.harness.task_plan.capability import (
    TaskCapabilityRegistration,
    TaskCapabilityRegistry,
)
from framework.harness.task_plan.models import (
    PlanCandidate,
    TaskAcceptanceCriteria,
    TaskBudget,
    TaskOutputContract,
    TaskRetryPolicy,
    TaskSpec,
)
from framework.harness.task_plan.ports import (
    PlanBuildRequest,
    PlanCandidateBuilderPort,
    TaskPlanResultVerifierPort,
    TaskPlanStageRequest,
)
from framework.harness.task_plan.policy import TaskPlanPolicy, TaskPlanPolicyRegistry
from framework.harness.task_plan.stage import TaskPlanStageRunner
from framework.harness.task_plan.stage_binding import TaskPlanStageBinding
from framework.harness.task_plan.store import (
    InMemoryTaskPlanStore,
    TaskPlanStorePort,
    TaskResultRecord,
)
from framework.harness.task_plan.verification import (
    TaskPlanGateRegistry,
    TaskPlanGateRequest,
)
from framework.harness.graph.bindings import HarnessWorkerBinding
from framework.harness.graph.activity import HarnessWorkerType
from framework.shared.graph_identity import GraphExecutionIdentity

from business.research.graphs.contracts import (
    RESEARCH_DYNAMIC_AGGREGATOR_REF,
    RESEARCH_DYNAMIC_CAPABILITIES,
    RESEARCH_DYNAMIC_CAPABILITY_REGISTRY_REF,
    RESEARCH_DYNAMIC_CANDIDATE_BUILDER_REF,
    RESEARCH_DYNAMIC_GATE_REFS,
    RESEARCH_DYNAMIC_GATES_BY_CAPABILITY,
    RESEARCH_DYNAMIC_GATE_REGISTRY_REF,
    RESEARCH_DYNAMIC_INPUT_REFS,
    RESEARCH_DYNAMIC_MEMORY_NAMESPACES,
    RESEARCH_DYNAMIC_OUTPUT_ROLES,
    RESEARCH_DYNAMIC_OUTPUT_ROLES_BY_CAPABILITY,
    RESEARCH_DYNAMIC_OUTPUT_SCHEMA_REFS,
    RESEARCH_DYNAMIC_PAPER_ANALYSIS_GRAPH_ID,
    RESEARCH_DYNAMIC_POLICY_REF,
    RESEARCH_PAPER_ANALYSIS_GRAPH_VERSION,
    RESEARCH_DYNAMIC_RESULT_STORE_REF,
    RESEARCH_DYNAMIC_STAGE_ID,
    RESEARCH_DYNAMIC_SUBAGENT_IDS,
    RESEARCH_DYNAMIC_TOOL_IDS,
    RESEARCH_DYNAMIC_WORKER_CONTRACT_REFS,
    RESEARCH_DYNAMIC_WORKER_REFS,
)


_RESEARCH_DYNAMIC_GRAPH_REF = (
    f"{RESEARCH_DYNAMIC_PAPER_ANALYSIS_GRAPH_ID}@"
    f"{RESEARCH_PAPER_ANALYSIS_GRAPH_VERSION}"
)
_RESEARCH_BRANCH_IDENTITIES = MappingProxyType(
    {
        "analysis.structure": ("analyze_structure", "structure_candidate"),
        "analysis.contribution": (
            "analyze_contribution",
            "contribution_candidate",
        ),
        "analysis.experiments": (
            "analyze_experiments",
            "experiment_candidate",
        ),
    }
)
_RESEARCH_SUBAGENT_OUTPUT_SCHEMAS = MappingProxyType(
    {
        "research.analysis.structure": {
            "type": "object",
            "required": [
                "candidate_ref",
                "three_minute_read",
                "claims",
                "warnings",
            ],
            "properties": {
                "candidate_ref": {"type": "string"},
                "three_minute_read": {"type": "object"},
                "claims": {"type": "array"},
                "warnings": {"type": "array"},
            },
        },
        "research.analysis.contribution": {
            "type": "object",
            "required": [
                "contributions",
                "taxonomy_assignment",
                "taxonomy_review_candidate_ids",
                "summary_evidence_refs",
            ],
            "properties": {
                "contributions": {"type": "array"},
                "taxonomy_assignment": {"type": "object"},
                "taxonomy_review_candidate_ids": {"type": "array"},
                "summary_evidence_refs": {"type": "array"},
            },
        },
        "research.analysis.experiments": {
            "type": "object",
            "required": [
                "claims",
                "claim_models",
                "scores",
                "claim_confidence_observation",
            ],
            "properties": {
                "claims": {"type": "array"},
                "claim_models": {"type": "array"},
                "scores": {"type": "array"},
                "claim_confidence_observation": {"type": "number"},
            },
        },
    }
)


def build_research_analysis_task_plan_policy() -> TaskPlanPolicy:
    """Return the pinned policy for the Research dynamic analysis stage."""

    budget = TaskBudget(max_turns=4, max_tool_calls=4, max_memory_ops=2, max_output_tokens=4096)
    return TaskPlanPolicy(
        policy_id="research.analysis",
        version="1",
        stage_id=RESEARCH_DYNAMIC_STAGE_ID,
        allowed_worker_capabilities=RESEARCH_DYNAMIC_CAPABILITIES,
        allowed_subagent_ids=tuple(RESEARCH_DYNAMIC_SUBAGENT_IDS.values()),
        allowed_tool_ids=RESEARCH_DYNAMIC_TOOL_IDS,
        allowed_memory_namespaces=RESEARCH_DYNAMIC_MEMORY_NAMESPACES,
        allowed_input_refs=RESEARCH_DYNAMIC_INPUT_REFS,
        allowed_output_roles=RESEARCH_DYNAMIC_OUTPUT_ROLES,
        required_output_roles=RESEARCH_DYNAMIC_OUTPUT_ROLES,
        allowed_output_schema_refs=(
            "research.analysis.structure@1",
            "research.analysis.contribution@1",
            "research.analysis.experiments@1",
        ),
        allowed_gate_refs=RESEARCH_DYNAMIC_GATE_REFS,
        deterministic_aggregator_refs={},
        pinned_capability_bindings=RESEARCH_DYNAMIC_WORKER_REFS,
        required_worker_contract_refs=RESEARCH_DYNAMIC_WORKER_CONTRACT_REFS,
        max_tasks=8,
        max_depth=4,
        max_parallelism=3,
        max_replans=2,
        max_task_attempts=2,
        max_plan_build_calls=1,
        max_plan_build_turns=4,
        max_plan_build_tool_calls=2,
        per_task_budget=budget,
        aggregate_task_budget=TaskBudget(max_turns=12, max_tool_calls=12, max_memory_ops=6, max_output_tokens=12288),
        metadata={
            "input_contract": {"required": list(RESEARCH_DYNAMIC_INPUT_REFS)},
            "output_contract": {"required": list(RESEARCH_DYNAMIC_OUTPUT_ROLES)},
            "capability_gate_refs": {
                capability: list(gates)
                for capability, gates in RESEARCH_DYNAMIC_GATES_BY_CAPABILITY.items()
            },
            "stage_aggregator_ref": RESEARCH_DYNAMIC_AGGREGATOR_REF,
            "static_graph_id": "research.paper_analysis",
        },
    )


def build_research_analysis_task_plan_policy_registry() -> TaskPlanPolicyRegistry:
    return TaskPlanPolicyRegistry((build_research_analysis_task_plan_policy(),))


class ResearchAnalysisPlanCandidateBuilder(PlanCandidateBuilderPort):
    """Translate one restricted LLM plan outline into a pinned candidate.

    The model may choose task objectives, ids, dependency hints, and one of
    the three logical capabilities. Harness-owned fields such as schemas,
    gates, tools, memory, retry limits, worker bindings, and plan identity are
    populated from the pinned policy rather than accepted from model output.
    """

    def __init__(self, candidate_worker: Any) -> None:
        if not callable(getattr(candidate_worker, "generate_candidate", None)):
            raise TypeError("candidate_worker must expose generate_candidate")
        self._candidate_worker = candidate_worker

    def build_candidate(self, request: PlanBuildRequest) -> PlanCandidate:
        if request.policy.exact_ref != RESEARCH_DYNAMIC_POLICY_REF:
            raise HarnessValidationError(
                "Research TaskPlan builder received an incompatible policy",
                code="research_task_plan_policy_mismatch",
            )
        candidate_request = {
            "task": "candidate_task_plan",
            "payload": {
                "stage": request.to_dict(),
                "required_output_roles": list(request.policy.required_output_roles),
                "allowed_capabilities": list(
                    request.policy.allowed_worker_capabilities
                ),
            },
        }
        if request.execution_identity is not None:
            candidate_request["execution_identity"] = request.execution_identity
        payload = self._candidate_worker.generate_candidate(**candidate_request)
        if not isinstance(payload, Mapping):
            raise HarnessValidationError(
                "Research TaskPlan builder returned an invalid candidate outline",
                code="research_task_plan_builder_output_invalid",
            )
        task_payloads = payload.get("tasks")
        requested_parallelism = payload.get("requested_max_parallelism", 1)
        if (
            set(payload) != {"tasks", "requested_max_parallelism"}
            or not isinstance(task_payloads, list)
        ):
            raise HarnessValidationError(
                "Research TaskPlan builder returned an invalid candidate outline",
                code="research_task_plan_builder_output_invalid",
            )
        tasks = tuple(
            self._task_from_outline(item, policy=request.policy)
            for item in task_payloads
        )
        candidate = PlanCandidate.for_stage(
            stage_identity=request.stage_identity,
            candidate_id=(
                f"research-analysis-plan-{request.run_id}-{request.graph_checksum[-12:]}"
            ),
            input_context_refs=tuple(request.context_refs.values()),
            tasks=tasks,
            required_output_roles=request.policy.required_output_roles,
            generated_by=RESEARCH_DYNAMIC_CANDIDATE_BUILDER_REF,
            requested_plan_budget=request.policy.limits.plan_build_budget,
            requested_max_parallelism=requested_parallelism,
            metadata={"policy_ref": request.policy.exact_ref},
        )
        validate_research_analysis_candidate(candidate)
        return candidate

    @staticmethod
    def _task_from_outline(
        value: Any,
        *,
        policy: TaskPlanPolicy,
    ) -> TaskSpec:
        if not isinstance(value, Mapping):
            raise HarnessValidationError(
                "Research TaskPlan task outline must be an object",
                code="research_task_plan_builder_output_invalid",
            )
        expected = {
            "task_id",
            "objective",
            "worker_capability",
            "input_refs",
            "depends_on",
            "priority",
        }
        if set(value) != expected:
            raise HarnessValidationError(
                "Research TaskPlan task outline has unsupported fields",
                code="research_task_plan_builder_output_invalid",
            )
        capability = value.get("worker_capability")
        if not isinstance(capability, str) or capability not in (
            RESEARCH_DYNAMIC_OUTPUT_ROLES_BY_CAPABILITY
        ):
            raise HarnessValidationError(
                "Research TaskPlan task requested an unsupported capability",
                code="research_task_plan_capability_not_allowed",
            )
        input_refs = value.get("input_refs")
        if not isinstance(input_refs, list) or not set(input_refs).issubset(
            RESEARCH_DYNAMIC_INPUT_REFS
        ):
            raise HarnessValidationError(
                "Research TaskPlan task referenced context outside the analysis stage",
                code="research_task_plan_input_not_allowed",
            )
        return TaskSpec(
            task_id=value.get("task_id"),
            objective=value.get("objective"),
            worker_capability=capability,
            input_refs=tuple(input_refs),
            output_contract=TaskOutputContract(
                schema_ref=RESEARCH_DYNAMIC_OUTPUT_SCHEMA_REFS[capability],
                output_role=RESEARCH_DYNAMIC_OUTPUT_ROLES_BY_CAPABILITY[capability],
            ),
            acceptance_criteria=TaskAcceptanceCriteria(
                RESEARCH_DYNAMIC_GATES_BY_CAPABILITY[capability]
            ),
            depends_on=tuple(value.get("depends_on", ())),
            requested_tools=(),
            requested_memory_namespaces=(),
            budget_request=policy.per_task_budget,
            retry_policy=TaskRetryPolicy(
                max_attempts=policy.max_task_attempts,
                retryable_reason_codes=("task_worker_failed",),
            ),
            priority=value.get("priority"),
        )


class ResearchAnalysisTaskPlanStageWorker:
    """Adapt the outer Graph worker task to the Harness TaskPlan runner."""

    def __init__(
        self,
        *,
        stage_binding: TaskPlanStageBinding,
        accepted_at: str,
        candidate_builder: PlanCandidateBuilderPort,
        capability_registry: TaskCapabilityRegistry,
        store: TaskPlanStorePort,
        worker_executor: Any,
        result_verifier: TaskPlanResultVerifierPort,
        worker_result_recovery: Any | None = None,
        policy: TaskPlanPolicy | None = None,
        allow_test_store: bool = False,
    ) -> None:
        if not isinstance(store, TaskPlanStorePort):
            raise TypeError("store must implement TaskPlanStorePort")
        if not isinstance(stage_binding, TaskPlanStageBinding):
            raise TypeError("stage_binding must be TaskPlanStageBinding")
        if isinstance(store, InMemoryTaskPlanStore) and not allow_test_store:
            raise HarnessValidationError(
                "Research production TaskPlan requires a durable store",
                code="research_task_plan_durable_store_required",
            )
        if not callable(worker_executor):
            raise TypeError("worker_executor must be callable")
        if not isinstance(result_verifier, TaskPlanResultVerifierPort):
            raise TypeError("result_verifier must implement TaskPlanResultVerifierPort")
        actual_policy = policy or build_research_analysis_task_plan_policy()
        if (
            actual_policy.exact_ref != RESEARCH_DYNAMIC_POLICY_REF
            or stage_binding.policy_ref != actual_policy.exact_ref
            or stage_binding.graph.identity_ref.exact_ref
            != _RESEARCH_DYNAMIC_GRAPH_REF
            or stage_binding.stage_id != RESEARCH_DYNAMIC_STAGE_ID
            or stage_binding.required_output_roles
            != actual_policy.required_output_roles
        ):
            raise HarnessValidationError(
                "Research TaskPlan stage worker requires the pinned Graph stage",
                code="research_task_plan_policy_mismatch",
            )
        self._stage_binding = stage_binding
        self._accepted_at = str(accepted_at)
        self._policy = actual_policy
        self._runner = TaskPlanStageRunner(
            candidate_builder=candidate_builder,
            capability_registry=capability_registry,
            store=store,
            aggregator=build_research_analysis_task_plan_aggregator(),
            result_verifier=result_verifier,
            worker_executor=worker_executor,
            worker_result_recovery=worker_result_recovery,
        )

    def __call__(self, task: Mapping[str, Any]):
        return self.run(task)

    def run(self, task: Mapping[str, Any]):
        if not isinstance(task, Mapping):
            raise TypeError("Research dynamic stage task must be a mapping")
        inputs = task.get("inputs")
        if (
            task.get("step_id") != RESEARCH_DYNAMIC_STAGE_ID
            or task.get("worker_type") != HarnessWorkerType.TASK_PLAN.value
            or not isinstance(inputs, Mapping)
            or set(inputs) != set(RESEARCH_DYNAMIC_INPUT_REFS)
            or any(inputs[name] is None for name in RESEARCH_DYNAMIC_INPUT_REFS)
        ):
            raise HarnessValidationError(
                "Research dynamic stage input contract is invalid",
                code="research_task_plan_stage_input_invalid",
            )
        run_id = task.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise HarnessValidationError(
                "Research dynamic stage run identity is missing",
                code="research_task_plan_stage_input_invalid",
            )
        raw_activity_context = task.get(HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY)
        if not isinstance(raw_activity_context, Mapping):
            raise HarnessValidationError(
                "Research dynamic stage requires physical Graph activity identity",
                code="research_task_plan_execution_identity_missing",
            )
        activity_context = HarnessGraphActivityTaskContext.from_dict(
            raw_activity_context
        )
        activity = activity_context.activity
        graph_ref = activity.graph_ref
        mismatches = tuple(
            field_name
            for field_name, expected, actual in (
                ("run_id", run_id, activity.run_id),
                ("node_id", self._stage_binding.node_id, activity.node_id),
                (
                    "graph_ref",
                    self._stage_binding.graph.graph_ref.exact_ref,
                    graph_ref.identity_ref.exact_ref,
                ),
                (
                    "graph_checksum",
                    self._stage_binding.graph_checksum,
                    graph_ref.checksum,
                ),
                ("step_ref", self._stage_binding.step_ref, activity.step_ref.exact_ref),
                ("worker_ref", self._stage_binding.worker_ref, activity.worker_ref.exact_ref),
                (
                    "activity_ref",
                    self._stage_binding.activity_ref,
                    activity.activity_ref.exact_ref,
                ),
            )
            if expected != actual
        )
        if mismatches:
            raise HarnessValidationError(
                "Research dynamic stage activity is outside its frozen Graph binding",
                code="research_task_plan_execution_identity_mismatch",
                details={"mismatches": list(mismatches)},
            )
        execution_identity = GraphExecutionIdentity(
            run_id=activity.run_id,
            graph_id=graph_ref.graph_id,
            graph_version=graph_ref.identity_version,
            graph_ref=graph_ref.identity_ref.exact_ref,
            graph_checksum=graph_ref.checksum,
            node_id=activity.node_id,
            node_instance_id=activity.node_instance_id,
            activity_id=activity.activity_id,
            attempt=activity.attempt,
        )
        input_checksums = {
            name: canonical_payload_checksum({"name": name, "value": inputs[name]})
            for name in RESEARCH_DYNAMIC_INPUT_REFS
        }
        return self._runner.run(
            TaskPlanStageRequest(
                run_id=run_id,
                stage_binding=self._stage_binding,
                context_refs={name: name for name in RESEARCH_DYNAMIC_INPUT_REFS},
                policy=self._policy,
                policy_ref=self._policy.exact_ref,
                accepted_at=self._accepted_at,
                execution_identity=execution_identity,
                metadata={
                    "accepted_at": self._accepted_at,
                    "input_ref_checksums": input_checksums,
                },
            )
        )


def build_research_analysis_subagent_specs() -> tuple[SubAgentSpec, ...]:
    """Return the exact SubAgent contracts allowed in the dynamic stage."""

    specs: list[SubAgentSpec] = []
    for capability in RESEARCH_DYNAMIC_CAPABILITIES:
        role = RESEARCH_DYNAMIC_OUTPUT_ROLES_BY_CAPABILITY[capability]
        specs.append(
            SubAgentSpec(
                subagent_id=RESEARCH_DYNAMIC_SUBAGENT_IDS[capability],
                role=role,
                purpose=(
                    "Produce one evidence-grounded Research analysis role; "
                    "Harness owns routing, verification, quality, and publication."
                ),
                input_schema={
                    "type": "object",
                    "required": [
                        "input_refs",
                        "task_id",
                        "task_definition_checksum",
                    ],
                    "properties": {
                        "input_refs": {"type": "array"},
                        "task_id": {"type": "string"},
                        "task_definition_checksum": {"type": "string"},
                    },
                },
                output_schema=_RESEARCH_SUBAGENT_OUTPUT_SCHEMAS[capability],
                allowed_tools=RESEARCH_DYNAMIC_TOOL_IDS,
                allowed_memory_namespaces=RESEARCH_DYNAMIC_MEMORY_NAMESPACES,
                context_policy={
                    "allow_sibling_history": False,
                    "allow_private_notes_export": False,
                    "allowed_input_refs": list(RESEARCH_DYNAMIC_INPUT_REFS),
                },
                budget={
                    "max_turns": 4,
                    "max_tool_calls": 4,
                    "max_memory_ops": 2,
                },
                metadata={
                    "worker_capability": capability,
                    "gate_refs": list(
                        RESEARCH_DYNAMIC_GATES_BY_CAPABILITY[capability]
                    ),
                },
            )
        )
    return tuple(specs)


def build_research_analysis_capability_registry(
    worker_bindings: Mapping[str, HarnessWorkerBinding],
) -> TaskCapabilityRegistry:
    """Bind Research capabilities without manufacturing runtime workers.

    The composition root must supply every exact worker binding. Missing,
    extra, stale, or non-SubAgent bindings fail before candidate validation.
    """

    if not isinstance(worker_bindings, Mapping):
        raise TypeError("worker_bindings must be a mapping")
    supplied = set(worker_bindings)
    expected = set(RESEARCH_DYNAMIC_CAPABILITIES)
    if supplied != expected:
        raise HarnessValidationError(
            "Research TaskPlan capability bindings are incomplete",
            code="research_task_plan_capability_bindings_incomplete",
            details={
                "missing": sorted(expected - supplied),
                "unexpected": sorted(supplied - expected),
            },
        )

    specs = {
        spec.metadata["worker_capability"]: spec
        for spec in build_research_analysis_subagent_specs()
    }
    registrations: list[TaskCapabilityRegistration] = []
    for capability in RESEARCH_DYNAMIC_CAPABILITIES:
        binding = worker_bindings[capability]
        if not isinstance(binding, HarnessWorkerBinding):
            raise TypeError("Research capability values must be HarnessWorkerBinding")
        expected_ref = RESEARCH_DYNAMIC_WORKER_REFS[capability]
        if (
            binding.reference.exact_ref != expected_ref
            or binding.worker_type is not HarnessWorkerType.SUBAGENT
        ):
            raise HarnessValidationError(
                "Research TaskPlan capability binding does not match policy",
                code="research_task_plan_capability_binding_mismatch",
                details={
                    "capability": capability,
                    "expected_worker_ref": expected_ref,
                    "actual_worker_ref": binding.reference.exact_ref,
                    "worker_type": binding.worker_type.value,
                },
            )
        registrations.append(
            TaskCapabilityRegistration(
                capability=capability,
                worker_binding=binding,
                worker_contract_ref=RESEARCH_DYNAMIC_WORKER_CONTRACT_REFS[
                    capability
                ],
                input_schema_ref="research.analysis.input@1",
                output_schema_ref=RESEARCH_DYNAMIC_OUTPUT_SCHEMA_REFS[
                    capability
                ],
                subagent_spec=specs[capability],
            )
        )
    return TaskCapabilityRegistry(registrations)


def build_research_analysis_task_gate_registry(
    gate_registry: DeterministicGateRegistry,
    *,
    context_factory: Any,
) -> TaskPlanGateRegistry:
    """Adapt the existing exact Research gates to TaskPlan gate requests."""

    if not isinstance(gate_registry, DeterministicGateRegistry):
        raise TypeError("gate_registry must be DeterministicGateRegistry")
    if not callable(context_factory):
        raise TypeError("context_factory must be callable")
    task_gates = TaskPlanGateRegistry()
    for gate_ref in RESEARCH_DYNAMIC_GATE_REFS:
        gate = gate_registry.resolve(gate_ref).gate

        def evaluate(
            request: TaskPlanGateRequest,
            *,
            implementation=gate,
        ) -> bool:
            context = context_factory(request)
            if not isinstance(context, GateContext):
                raise TypeError("context_factory must return GateContext")
            result = implementation.evaluate(context)
            return result.passed

        task_gates.register(gate_ref, evaluate, deterministic=True)
    return task_gates


class ResearchAnalysisTaskPlanAggregator(TaskPlanAggregator):
    """Project accepted role refs to the existing Research merge contract."""

    aggregator_ref = RESEARCH_DYNAMIC_AGGREGATOR_REF

    def __init__(self) -> None:
        registry = TaskPlanAggregatorRegistry()
        registry.register(
            self.aggregator_ref,
            _reject_conflicting_research_role,
            deterministic=True,
        )
        super().__init__(registry)

    def aggregate(
        self,
        results: tuple[TaskResultRecord, ...],
        policy: TaskPlanPolicy,
    ) -> TaskPlanAggregateResult:
        aggregate = super().aggregate(results, policy)
        branch_refs = tuple(
            {
                "role": role,
                "output_ref": aggregate.output_refs_by_role[role],
                "producer_node_id": _RESEARCH_BRANCH_IDENTITIES[role][0],
                "output_key": _RESEARCH_BRANCH_IDENTITIES[role][1],
            }
            for role in RESEARCH_DYNAMIC_OUTPUT_ROLES
        )
        aggregate_checksum = canonical_payload_checksum(
            {
                "roles": dict(aggregate.output_refs_by_role),
                "result_refs": list(aggregate.result_refs),
                "branch_refs": [dict(item) for item in branch_refs],
            }
        )
        return TaskPlanAggregateResult(
            output_refs_by_role=aggregate.output_refs_by_role,
            aggregate_ref=f"task-plan-aggregate:{aggregate_checksum}",
            aggregate_checksum=aggregate_checksum,
            result_refs=aggregate.result_refs,
            branch_refs=branch_refs,
        )


def build_research_analysis_task_plan_aggregator() -> TaskPlanAggregator:
    return ResearchAnalysisTaskPlanAggregator()


def validate_research_analysis_candidate(candidate: PlanCandidate) -> None:
    """Enforce capability-specific Research roles, schemas, and gates."""

    if not isinstance(candidate, PlanCandidate):
        raise TypeError("candidate must be PlanCandidate")
    violations: list[dict[str, Any]] = []
    for task in candidate.tasks:
        capability = task.worker_capability
        if capability not in RESEARCH_DYNAMIC_OUTPUT_ROLES_BY_CAPABILITY:
            violations.append(
                {"task_id": task.task_id, "reason": "capability_not_allowed"}
            )
            continue
        expected_role = RESEARCH_DYNAMIC_OUTPUT_ROLES_BY_CAPABILITY[capability]
        expected_schema = RESEARCH_DYNAMIC_OUTPUT_SCHEMA_REFS[capability]
        expected_gates = RESEARCH_DYNAMIC_GATES_BY_CAPABILITY[capability]
        if task.output_contract.output_role != expected_role:
            violations.append(
                {"task_id": task.task_id, "reason": "output_role_mismatch"}
            )
        if task.output_contract.schema_ref != expected_schema:
            violations.append(
                {"task_id": task.task_id, "reason": "output_schema_mismatch"}
            )
        if task.acceptance_criteria.gate_refs != expected_gates:
            violations.append(
                {"task_id": task.task_id, "reason": "gate_binding_mismatch"}
            )
    if violations:
        raise HarnessValidationError(
            "Research analysis candidate violates its pinned capability contract",
            code="research_task_plan_candidate_contract_mismatch",
            details={"violations": violations},
        )


def _reject_conflicting_research_role(
    _results: tuple[TaskResultRecord, ...],
    _policy: TaskPlanPolicy,
) -> Mapping[str, str]:
    raise HarnessValidationError(
        "Research analysis roles require one accepted producer",
        code="task_plan_output_conflict",
    )


__all__ = [
    "RESEARCH_DYNAMIC_CAPABILITIES",
    "RESEARCH_DYNAMIC_CAPABILITY_REGISTRY_REF",
    "RESEARCH_DYNAMIC_AGGREGATOR_REF",
    "RESEARCH_DYNAMIC_CANDIDATE_BUILDER_REF",
    "RESEARCH_DYNAMIC_GATE_REFS",
    "RESEARCH_DYNAMIC_GATE_REGISTRY_REF",
    "RESEARCH_DYNAMIC_INPUT_REFS",
    "RESEARCH_DYNAMIC_GATES_BY_CAPABILITY",
    "RESEARCH_DYNAMIC_MEMORY_NAMESPACES",
    "RESEARCH_DYNAMIC_OUTPUT_ROLES",
    "RESEARCH_DYNAMIC_OUTPUT_ROLES_BY_CAPABILITY",
    "RESEARCH_DYNAMIC_OUTPUT_SCHEMA_REFS",
    "RESEARCH_DYNAMIC_POLICY_REF",
    "RESEARCH_DYNAMIC_RESULT_STORE_REF",
    "RESEARCH_DYNAMIC_STAGE_ID",
    "RESEARCH_DYNAMIC_SUBAGENT_IDS",
    "RESEARCH_DYNAMIC_TOOL_IDS",
    "RESEARCH_DYNAMIC_WORKER_CONTRACT_REFS",
    "RESEARCH_DYNAMIC_WORKER_REFS",
    "ResearchAnalysisTaskPlanAggregator",
    "ResearchAnalysisPlanCandidateBuilder",
    "ResearchAnalysisTaskPlanStageWorker",
    "build_research_analysis_capability_registry",
    "build_research_analysis_subagent_specs",
    "build_research_analysis_task_gate_registry",
    "build_research_analysis_task_plan_aggregator",
    "build_research_analysis_task_plan_policy",
    "build_research_analysis_task_plan_policy_registry",
    "validate_research_analysis_candidate",
]
