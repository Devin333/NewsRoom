from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest

from framework.harness.control_plane.gate_registry import (
    DeterministicGateRegistry,
    GateReference,
    GateRegistration,
)
from framework.harness.control_plane.gates import (
    DeterministicGate,
    HarnessGateResult,
)
from framework.harness.control_plane.graph_evaluator import (
    HarnessGraphObservationType,
    merge_branch_output_references,
)
from framework.harness.control_plane.graph_decision import HarnessGraphDecisionType
from framework.harness.control_plane.graph_state import (
    HarnessEvidenceKind,
    HarnessNodeInstanceStatus,
    RunOutcome,
)
from framework.harness.control_plane.harness import (
    HarnessControlPlane,
    InMemoryHarnessEventPort,
)
from framework.harness.control_plane.state import HarnessRunSpec
from framework.harness.workflow.binding_authority import (
    HarnessActivityCapabilities,
    HarnessActivityContractBinding,
    HarnessDeterministicMergeBinding,
    HarnessRuntimeBindingAuthority,
    HarnessWorkerBinding,
)
from framework.harness.workflow.dsl import (
    HarnessGraphSpec,
    ParallelAll,
    ParallelBranch,
    PureMerge,
    Sequence,
    StepRef,
    VerifiedAggregation,
)
from framework.harness.workflow.graph import HarnessControlNode
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.workflow.step import HarnessStepSpec
from framework.harness.workflow.validation import (
    HarnessGraphPreflight,
    HarnessGraphPreflightPolicy,
)
from framework.harness.workers.result import HarnessWorkerResult


_CREATED_AT = datetime(2026, 7, 31, 6, 0, tzinfo=UTC)


@dataclass
class _Worker:
    worker_id: str
    calls: list[dict]
    worker_version: str = "1"
    worker_type: str = "script"

    def execute(self, task: dict) -> HarnessWorkerResult:
        self.calls.append(task)
        if self.worker_id == "aggregate":
            return HarnessWorkerResult(
                "succeeded",
                output={"branches": task["inputs"]["branch_output_refs"]},
            )
        return HarnessWorkerResult(
            "succeeded",
            output={"worker_id": self.worker_id, "inputs": task["inputs"]},
        )


@dataclass
class _Activity:
    activity_contract_id: str = "newsroom.harness-worker-activity"
    activity_contract_version: str = "v1"
    capabilities: HarnessActivityCapabilities = HarnessActivityCapabilities(
        stable_idempotency=True,
    )

    def dispatch(self, _request: dict) -> None:
        raise AssertionError("the local Harness path owns test Worker execution")


@dataclass
class _PureMerge:
    calls: list[dict]
    merge_id: str = "test.merge"
    merge_version: str = "1"
    deterministic: bool = True

    def __call__(self, request: dict) -> dict:
        self.calls.append(request)
        return {
            "merged_refs": tuple(
                item["payload_ref"] for item in request["branch_outputs"]
            )
        }


@dataclass
class _InvalidMerge:
    calls: list[dict]
    mode: str
    merge_id: str = "test.merge"
    merge_version: str = "1"
    deterministic: bool = True

    def __call__(self, request: dict) -> dict:
        self.calls.append(request)
        if self.mode == "exception":
            raise RuntimeError("binding failed")
        if self.mode == "wrong_keys":
            return {
                "unexpected": request["branch_outputs"][0]["payload_ref"],
            }
        if self.mode == "forged_ref":
            return {"merged_refs": "sha256:" + "f" * 64}
        raise AssertionError(f"unknown invalid Merge mode: {self.mode}")


@dataclass
class _SharedMerge:
    calls: list[dict]
    merge_id: str = "test.merge"
    merge_version: str = "1"
    deterministic: bool = True

    def __call__(self, request: dict) -> dict:
        self.calls.append(request)
        return {"shared": [item["payload_ref"] for item in request["branch_outputs"]]}


class _AggregateGate(DeterministicGate):
    gate_name = "aggregate.schema"
    gate_version = "1"

    def evaluate(self, _context) -> HarnessGateResult:
        return HarnessGateResult(self.gate_name, True)


class _FailAfterMergeObservationPort(InMemoryHarnessEventPort):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def commit_graph_observation(self, observation, **kwargs):
        committed = super().commit_graph_observation(observation, **kwargs)
        if (
            not self.failed
            and observation.observation_type is HarnessGraphObservationType.MERGE_RESULT
        ):
            self.failed = True
            raise RuntimeError("committed Merge result response was lost")
        return committed


class _FailAfterMergeProjectionPort(InMemoryHarnessEventPort):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def commit_graph_projection(self, commit, **kwargs):
        committed = super().commit_graph_projection(commit, **kwargs)
        if not self.failed and any(
            item.identity.node_id == "join:merge"
            and item.status is HarnessNodeInstanceStatus.RUNNING
            for item in committed.state.node_instances
        ):
            self.failed = True
            raise RuntimeError("committed Merge projection response was lost")
        return committed


class _StopBeforeMergePort(InMemoryHarnessEventPort):
    def commit_graph_decision(self, decision, **kwargs):
        if decision.decision_type is HarnessGraphDecisionType.APPLY_MERGE:
            raise RuntimeError("stop before Merge decision")
        return super().commit_graph_decision(decision, **kwargs)


def test_pure_merge_uses_exact_ordered_refs_before_successor_activation() -> None:
    run_spec = _pure_merge_run_spec("run-pure-merge")
    merge_calls: list[dict] = []
    worker_calls: list[dict] = []
    port = InMemoryHarnessEventPort()

    result = _control_plane(
        port,
        run_spec,
        worker_calls=worker_calls,
        merge=_PureMerge(merge_calls),
    ).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    assert len(merge_calls) == 1
    branch_refs = merge_calls[0]["branch_outputs"]
    assert [item["branch_id"] for item in branch_refs] == ["left", "right"]
    assert all(item["producer_node_instance_id"] for item in branch_refs)
    consume = next(item for item in worker_calls if item["step_id"] == "consume")
    assert consume["inputs"]["merged_refs"] == [
        item["payload_ref"] for item in branch_refs
    ]
    merge_node = next(
        item
        for item in result.graph_state.node_instances
        if item.identity.node_id == "join:merge"
    )
    assert merge_node.status is HarnessNodeInstanceStatus.SUCCEEDED
    assert set(merge_node.output_refs) == {"merged_refs"}
    assert any(
        evidence.kind is HarnessEvidenceKind.MERGE_RESULT
        for evidence in merge_node.evidence_refs
    )
    recovery = port.recover_graph(run_spec.run_id)
    observation = next(
        item
        for item in recovery.observation_commits
        if item.observation.observation_type is HarnessGraphObservationType.MERGE_RESULT
    )
    consume_activation = next(
        item
        for item in recovery.decision_commits
        if item.decision.node_id == "consume"
        and item.decision.decision_type.value == "activate_node"
    )
    assert observation.sequence < consume_activation.sequence


def test_verified_aggregation_runs_step_gate_before_merge_marker() -> None:
    run_spec = _aggregation_run_spec("run-aggregation-merge")
    worker_calls: list[dict] = []
    port = InMemoryHarnessEventPort()

    result = _control_plane(
        port,
        run_spec,
        worker_calls=worker_calls,
        gate=_AggregateGate(),
    ).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    aggregate = next(item for item in worker_calls if item["step_id"] == "aggregate")
    refs = aggregate["inputs"]["branch_output_refs"]
    assert [item["branch_id"] for item in refs] == ["left", "right"]
    marker = next(
        item
        for item in result.graph_state.node_instances
        if item.identity.node_id == "join:merge"
    )
    assert marker.status is HarnessNodeInstanceStatus.SUCCEEDED
    assert set(marker.output_refs) == {"combined"}
    consume = next(item for item in worker_calls if item["step_id"] == "consume")
    assert consume["inputs"]["combined"] == {"branches": list(refs)}
    recovery = port.recover_graph(run_spec.run_id)
    aggregate_complete = next(
        item
        for item in recovery.decision_commits
        if item.decision.node_id == "aggregate"
        and item.decision.decision_type.value == "complete_node"
    )
    apply_merge = next(
        item
        for item in recovery.decision_commits
        if item.decision.node_id == "join:merge"
        and item.decision.decision_type.value == "apply_merge"
    )
    assert aggregate_complete.sequence < apply_merge.sequence
    assert aggregate_complete.decision.decision_checksum in (
        apply_merge.accepted_evidence_refs
    )


def test_committed_merge_result_recovers_without_reinvoking_binding() -> None:
    run_spec = _pure_merge_run_spec("run-pure-merge-recovery")
    merge_calls: list[dict] = []
    worker_calls: list[dict] = []
    port = _FailAfterMergeObservationPort()
    merge = _PureMerge(merge_calls)
    first = _control_plane(
        port,
        run_spec,
        worker_calls=worker_calls,
        merge=merge,
    )

    with pytest.raises(RuntimeError, match="Merge result response was lost"):
        first.run(run_spec)

    assert len(merge_calls) == 1

    recovered = _control_plane(
        port,
        run_spec,
        worker_calls=worker_calls,
        merge=merge,
    ).recover_and_run(run_spec)

    assert recovered.graph_state is not None
    assert recovered.graph_state.outcome is RunOutcome.SUCCEEDED
    assert len(merge_calls) == 1


def test_committed_merge_projection_recovers_by_invoking_binding_once() -> None:
    run_spec = _pure_merge_run_spec("run-pure-merge-projection-recovery")
    merge_calls: list[dict] = []
    worker_calls: list[dict] = []
    port = _FailAfterMergeProjectionPort()
    merge = _PureMerge(merge_calls)

    with pytest.raises(RuntimeError, match="Merge projection response was lost"):
        _control_plane(
            port,
            run_spec,
            worker_calls=worker_calls,
            merge=merge,
        ).run(run_spec)

    assert merge_calls == []
    interrupted = port.recover_graph(run_spec.run_id)
    merge_node = next(
        item
        for item in interrupted.state.node_instances
        if item.identity.node_id == "join:merge"
    )
    assert merge_node.status is HarnessNodeInstanceStatus.RUNNING

    recovered = _control_plane(
        port,
        run_spec,
        worker_calls=worker_calls,
        merge=merge,
    ).recover_and_run(run_spec)

    assert recovered.graph_state is not None
    assert recovered.graph_state.outcome is RunOutcome.SUCCEEDED
    assert len(merge_calls) == 1


@pytest.mark.parametrize("mode", ("wrong_keys", "forged_ref", "exception"))
def test_invalid_pure_merge_result_fails_closed(mode: str) -> None:
    run_spec = _pure_merge_run_spec(f"run-invalid-pure-merge-{mode}")
    merge_calls: list[dict] = []
    worker_calls: list[dict] = []
    port = InMemoryHarnessEventPort()

    result = _control_plane(
        port,
        run_spec,
        worker_calls=worker_calls,
        merge=_InvalidMerge(merge_calls, mode),
    ).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.FAILED
    assert len(merge_calls) == 1
    assert not any(item["step_id"] == "consume" for item in worker_calls)
    merge_node = next(
        item
        for item in result.graph_state.node_instances
        if item.identity.node_id == "join:merge"
    )
    assert merge_node.status is HarnessNodeInstanceStatus.FAILED
    assert merge_node.output_refs == {}
    observation = next(
        item.observation
        for item in port.recover_graph(run_spec.run_id).observation_commits
        if item.observation.observation_type is HarnessGraphObservationType.MERGE_RESULT
    )
    assert observation.payload["succeeded"] is False
    assert observation.payload["reason_code"] == "merge_execution_failed"


def test_merge_input_order_ignores_branch_completion_container_order() -> None:
    run_spec = _pure_merge_run_spec("run-pure-merge-input-permutation")
    worker_calls: list[dict] = []
    port = _StopBeforeMergePort()
    control_plane = _control_plane(
        port,
        run_spec,
        worker_calls=worker_calls,
        merge=_PureMerge([]),
    )

    with pytest.raises(RuntimeError, match="stop before Merge decision"):
        control_plane.run(run_spec)

    recovery = port.recover_graph(run_spec.run_id)
    merge_definition = next(
        item
        for item in recovery.graph.nodes
        if isinstance(item, HarnessControlNode) and item.node_id == "join:merge"
    )
    merge_instance = next(
        item
        for item in recovery.state.node_instances
        if item.identity.node_id == merge_definition.node_id
    )
    _, _, baseline = merge_branch_output_references(
        recovery.graph,
        recovery.state,
        merge_definition,
        branch_path=merge_instance.identity.branch_path,
        iteration_vector=merge_instance.identity.iteration_vector,
    )
    permuted_joins = tuple(
        replace(
            item,
            completed_branch_instances=dict(
                reversed(tuple(item.completed_branch_instances.items()))
            ),
            terminal_event_refs=dict(reversed(tuple(item.terminal_event_refs.items()))),
        )
        for item in recovery.state.join_states
    )
    permuted = replace(
        recovery.state,
        join_states=permuted_joins,
        projection_checksum=None,
    )
    _, _, reordered = merge_branch_output_references(
        recovery.graph,
        permuted,
        merge_definition,
        branch_path=merge_instance.identity.branch_path,
        iteration_vector=merge_instance.identity.iteration_vector,
    )

    assert [item.to_dict() for item in reordered] == [
        item.to_dict() for item in baseline
    ]
    assert [item.branch_id for item in reordered] == ["left", "right"]


def test_composite_branch_reads_scoped_output_and_merge_sees_every_producer() -> None:
    run_spec = _composite_merge_run_spec("run-composite-branch-merge")
    worker_calls: list[dict] = []
    merge_calls: list[dict] = []

    result = _control_plane(
        InMemoryHarnessEventPort(),
        run_spec,
        worker_calls=worker_calls,
        merge=_SharedMerge(merge_calls),
    ).run(run_spec)

    assert result.graph_state is not None
    assert result.graph_state.outcome is RunOutcome.SUCCEEDED
    left_consume = next(
        item for item in worker_calls if item["step_id"] == "left_consume"
    )
    assert left_consume["inputs"]["shared"]["worker_id"] == "left_produce"
    branch_outputs = merge_calls[0]["branch_outputs"]
    assert [
        (item["branch_id"], item["producer_node_id"], item["output_key"])
        for item in branch_outputs
    ] == [
        ("left", "left_produce", "shared"),
        ("left", "left_consume", "left_done"),
        ("right", "right_produce", "shared"),
    ]
    consume = next(item for item in worker_calls if item["step_id"] == "consume")
    assert consume["inputs"]["shared"] == [
        item["payload_ref"] for item in branch_outputs
    ]


def _pure_merge_run_spec(run_id: str) -> HarnessRunSpec:
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        steps=(
            HarnessStepSpec("left", "script", output_key="left_output"),
            HarnessStepSpec("right", "script", output_key="right_output"),
            HarnessStepSpec(
                "consume",
                "script",
                input_keys=("merged_refs",),
                output_key="result",
            ),
        ),
        entry_step_id="left",
        graph=HarnessGraphSpec(
            f"graph-{run_id}",
            Sequence(
                (
                    ParallelAll(
                        "fork",
                        "join",
                        (
                            ParallelBranch("left", StepRef("left"), "branch.left"),
                            ParallelBranch(
                                "right",
                                StepRef("right"),
                                "branch.right",
                            ),
                        ),
                        merge=PureMerge("test.merge@1", ("merged_refs",)),
                    ),
                    StepRef("consume"),
                )
            ),
        ),
    )
    return HarnessRunSpec(run_id, workflow, created_at=_CREATED_AT)


def _aggregation_run_spec(run_id: str) -> HarnessRunSpec:
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        steps=(
            HarnessStepSpec("left", "script", output_key="left_output"),
            HarnessStepSpec("right", "script", output_key="right_output"),
            HarnessStepSpec(
                "aggregate",
                "script",
                input_keys=("branch_output_refs",),
                output_key="combined",
                quality_gate="aggregate.schema@1",
            ),
            HarnessStepSpec(
                "consume",
                "script",
                input_keys=("combined",),
                output_key="result",
            ),
        ),
        entry_step_id="left",
        graph=HarnessGraphSpec(
            f"graph-{run_id}",
            Sequence(
                (
                    ParallelAll(
                        "fork",
                        "join",
                        (
                            ParallelBranch("left", StepRef("left"), "branch.left"),
                            ParallelBranch(
                                "right",
                                StepRef("right"),
                                "branch.right",
                            ),
                        ),
                        merge=VerifiedAggregation(
                            StepRef("aggregate"),
                            "branch_output_refs",
                        ),
                    ),
                    StepRef("consume"),
                )
            ),
        ),
    )
    return HarnessRunSpec(run_id, workflow, created_at=_CREATED_AT)


def _composite_merge_run_spec(run_id: str) -> HarnessRunSpec:
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        steps=(
            HarnessStepSpec("left_produce", "script", output_key="shared"),
            HarnessStepSpec(
                "left_consume",
                "script",
                input_keys=("shared",),
                output_key="left_done",
            ),
            HarnessStepSpec("right_produce", "script", output_key="shared"),
            HarnessStepSpec(
                "consume",
                "script",
                input_keys=("shared",),
                output_key="result",
            ),
        ),
        entry_step_id="left_produce",
        graph=HarnessGraphSpec(
            f"graph-{run_id}",
            Sequence(
                (
                    ParallelAll(
                        "fork",
                        "join",
                        (
                            ParallelBranch(
                                "left",
                                Sequence(
                                    (
                                        StepRef("left_produce"),
                                        StepRef("left_consume"),
                                    )
                                ),
                                "branch.left",
                            ),
                            ParallelBranch(
                                "right",
                                StepRef("right_produce"),
                                "branch.right",
                            ),
                        ),
                        merge=PureMerge("test.merge@1", ("shared",)),
                    ),
                    StepRef("consume"),
                )
            ),
        ),
    )
    return HarnessRunSpec(run_id, workflow, created_at=_CREATED_AT)


def _control_plane(
    port: InMemoryHarnessEventPort,
    run_spec: HarnessRunSpec,
    *,
    worker_calls: list[dict],
    merge: _PureMerge | None = None,
    gate: DeterministicGate | None = None,
) -> HarnessControlPlane:
    workers = tuple(
        HarnessWorkerBinding(
            f"{step.step_id}@1",
            "script",
            _Worker(step.step_id, worker_calls),
        )
        for step in run_spec.workflow.steps
    )
    gate_registry = DeterministicGateRegistry()
    if gate is not None:
        gate_registry = DeterministicGateRegistry(
            (
                GateRegistration(
                    GateReference(gate.gate_name, gate.gate_version),
                    gate,
                ),
            )
        )
    authority = HarnessRuntimeBindingAuthority(
        workers=workers,
        activities=(
            HarnessActivityContractBinding(
                "newsroom.harness-worker-activity@v1",
                _Activity(),
            ),
        ),
        merges=(
            ()
            if merge is None
            else (HarnessDeterministicMergeBinding("test.merge@1", merge),)
        ),
        gate_registry=gate_registry,
    )
    return HarnessControlPlane(
        event_port=port,
        runtime_binding_authority=authority,
        graph_preflight=HarnessGraphPreflight(
            policy=HarnessGraphPreflightPolicy(
                max_node_activations=32,
                max_active_nodes=8,
                max_parallelism=1,
            )
        ),
    )
