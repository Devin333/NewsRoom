from __future__ import annotations

from dataclasses import dataclass

import pytest

from framework.events.canonical import canonical_json_bytes, checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_application import (
    HarnessGraphDecisionApplier,
)
from framework.harness.control_plane.gates import DeterministicGate, HarnessGateResult
from framework.harness.graph.decision import (
    HarnessGraphDecision,
    HarnessGraphDecisionType,
)
from framework.harness.control_plane.graph_evaluator import (
    HarnessGraphObservationType,
)
from framework.harness.control_plane.graph_runtime import (
    HarnessGraphActivityResult,
    HarnessGraphActivityResultStatus,
    HarnessGraphCommitKind,
)
from framework.harness.control_plane.graph_state import (
    HarnessCompensationStatus,
    HarnessEvidenceKind,
    HarnessGraphState,
    HarnessNodeInstanceStatus,
    RunLifecycle,
    RunOutcome,
)
from framework.harness.control_plane.harness import (
    HarnessControlPlane,
    InMemoryHarnessEventPort,
)
from framework.harness.control_plane.policy import HarnessBudget
from framework.harness.control_plane.state import HarnessRunSpec, HarnessStepStatus
from framework.harness.runtime import (
    ArtifactClass,
    ArtifactRecord,
    BoundedSummary,
    ContextPolicy,
    HarnessGraphResultRuntime,
    NodeResultEnvelope,
    NodeResultStatus,
    PersistenceDecision,
    PersistenceMode,
    PersistenceReason,
    ResultMetrics,
    ResultProvenance,
    ResultSensitivity,
    RetentionClass,
)
from framework.harness.side_effects.fake import (
    CountingHarnessSideEffectHandler,
    InMemoryHarnessSideEffectStore,
)
from framework.harness.side_effects.models import (
    HarnessSideEffectIntent,
    HarnessTerminalSideEffectPolicy,
)
from framework.harness.side_effects.registry import (
    HarnessSideEffectHandlerBinding,
    HarnessSideEffectRegistry,
)
from framework.harness.graph.bindings import (
    HarnessActivityCapabilities,
    HarnessActivityContractBinding,
    HarnessCompensationHandlerBinding,
    HarnessLeafActivityBinding,
    HarnessRuntimeBindingAuthority,
    HarnessWorkerBinding,
)
from framework.harness.graph.canonical import canonical_checksum
from framework.harness.graph.dsl import (
    CompensationBinding,
    HarnessGraphSpec,
    ParallelAll,
    ParallelBranch,
    StepRef,
)
from framework.harness.graph.model import (
    HarnessExecutableNode,
    NormalizedHarnessGraph,
)
from framework.harness.graph.activity import (
    HarnessLeafActivityKind,
    HarnessRetryPolicy,
    HarnessStepSpec,
    HarnessWorkerType,
)
from framework.harness.graph.definition import HarnessGraphDefinition, HarnessGraphLeafBinding
from framework.harness.graph.model import HarnessContractKind, HarnessContractReference
from framework.harness.graph.validation import HarnessGraphPreflightPolicy
from framework.harness.graph.validation import HarnessGraphPreflight
from framework.harness.workers.result import (
    HarnessWorkerResult,
    harness_worker_candidate_ref,
)
from framework.harness.runtime.activity_executor import HarnessGraphPhysicalActivityExecutor
from framework.harness.runtime.graph_dispatcher import HarnessGraphPhysicalActivityDispatcher
from framework.harness import InMemoryHarnessNodeOutputResource
from framework.shared.attempts import AttemptSupervisor


IDENTITY_SCOPE_REF = checksum_for({"tenant_id": "tenant-compensation"})
SUBJECT_SCOPE_REF = checksum_for({"paper_id": "paper-compensation"})


class _OutcomeAwareEventPort(InMemoryHarnessEventPort):
    def __init__(self, store: InMemoryHarnessSideEffectStore) -> None:
        super().__init__()
        self._store = store
        self.outcome_was_durable_at_completion_commit = False

    def commit_graph_decision(self, decision, **kwargs):
        if decision.decision_type is HarnessGraphDecisionType.COMPLETE_NODE:
            outcome_ref = kwargs.get("side_effect_outcome_ref")
            assert outcome_ref is not None
            assert any(
                outcome.checksum == outcome_ref
                for outcome in self._store.outcomes_by_effect.values()
            )
            self.outcome_was_durable_at_completion_commit = True
        return super().commit_graph_decision(decision, **kwargs)


class _DecisionDispositionSideEffectHandler(CountingHarnessSideEffectHandler):
    def commit(self, intent, authorization):
        self.disposition = authorization.disposition
        return super().commit(intent, authorization)


class _FailBeforeWorkerSideEffectControlPlane(HarnessControlPlane):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.failed = False

    def _prepare_worker_side_effect(self, *args, **kwargs):
        if not self.failed:
            self.failed = True
            raise RuntimeError("injected crash before completion decision")
        return super()._prepare_worker_side_effect(*args, **kwargs)


class _FailBeforeCompensationCallPort(InMemoryHarnessEventPort):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def accept_graph_activity(
        self,
        activity,
        graph,
        inputs,
        *,
        accepted_at,
        started_at,
    ):
        if not self.failed and activity.node_id.startswith("compensation:"):
            self.failed = True
            raise RuntimeError("injected crash before compensation handler call")
        return super().accept_graph_activity(
            activity,
            graph,
            inputs,
            accepted_at=accepted_at,
            started_at=started_at,
        )


class _FailAfterCompensationResultControlPlane(HarnessControlPlane):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.failed_after_compensation_result = False

    def accept_graph_activity_result(self, run_spec, result, *, occurred_at):
        transition_port = self.graph_transition_port
        activity = (
            None
            if transition_port is None
            else transition_port.activity_for(result.activity_id)
        )
        if (
            not self.failed_after_compensation_result
            and activity is not None
            and activity.node_id.startswith("compensation:")
        ):
            self.failed_after_compensation_result = True
            raise RuntimeError("injected crash after compensation result")
        return super().accept_graph_activity_result(
            run_spec,
            result,
            occurred_at=occurred_at,
        )


class _MaterializedResultControlPlane(HarnessControlPlane):
    def accept_graph_activity_result(self, run_spec, result, *, occurred_at):
        self._prepare_run_spec(run_spec)
        graph_runtime = self._require_graph_runtime()
        activity = graph_runtime.transition_port.activity_for(result.activity_id)
        if activity is None or activity.tenant_scope_ref is None:
            raise AssertionError("materialized compensation fixture lost activity scope")
        graph = self._prepared_graphs[run_spec.run_id]
        run_checksum = self._prepared_run_specs[run_spec.run_id]
        adapter = HarnessGraphResultRuntime(graph_runtime)
        binding = adapter.binding_for_activity(
            activity_id=activity.activity_id,
            graph=graph,
            tenant_id="tenant-compensation",
            tenant_scope_ref=activity.tenant_scope_ref,
            attempt_id=f"physical-{activity.activity_id}",
            run_spec_checksum=run_checksum,
        )
        projection = {"worker_status": result.status.value}
        summary = BoundedSummary.from_text(
            f"{activity.node_id} {result.status.value}"
        )
        candidate_bytes = 64
        artifacts = ()
        mode = PersistenceMode.INLINE
        reason = PersistenceReason.BELOW_INLINE_THRESHOLD
        artifact_class = ArtifactClass.CONTROL
        retention_class = RetentionClass.RUN
        reserved_bytes = 0
        inline_projection = projection
        if activity.node_id == "publish":
            artifacts = (
                ArtifactRecord(
                    ref=(
                        "artifact://tenant-compensation/"
                        f"{run_spec.run_id}/{activity.activity_id}"
                    ),
                    artifact_id=f"result-{activity.activity_id}",
                    artifact_type="node_result",
                    content_checksum=result.payload_ref,
                    byte_size=candidate_bytes,
                    media_type="application/json",
                    artifact_class=ArtifactClass.EVIDENCE,
                    tenant_id=binding.tenant_id,
                    run_id=binding.run_id,
                    graph_id=binding.graph_id,
                    node_id=binding.node_id,
                    attempt_id=binding.attempt_id,
                    producer_revision="test-worker-build@1",
                    sensitivity=ResultSensitivity.INTERNAL,
                    reusable=False,
                    dependency_digest=None,
                    retention_class=RetentionClass.EVIDENCE,
                    expires_at=None,
                    required_for_replay=True,
                    required_for_publication=False,
                    created_at=occurred_at,
                ),
            )
            mode = PersistenceMode.ARTIFACT
            reason = PersistenceReason.REQUIRED_FOR_REPLAY
            artifact_class = ArtifactClass.EVIDENCE
            retention_class = RetentionClass.EVIDENCE
            reserved_bytes = candidate_bytes
            inline_projection = {}
        envelope = NodeResultEnvelope(
            binding=binding,
            status=(
                NodeResultStatus.SUCCEEDED
                if result.status is HarnessGraphActivityResultStatus.SUCCEEDED
                else NodeResultStatus.FAILED
            ),
            output_schema_ref="compensation-result@1",
            output_schema_digest=checksum_for("compensation-result@1"),
            candidate_checksum=result.payload_ref,
            summary=summary,
            inline_projection=inline_projection,
            materialized_refs=artifacts,
            cache_refs=(),
            provenance=ResultProvenance(
                producer_ref="test-worker@1",
                producer_revision="test-worker-build@1",
            ),
            persistence_decision=PersistenceDecision(
                mode=mode,
                reason=reason,
                artifact_class=artifact_class,
                retention_class=retention_class,
                estimated_bytes=candidate_bytes,
                reserved_bytes=reserved_bytes,
                context_policy=ContextPolicy.SUMMARY_ONLY,
                required=mode is PersistenceMode.ARTIFACT,
                policy_version="graph-artifact-policy@1",
            ),
            metrics=ResultMetrics(
                candidate_bytes=candidate_bytes,
                candidate_tokens=16,
                summary_bytes=summary.byte_size,
                inline_bytes=(
                    len(canonical_json_bytes(inline_projection))
                    if mode is PersistenceMode.INLINE
                    else 0
                ),
            ),
            created_at=occurred_at,
        )
        return adapter.accept_materialized_result(
            envelope,
            expected_binding=binding,
            activity_id=activity.activity_id,
            graph=graph,
            run_spec_checksum=run_checksum,
            occurred_at=occurred_at,
        )


class _FailBeforeCompensationCompletionProjectionPort(InMemoryHarnessEventPort):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def commit_graph_projection(self, projection, **kwargs):
        recovery = self._graph_transition_port.recover_graph(projection.state.run_id)
        causal = next(
            (
                commit.decision
                for commit in recovery.pending_decisions
                if commit.decision.decision_checksum == projection.cause_checksum
            ),
            None,
        )
        if (
            not self.failed
            and causal is not None
            and causal.decision_type is HarnessGraphDecisionType.COMPLETE_NODE
            and causal.node_id is not None
            and causal.node_id.startswith("compensation:")
        ):
            self.failed = True
            raise RuntimeError("injected crash before compensation completion projection")
        return super().commit_graph_projection(projection, **kwargs)


class _FailBeforeCompletionProjectionPort(_OutcomeAwareEventPort):
    def __init__(self, store: InMemoryHarnessSideEffectStore) -> None:
        super().__init__(store)
        self.failed = False

    def commit_graph_projection(self, projection, **kwargs):
        if (
            not self.failed
            and projection.commit_kind is HarnessGraphCommitKind.DECISION_PROJECTION
        ):
            recovery = self._graph_transition_port.recover_graph(
                projection.state.run_id
            )
            causal = next(
                (
                    commit.decision
                    for commit in recovery.pending_decisions
                    if commit.decision.decision_checksum == projection.cause_checksum
                ),
                None,
            )
            if (
                causal is not None
                and causal.decision_type is HarnessGraphDecisionType.COMPLETE_NODE
            ):
                self.failed = True
                raise RuntimeError("injected crash before complete_node projection")
        return super().commit_graph_projection(projection, **kwargs)


class _StopAfterCompletionProjectionPort(_OutcomeAwareEventPort):
    def __init__(self, store: InMemoryHarnessSideEffectStore) -> None:
        super().__init__(store)
        self.stopped = False

    def commit_graph_projection(self, projection, **kwargs):
        recovery = self._graph_transition_port.recover_graph(projection.state.run_id)
        causal = next(
            (
                commit.decision
                for commit in recovery.pending_decisions
                if commit.decision.decision_checksum == projection.cause_checksum
            ),
            None,
        )
        committed = super().commit_graph_projection(projection, **kwargs)
        if (
            not self.stopped
            and causal is not None
            and causal.decision_type is HarnessGraphDecisionType.COMPLETE_NODE
        ):
            self.stopped = True
            raise RuntimeError("injected stop after complete_node projection")
        return committed


class _FailGate(DeterministicGate):
    gate_name = "compensation_verify_failure"

    def evaluate(self, context) -> HarnessGateResult:
        del context
        return HarnessGateResult(
            gate_name=self.gate_name,
            passed=False,
            reason="injected verification failure",
        )


@dataclass
class _CandidateWorker:
    worker_id: str = "test.publish"
    worker_version: str = "1"
    worker_type: str = "function"
    call_count: int = 0

    def execute(self, task: dict) -> HarnessWorkerResult:
        self.call_count += 1
        output = {"candidate": "ok"}
        artifact_ref = f"candidate://{task['run_id']}/report"
        candidate_payload = {
            "status": "succeeded",
            "output": output,
            "artifacts": [artifact_ref],
            "diagnostics": {},
            "metrics": {},
            "error": None,
        }
        activity = task["harness_graph_activity"]["activity"]
        graph_ref = activity["graph_ref"]
        graph_contract = graph_ref["graph_ref"]
        attempt = activity["attempt"]
        return HarnessWorkerResult(
            status="succeeded",
            output=output,
            artifacts=(artifact_ref,),
            effect_intent=HarnessSideEffectIntent(
                effect_id=f"effect-{task['run_id']}-{task['step_id']}-{attempt}",
                kind="artifact",
                run_id=task["run_id"],
                graph_id=graph_ref["graph_id"],
                graph_version=graph_contract["version"],
                graph_ref=f"{graph_ref['graph_id']}@{graph_contract['version']}",
                graph_checksum=graph_ref["checksum"],
                origin="worker",
                atomic_group=f"group-{task['run_id']}",
                identity_scope_ref=IDENTITY_SCOPE_REF,
                subject_scope_ref=SUBJECT_SCOPE_REF,
                attempt=attempt,
                step_id=task["step_id"],
                node_id=activity["node_id"],
                node_instance_id=activity["node_instance_id"],
                activity_id=activity["activity_id"],
                worker_result_ref=harness_worker_candidate_ref(candidate_payload),
                candidate_checksum=checksum_for({"candidate": output}),
                handler="research.prepare@1",
                candidate_refs=(artifact_ref,),
            ),
        )


@dataclass
class _CompensationWorker:
    worker_id: str = "test.undo"
    worker_version: str = "1"
    worker_type: str = "function"
    call_count: int = 0

    def execute(self, task: dict) -> HarnessWorkerResult:
        self.call_count += 1
        return HarnessWorkerResult("succeeded", output={"compensated": task["run_id"]})


@dataclass
class _FailingWorker:
    worker_id: str = "test.fail"
    worker_version: str = "1"
    worker_type: str = "function"
    call_count: int = 0

    def execute(self, task: dict) -> HarnessWorkerResult:
        self.call_count += 1
        return HarnessWorkerResult("failed", error=f"{task['step_id']} failed")


@dataclass(frozen=True)
class _Activity:
    activity_contract_id: str
    activity_contract_version: str
    capabilities: HarnessActivityCapabilities = HarnessActivityCapabilities(
        termination_confirmation=True,
        stable_idempotency=True,
        fencing=True,
        reconciliation=True,
    )

    def dispatch(self, request) -> None:
        del request


@dataclass
class _CompensationHandler:
    compensation_handler_id: str = "research.undo"
    compensation_handler_version: str = "1"
    call_count: int = 0
    last_request: dict | None = None
    fail_first: bool = False
    label: str = "undo"
    call_order: list[str] | None = None

    def compensate(self, request) -> dict[str, object]:
        self.call_count += 1
        self.last_request = dict(request)
        if self.call_order is not None:
            self.call_order.append(self.label)
        if self.fail_first and self.call_count == 1:
            return {"status": "failed", "error": "transient compensation failure"}
        return {"compensated": True}


@dataclass
class _RuntimeFixture:
    control_plane: HarnessControlPlane
    run_spec: HarnessRunSpec
    event_port: InMemoryHarnessEventPort
    store: InMemoryHarnessSideEffectStore
    side_effect_handler: CountingHarnessSideEffectHandler
    worker: _CandidateWorker
    compensation_worker: _CompensationWorker
    compensation_handler: _CompensationHandler


@dataclass
class _ParallelRuntimeFixture:
    control_plane: HarnessControlPlane
    run_spec: HarnessRunSpec
    event_port: InMemoryHarnessEventPort
    store: InMemoryHarnessSideEffectStore
    side_effect_handler: CountingHarnessSideEffectHandler
    publish_worker: _CandidateWorker
    failing_worker: _FailingWorker
    compensation_worker: _CompensationWorker
    compensation_handler: _CompensationHandler


@dataclass
class _MultiEffectRuntimeFixture:
    control_plane: HarnessControlPlane
    run_spec: HarnessRunSpec
    event_port: InMemoryHarnessEventPort
    first_handler: _CompensationHandler
    second_handler: _CompensationHandler
    call_order: list[str]


def test_compensation_entry_follows_durable_outcome_and_successful_verify() -> None:
    store = InMemoryHarnessSideEffectStore()
    event_port = _StopAfterCompletionProjectionPort(store)
    fixture = _fixture("run-compensation-success", store=store, event_port=event_port)

    with pytest.raises(RuntimeError, match="after complete_node projection"):
        fixture.control_plane.run(fixture.run_spec)

    assert event_port.outcome_was_durable_at_completion_commit
    assert fixture.side_effect_handler.call_count == 1
    assert fixture.store.outcome_write_count == 1
    recovery = event_port.recover_graph(fixture.run_spec.run_id)
    assert recovery.state is not None
    state = recovery.state
    origin = _origin_node(state)
    assert origin.status is HarnessNodeInstanceStatus.SUCCEEDED
    assert origin.step_status is HarnessStepStatus.SUCCEEDED
    evidence_kinds = {item.kind for item in origin.evidence_refs}
    assert HarnessEvidenceKind.GATE_RESULT in evidence_kinds
    assert HarnessEvidenceKind.SIDE_EFFECT_OUTCOME in evidence_kinds
    outcome = next(iter(store.outcomes_by_effect.values()))
    entry = _only_compensation_entry(state)
    assert entry.origin_node_instance_id == origin.instance_id
    assert entry.effect_outcome_ref == outcome.checksum

    completion = next(
        commit
        for commit in recovery.decision_commits
        if commit.decision.decision_type is HarnessGraphDecisionType.COMPLETE_NODE
        and commit.decision.node_id == "publish"
    )
    outcome_observation = next(
        commit
        for commit in recovery.observation_commits
        if commit.observation.observation_type
        is HarnessGraphObservationType.SIDE_EFFECT_OUTCOME
        and commit.observation.evidence_ref == outcome.checksum
    )
    assert completion.side_effect_outcome_ref == outcome.checksum
    assert entry.effect_commit_sequence == outcome_observation.sequence
    assert outcome_observation.sequence < completion.sequence


def test_successful_run_retains_dormant_pending_compensation_evidence() -> None:
    fixture = _fixture("run-compensation-success-terminal")

    result = fixture.control_plane.run(fixture.run_spec)

    assert result.succeeded
    assert result.state is not None
    assert result.state.lifecycle is RunLifecycle.COMPLETED
    assert result.state.outcome is RunOutcome.SUCCEEDED
    entry = _only_compensation_entry(result.state)
    assert entry.status is HarnessCompensationStatus.PENDING
    assert entry.compensation_node_instance_id is None
    assert entry.outcome_ref is None


def test_terminal_side_effect_uses_only_explicit_terminal_run_binding() -> None:
    run_id = "run-terminal-compensation-entry"
    store = InMemoryHarnessSideEffectStore()
    side_effect_handler = _DecisionDispositionSideEffectHandler(store)
    fixture = _fixture(
        run_id,
        run_spec=_terminal_compensation_run_spec(run_id),
        store=store,
        side_effect_handler=side_effect_handler,
    )

    result = fixture.control_plane.run(fixture.run_spec)

    assert result.state is not None
    assert result.state.outcome is RunOutcome.SUCCEEDED
    assert fixture.side_effect_handler.call_count == 2
    entries = result.state.compensation_stack
    assert len(entries) == 2
    node_entry, terminal_entry = entries
    assert node_entry.effect_commit_sequence < terminal_entry.effect_commit_sequence
    node_slot = next(
        key for key in result.side_effect_outcomes if not key.startswith("terminal:")
    )
    assert node_entry.effect_outcome_ref == result.side_effect_outcomes[node_slot].checksum
    terminal_slot = next(
        key for key in result.side_effect_outcomes if key.startswith("terminal:")
    )
    assert terminal_entry.effect_outcome_ref == result.side_effect_outcomes[terminal_slot].checksum
    assert node_entry.status is HarnessCompensationStatus.PENDING
    assert terminal_entry.status is HarnessCompensationStatus.PENDING
    origin = _origin_node(result.state)
    assert origin.metadata["terminal_compensation_binding_id"] == "undo-terminal"
    assert origin.metadata["terminal_side_effect_outcome_ref"] == (
        terminal_entry.effect_outcome_ref
    )


def test_parallel_failure_executes_compensation_handler_through_full_lifecycle() -> (
    None
):
    fixture = _parallel_compensation_fixture("run-parallel-compensation")

    result = fixture.control_plane.run(fixture.run_spec)

    assert result.state is not None
    state = result.state
    assert state.lifecycle is RunLifecycle.COMPLETED
    assert state.outcome is RunOutcome.COMPENSATED
    assert fixture.publish_worker.call_count == 1
    assert fixture.failing_worker.call_count == 1
    assert fixture.compensation_worker.call_count == 0
    assert fixture.compensation_handler.call_count == 1
    assert fixture.side_effect_handler.call_count == 1

    entry = _only_compensation_entry(state)
    assert entry.status is HarnessCompensationStatus.SUCCEEDED
    assert entry.outcome_ref is not None
    compensation_node = next(
        item
        for item in state.node_instances
        if item.instance_id == entry.compensation_node_instance_id
    )
    assert compensation_node.status is HarnessNodeInstanceStatus.COMPENSATED
    assert compensation_node.step_status is HarnessStepStatus.SUCCEEDED
    assert {
        evidence.kind for evidence in compensation_node.evidence_refs
    }.issuperset(
        {HarnessEvidenceKind.ACTIVITY_RESULT, HarnessEvidenceKind.GATE_RESULT}
    )

    recovery = fixture.event_port.recover_graph(fixture.run_spec.run_id)
    phase_decisions = tuple(
        commit
        for commit in recovery.decision_commits
        if commit.decision.node_instance_id == compensation_node.instance_id
        and commit.decision.decision_type
        in {
            HarnessGraphDecisionType.ENTER_STEP_PHASE,
            HarnessGraphDecisionType.DISPATCH_ACTIVITY,
            HarnessGraphDecisionType.VERIFY_ACTIVITY_RESULT,
            HarnessGraphDecisionType.COMPLETE_NODE,
        }
    )
    assert tuple(item.decision.decision_type for item in phase_decisions) == (
        HarnessGraphDecisionType.ENTER_STEP_PHASE,
        HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        HarnessGraphDecisionType.VERIFY_ACTIVITY_RESULT,
        HarnessGraphDecisionType.COMPLETE_NODE,
    )
    expected_bindings = dict(phase_decisions[0].decision.binding_versions)
    assert all(
        dict(item.decision.binding_versions) == expected_bindings
        for item in phase_decisions
    )
    assert expected_bindings["activity"] == entry.activity_ref.exact_ref
    assert expected_bindings["compensation"] == entry.handler_ref.exact_ref
    assert entry.outcome_ref == phase_decisions[-1].decision.decision_checksum

    activity = next(
        item
        for item in recovery.activities
        if item.node_instance_id == compensation_node.instance_id
    )
    assert activity.activity_ref == entry.activity_ref
    assert activity.fencing_generation == entry.fencing_generation
    request = fixture.compensation_handler.last_request
    assert request is not None
    assert request["entry_id"] == entry.entry_id
    assert request["origin_node_instance_id"] == entry.origin_node_instance_id
    assert request["effect_outcome_ref"] == entry.effect_outcome_ref
    assert request["idempotency_key"] == entry.idempotency_key
    assert request["fencing_generation"] == entry.fencing_generation

    phase_events = tuple(
        (event.payload["phase"], event.payload["boundary"])
        for event in result.events
        if event.event_type.value == "graph_phase_transition_recorded"
        and event.node_id == "compensation:undo-publish"
    )
    assert phase_events == (
        ("plan", "entry"),
        ("plan", "exit"),
        ("execute", "entry"),
        ("execute", "exit"),
        ("verify", "entry"),
        ("verify", "exit"),
    )
    assert state.budgets.require("compensations").used == 1
    assert state.budgets.require("worker_calls").used == 3


def test_compensation_lineage_preserves_original_materialized_evidence() -> None:
    fixture = _parallel_compensation_fixture(
        "run-materialized-compensation",
        control_plane_type=_MaterializedResultControlPlane,
    )

    result = fixture.control_plane.run(fixture.run_spec)

    assert result.state is not None
    state = result.state
    assert state.outcome is RunOutcome.COMPENSATED
    original = next(
        item for item in state.node_instances if item.identity.node_id == "publish"
    )
    entry = _only_compensation_entry(state)
    compensation = next(
        item
        for item in state.node_instances
        if item.instance_id == entry.compensation_node_instance_id
    )
    original_lineage = original.output_refs["activity_result_lineage"]
    compensation_lineage = compensation.output_refs["activity_result_lineage"]
    assert original_lineage["persistence_mode"] == "artifact"
    assert len(original_lineage["artifact_refs"]) == 1
    assert compensation_lineage["persistence_mode"] == "inline"
    assert compensation_lineage["inline_projection"] == {
        "worker_status": "succeeded"
    }
    assert original_lineage["lineage_checksum"] != (
        compensation_lineage["lineage_checksum"]
    )
    assert original.output_refs["activity_result_lineage"] == original_lineage
    assert original.evidence_refs
    assert compensation.evidence_refs

    recovery = fixture.event_port.recover_graph(fixture.run_spec.run_id)
    lineage_by_node = {
        commit.result.result_lineage.node_id: commit.result.result_lineage
        for commit in recovery.activity_result_commits
        if commit.result.result_lineage is not None
    }
    assert lineage_by_node["publish"].artifact_refs[0].ref == (
        original_lineage["artifact_refs"][0]["ref"]
    )
    assert lineage_by_node["compensation:undo-publish"].artifact_refs == ()


def test_compensation_retry_keeps_idempotency_and_advances_fencing() -> None:
    handler = _CompensationHandler(fail_first=True)
    fixture = _parallel_compensation_fixture(
        "run-parallel-compensation-retry",
        compensation_handler=handler,
        max_retries_per_step=1,
        max_worker_calls=4,
    )

    result = fixture.control_plane.run(fixture.run_spec)

    assert result.state is not None
    assert result.state.outcome is RunOutcome.COMPENSATED
    assert handler.call_count == 2
    recovery = fixture.event_port.recover_graph(fixture.run_spec.run_id)
    activities = tuple(
        sorted(
            (
                item
                for item in recovery.activities
                if item.node_id == "compensation:undo-publish"
            ),
            key=lambda item: item.attempt,
        )
    )
    assert len(activities) == 2
    assert {item.idempotency_key for item in activities} == {
        activities[0].idempotency_key
    }
    assert tuple(item.fencing_generation for item in activities) == (1, 2)
    entry = _only_compensation_entry(result.state)
    assert entry.fencing_generation == 2
    dispatches = tuple(
        item
        for item in recovery.decision_commits
        if item.decision.decision_type is HarnessGraphDecisionType.DISPATCH_ACTIVITY
        and item.decision.node_id == "compensation:undo-publish"
    )
    assert len(dispatches) == 2
    assert all(
        item.decision.binding_versions["activity"] == entry.activity_ref.exact_ref
        and item.decision.binding_versions["compensation"]
        == entry.handler_ref.exact_ref
        for item in dispatches
    )


def test_compensation_failure_halts_with_manual_intervention_evidence() -> None:
    handler = _CompensationHandler(fail_first=True)
    fixture = _parallel_compensation_fixture(
        "run-parallel-compensation-failed",
        compensation_handler=handler,
    )

    result = fixture.control_plane.run(fixture.run_spec)

    assert result.state is not None
    state = result.state
    assert state.lifecycle is RunLifecycle.HALTED
    assert state.outcome is RunOutcome.COMPENSATION_FAILED
    entry = _only_compensation_entry(state)
    assert entry.status is HarnessCompensationStatus.FAILED
    assert entry.outcome_ref is not None
    manual = state.metadata["manual_intervention"]
    assert manual["required"] is True
    assert manual["reason_code"] == "compensation_failed"
    assert manual["decision_ref"] == state.terminal_evidence_ref
    assert entry.outcome_ref in manual["evidence_refs"]
    assert fixture.compensation_worker.call_count == 0


def test_recovery_after_compensation_dispatch_calls_handler_once() -> None:
    event_port = _FailBeforeCompensationCallPort()
    fixture = _parallel_compensation_fixture(
        "run-compensation-dispatch-recovery",
        event_port=event_port,
    )

    with pytest.raises(RuntimeError, match="before compensation handler call"):
        fixture.control_plane.run(fixture.run_spec)

    interrupted = event_port.recover_graph(fixture.run_spec.run_id)
    assert fixture.compensation_handler.call_count == 0
    assert any(
        item.node_id == "compensation:undo-publish"
        for item in interrupted.activities
    )
    assert interrupted.state is not None
    assert any(
        item.node_id == "compensation:undo-publish"
        for item in (
            event_port.activity_for(active.activity_id)
            for active in interrupted.state.active_activities
        )
        if item is not None
    )

    recovered = fixture.control_plane.recover_and_run(fixture.run_spec)

    assert recovered.state is not None
    assert recovered.state.outcome is RunOutcome.COMPENSATED
    assert fixture.compensation_handler.call_count == 1
    assert fixture.compensation_worker.call_count == 0


def test_recovery_reuses_durable_compensation_result_without_recalling_handler() -> (
    None
):
    fixture = _parallel_compensation_fixture(
        "run-compensation-result-recovery",
        control_plane_type=_FailAfterCompensationResultControlPlane,
    )

    with pytest.raises(RuntimeError, match="after compensation result"):
        fixture.control_plane.run(fixture.run_spec)

    assert fixture.compensation_handler.call_count == 1
    interrupted = fixture.event_port.recover_graph(fixture.run_spec.run_id)
    assert interrupted.state is not None
    compensation_activity = next(
        item
        for item in interrupted.activities
        if item.node_id == "compensation:undo-publish"
    )
    assert compensation_activity.activity_id in fixture.event_port.activity_results
    assert all(
        item.result.activity_id != compensation_activity.activity_id
        for item in interrupted.activity_result_commits
    )

    recovered = fixture.control_plane.recover_and_run(fixture.run_spec)

    assert recovered.state is not None
    assert recovered.state.outcome is RunOutcome.COMPENSATED
    assert fixture.compensation_handler.call_count == 1
    graph_recovery = fixture.event_port.recover_graph(fixture.run_spec.run_id)
    assert (
        sum(
            item.result.activity_id == compensation_activity.activity_id
            for item in graph_recovery.activity_result_commits
        )
        == 1
    )
    replayed = fixture.control_plane.recover_and_run(fixture.run_spec)
    assert replayed.state is not None
    assert (
        replayed.state.projection_checksum
        == recovered.state.projection_checksum
    )
    assert fixture.compensation_handler.call_count == 1


def test_recovery_projects_committed_compensation_completion_exactly_once() -> None:
    event_port = _FailBeforeCompensationCompletionProjectionPort()
    fixture = _parallel_compensation_fixture(
        "run-compensation-completion-recovery",
        event_port=event_port,
    )

    with pytest.raises(RuntimeError, match="compensation completion projection"):
        fixture.control_plane.run(fixture.run_spec)

    interrupted = event_port.recover_graph(fixture.run_spec.run_id)
    assert len(interrupted.pending_decisions) == 1
    completion = interrupted.pending_decisions[0]
    assert completion.decision.decision_type is HarnessGraphDecisionType.COMPLETE_NODE
    assert completion.decision.node_id == "compensation:undo-publish"
    assert fixture.compensation_handler.call_count == 1

    recovered = fixture.control_plane.recover_and_run(fixture.run_spec)
    first = fixture.control_plane.recover_graph(fixture.run_spec)
    second = fixture.control_plane.recover_graph(fixture.run_spec)

    assert recovered.state is not None
    assert recovered.state.outcome is RunOutcome.COMPENSATED
    assert first == second == recovered.state
    assert fixture.compensation_handler.call_count == 1
    final_recovery = event_port.recover_graph(fixture.run_spec.run_id)
    assert final_recovery.pending_decisions == ()
    assert (
        sum(
            projection.cause_checksum == completion.decision.decision_checksum
            for projection in final_recovery.projection_commits
        )
        == 1
    )


def test_parallel_effects_compensate_in_reverse_order_and_preserve_partial_failure() -> (
    None
):
    fixture = _multi_effect_compensation_fixture(
        "run-multi-effect-partial-failure",
        fail_first_handler=True,
    )

    result = fixture.control_plane.run(fixture.run_spec)

    assert result.state is not None
    state = result.state
    assert state.lifecycle is RunLifecycle.HALTED
    assert state.outcome is RunOutcome.COMPENSATION_FAILED
    entries = state.compensation_stack
    assert len(entries) == 2
    first_entry = next(
        item for item in entries if item.handler_ref.contract_id == "research.undo.first"
    )
    second_entry = next(
        item for item in entries if item.handler_ref.contract_id == "research.undo.second"
    )
    assert first_entry.effect_commit_sequence < second_entry.effect_commit_sequence
    assert first_entry.status is HarnessCompensationStatus.FAILED
    assert second_entry.status is HarnessCompensationStatus.SUCCEEDED
    assert fixture.call_order == ["second", "first"]
    assert state.metadata["manual_intervention"]["reason_code"] == (
        "compensation_failed"
    )


def test_compensation_budget_exhaustion_preserves_remaining_entry_for_manual_work() -> (
    None
):
    fixture = _multi_effect_compensation_fixture(
        "run-multi-effect-budget-exhausted",
        max_compensations=1,
    )

    result = fixture.control_plane.run(fixture.run_spec)

    assert result.state is not None
    state = result.state
    assert state.lifecycle is RunLifecycle.HALTED
    assert state.outcome is RunOutcome.COMPENSATION_FAILED
    first_entry = next(
        item
        for item in state.compensation_stack
        if item.handler_ref.contract_id == "research.undo.first"
    )
    second_entry = next(
        item
        for item in state.compensation_stack
        if item.handler_ref.contract_id == "research.undo.second"
    )
    assert first_entry.status is HarnessCompensationStatus.PENDING
    assert second_entry.status is HarnessCompensationStatus.SUCCEEDED
    assert fixture.call_order == ["second"]
    assert state.budgets.require("compensations").used == 1
    manual = state.metadata["manual_intervention"]
    assert manual["reason_code"] == "compensation_budget_exhausted"
    assert first_entry.effect_outcome_ref in manual["evidence_refs"]


def test_indeterminate_compensation_result_atomically_halts_node_and_entry() -> None:
    fixture = _parallel_compensation_fixture("run-compensation-indeterminate")
    fixture.control_plane.run(fixture.run_spec)
    recovery = fixture.event_port.recover_graph(fixture.run_spec.run_id)
    dispatch = next(
        item
        for item in recovery.decision_commits
        if item.decision.decision_type is HarnessGraphDecisionType.DISPATCH_ACTIVITY
        and item.decision.node_id == "compensation:undo-publish"
    )
    dispatch_projection = next(
        item
        for item in recovery.projection_commits
        if item.cause_checksum == dispatch.decision.decision_checksum
    )
    activity = next(
        item
        for item in recovery.activities
        if item.causal_decision_checksum == dispatch.decision.decision_checksum
    )
    evidence_ref = checksum_for({"activity_id": activity.activity_id, "uncertain": True})
    result = HarnessGraphActivityResult.for_activity(
        activity,
        evidence_ref=evidence_ref,
        payload_ref=checksum_for({"outcome": "unknown"}),
        status=HarnessGraphActivityResultStatus.INDETERMINATE,
        termination_confirmed=False,
    )

    projected = HarnessGraphDecisionApplier().apply_activity_result(
        dispatch_projection.state,
        activity,
        result,
        result_sequence=dispatch_projection.state.last_event_sequence + 1,
        projection_sequence=dispatch_projection.state.last_event_sequence + 2,
    )

    entry = _only_compensation_entry(projected)
    node = next(
        item
        for item in projected.node_instances
        if item.instance_id == entry.compensation_node_instance_id
    )
    assert entry.status is HarnessCompensationStatus.INDETERMINATE
    assert entry.outcome_ref == evidence_ref
    assert node.status is HarnessNodeInstanceStatus.HALTED
    assert projected.lifecycle is RunLifecycle.HALTED
    assert projected.outcome is RunOutcome.INDETERMINATE
    assert projected.terminal_evidence_ref == evidence_ref
    assert projected.active_activities[0].activity_id == activity.activity_id
    assert projected.metadata["manual_intervention"]["evidence_ref"] == evidence_ref


def test_effectful_completion_without_durable_outcome_fails_closed() -> None:
    event_port = InMemoryHarnessEventPort()
    fixture = _fixture(
        "run-compensation-missing-outcome",
        event_port=event_port,
        control_plane_type=_FailBeforeWorkerSideEffectControlPlane,
    )

    with pytest.raises(RuntimeError, match="before completion decision"):
        fixture.control_plane.run(fixture.run_spec)

    verifying = fixture.control_plane.recover_graph(fixture.run_spec)
    origin = _origin_node(verifying)
    assert origin.step_status is HarnessStepStatus.VERIFYING
    assert verifying.compensation_stack == ()
    assert fixture.store.outcome_write_count == 0
    graph = fixture.control_plane._prepared_graphs[fixture.run_spec.run_id]
    completion = _step_decision(
        verifying,
        graph,
        origin.instance_id,
        HarnessGraphDecisionType.COMPLETE_NODE,
    )
    before = event_port.recover_graph(fixture.run_spec.run_id)

    with pytest.raises(HarnessValidationError) as captured:
        fixture.control_plane.apply_graph_decision(
            fixture.run_spec,
            verifying,
            completion,
            occurred_at=fixture.run_spec.created_at,
        )

    assert captured.value.code == "graph_side_effect_outcome_missing"
    after = event_port.recover_graph(fixture.run_spec.run_id)
    assert after.expected_last_sequence == before.expected_last_sequence
    assert after.pending_decisions == ()
    assert after.state is not None
    assert after.state.compensation_stack == ()


def test_failed_verify_never_pushes_compensation_entry() -> None:
    fixture = _fixture(
        "run-compensation-verify-failed",
        verify_gates=(_FailGate(),),
    )

    result = fixture.control_plane.run(fixture.run_spec)

    assert not result.succeeded
    assert result.state is not None
    assert result.state.compensation_stack == ()
    assert fixture.side_effect_handler.call_count == 0
    assert fixture.store.decision_write_count == 0
    assert fixture.store.outcome_write_count == 0


def test_recovery_projects_committed_completion_without_replaying_side_effect() -> None:
    store = InMemoryHarnessSideEffectStore()
    event_port = _FailBeforeCompletionProjectionPort(store)
    fixture = _fixture("run-compensation-recovery", store=store, event_port=event_port)

    with pytest.raises(RuntimeError, match="before complete_node projection"):
        fixture.control_plane.run(fixture.run_spec)

    interrupted = event_port.recover_graph(fixture.run_spec.run_id)
    assert len(interrupted.pending_decisions) == 1
    pending = interrupted.pending_decisions[0]
    assert pending.decision.decision_type is HarnessGraphDecisionType.COMPLETE_NODE
    assert pending.side_effect_outcome_ref is not None
    assert fixture.side_effect_handler.call_count == 1
    assert fixture.worker.call_count == 1

    recovered_control_plane = _fixture(
        fixture.run_spec.run_id,
        store=store,
        event_port=event_port,
        side_effect_handler=fixture.side_effect_handler,
        worker=fixture.worker,
        compensation_worker=fixture.compensation_worker,
        compensation_handler=fixture.compensation_handler,
    ).control_plane
    recovered = recovered_control_plane.recover_graph(fixture.run_spec)

    assert len(recovered.compensation_stack) == 1
    entry = recovered.compensation_stack[0]
    assert entry.effect_outcome_ref == pending.side_effect_outcome_ref
    outcome_observation = next(
        commit
        for commit in event_port.recover_graph(
            fixture.run_spec.run_id
        ).observation_commits
        if commit.observation.observation_type
        is HarnessGraphObservationType.SIDE_EFFECT_OUTCOME
        and commit.observation.evidence_ref == pending.side_effect_outcome_ref
    )
    assert entry.effect_commit_sequence == outcome_observation.sequence
    assert outcome_observation.sequence < pending.sequence
    assert event_port.recover_graph(fixture.run_spec.run_id).pending_decisions == ()
    assert fixture.side_effect_handler.call_count == 1
    assert fixture.worker.call_count == 1
    assert store.outcome_write_count == 1


def test_duplicate_recovery_does_not_duplicate_compensation_entry() -> None:
    store = InMemoryHarnessSideEffectStore()
    event_port = _FailBeforeCompletionProjectionPort(store)
    fixture = _fixture(
        "run-compensation-duplicate-recovery",
        store=store,
        event_port=event_port,
    )

    with pytest.raises(RuntimeError, match="before complete_node projection"):
        fixture.control_plane.run(fixture.run_spec)

    recovered_control_plane = _fixture(
        fixture.run_spec.run_id,
        store=store,
        event_port=event_port,
        side_effect_handler=fixture.side_effect_handler,
        worker=fixture.worker,
        compensation_worker=fixture.compensation_worker,
        compensation_handler=fixture.compensation_handler,
    ).control_plane
    first = recovered_control_plane.recover_graph(fixture.run_spec)
    second = recovered_control_plane.recover_graph(fixture.run_spec)

    assert first == second
    assert len(first.compensation_stack) == 1
    entry = first.compensation_stack[0]
    assert second.compensation_stack == (entry,)
    recovery = event_port.recover_graph(fixture.run_spec.run_id)
    completion = next(
        commit
        for commit in recovery.decision_commits
        if commit.decision.decision_type is HarnessGraphDecisionType.COMPLETE_NODE
    )
    assert (
        sum(
            projection.commit_kind is HarnessGraphCommitKind.DECISION_PROJECTION
            and projection.cause_checksum == completion.decision.decision_checksum
            for projection in recovery.projection_commits
        )
        == 1
    )
    assert fixture.side_effect_handler.call_count == 1
    assert fixture.worker.call_count == 1


def _fixture(
    run_id: str,
    *,
    run_spec: HarnessRunSpec | None = None,
    store: InMemoryHarnessSideEffectStore | None = None,
    event_port: InMemoryHarnessEventPort | None = None,
    side_effect_handler: CountingHarnessSideEffectHandler | None = None,
    worker: _CandidateWorker | None = None,
    compensation_worker: _CompensationWorker | None = None,
    compensation_handler: _CompensationHandler | None = None,
    verify_gates: tuple[DeterministicGate, ...] | None = None,
    control_plane_type: type[HarnessControlPlane] = HarnessControlPlane,
) -> _RuntimeFixture:
    store = store or InMemoryHarnessSideEffectStore()
    event_port = event_port or InMemoryHarnessEventPort()
    side_effect_handler = side_effect_handler or _DecisionDispositionSideEffectHandler(
        store
    )
    worker = worker or _CandidateWorker()
    compensation_worker = compensation_worker or _CompensationWorker()
    compensation_handler = compensation_handler or _CompensationHandler()
    side_effect_registry = HarnessSideEffectRegistry(
        (
            HarnessSideEffectHandlerBinding(
                "research.prepare@1",
                "artifact",
                side_effect_handler,
            ),
        )
    )
    authority = HarnessRuntimeBindingAuthority(
        workers=(
            HarnessWorkerBinding("test.publish@1", "function", worker),
            HarnessWorkerBinding("test.undo@1", "function", compensation_worker),
        ),
        activities=(
            HarnessActivityContractBinding(
                "newsroom.harness-worker-activity@v1",
                _Activity("newsroom.harness-worker-activity", "v1"),
            ),
            HarnessActivityContractBinding(
                "research.undo.activity@1",
                _Activity("research.undo.activity", "1"),
            ),
        ),
        compensations=(
            HarnessCompensationHandlerBinding(
                "research.undo@1",
                compensation_handler,
            ),
        ),
        leaf_activities=tuple(
            HarnessLeafActivityBinding(
                HarnessLeafActivityKind.FUNCTION,
                f"test.{worker_id}@1",
                (
                    "research.undo.activity@1"
                    if worker_id == "undo"
                    else "newsroom.harness-worker-activity@v1"
                ),
            )
            for worker_id in ("publish", "undo")
        ),
        side_effect_registry=side_effect_registry,
    )
    kwargs = {}
    if verify_gates is not None:
        kwargs["verify_gates"] = verify_gates
    control_plane = control_plane_type(
            event_port=event_port,
            side_effect_registry=side_effect_registry,
            side_effect_store=store,
            runtime_binding_authority=authority,
            **kwargs,
        )
    _install_local_physical_dispatcher(control_plane)
    return _RuntimeFixture(
        control_plane=control_plane,
        run_spec=run_spec or _run_spec(run_id),
        event_port=event_port,
        store=store,
        side_effect_handler=side_effect_handler,
        worker=worker,
        compensation_worker=compensation_worker,
        compensation_handler=compensation_handler,
    )


def _parallel_compensation_fixture(
    run_id: str,
    *,
    event_port: InMemoryHarnessEventPort | None = None,
    compensation_handler: _CompensationHandler | None = None,
    max_retries_per_step: int = 0,
    max_worker_calls: int = 3,
    control_plane_type: type[HarnessControlPlane] = HarnessControlPlane,
) -> _ParallelRuntimeFixture:
    store = InMemoryHarnessSideEffectStore()
    event_port = event_port or InMemoryHarnessEventPort()
    side_effect_handler = CountingHarnessSideEffectHandler(store)
    publish_worker = _CandidateWorker()
    failing_worker = _FailingWorker()
    compensation_worker = _CompensationWorker()
    compensation_handler = compensation_handler or _CompensationHandler()
    side_effect_registry = HarnessSideEffectRegistry(
        (
            HarnessSideEffectHandlerBinding(
                "research.prepare@1",
                "artifact",
                side_effect_handler,
            ),
        )
    )
    authority = HarnessRuntimeBindingAuthority(
        workers=(
            HarnessWorkerBinding("test.publish@1", "function", publish_worker),
            HarnessWorkerBinding("test.fail@1", "function", failing_worker),
            HarnessWorkerBinding("test.undo@1", "function", compensation_worker),
        ),
        activities=(
            HarnessActivityContractBinding(
                "newsroom.harness-worker-activity@v1",
                _Activity("newsroom.harness-worker-activity", "v1"),
            ),
            HarnessActivityContractBinding(
                "research.undo.activity@1",
                _Activity("research.undo.activity", "1"),
            ),
        ),
        compensations=(
            HarnessCompensationHandlerBinding(
                "research.undo@1",
                compensation_handler,
            ),
        ),
        leaf_activities=(
            HarnessLeafActivityBinding(
                HarnessLeafActivityKind.FUNCTION,
                "test.publish@1",
                "newsroom.harness-worker-activity@v1",
            ),
            HarnessLeafActivityBinding(
                HarnessLeafActivityKind.FUNCTION,
                "test.fail@1",
                "newsroom.harness-worker-activity@v1",
            ),
            HarnessLeafActivityBinding(
                HarnessLeafActivityKind.FUNCTION,
                "test.undo@1",
                "research.undo.activity@1",
            ),
        ),
        side_effect_registry=side_effect_registry,
    )
    activities = (
            HarnessStepSpec(
                "publish",
                "function",
                output_key="candidate",
                side_effect_handler="research.prepare@1",
                metadata={
                    "step_version": "1",
                    "worker_id": "test.publish",
                    "worker_version": "1",
                },
            ),
            HarnessStepSpec(
                "fail",
                "function",
                output_key="failure_output",
                metadata={
                    "step_version": "1",
                    "worker_id": "test.fail",
                    "worker_version": "1",
                },
            ),
            HarnessStepSpec(
                "undo",
                "function",
                output_key="compensation_output",
                retry_policy=HarnessRetryPolicy(max_retries=1),
                metadata={
                    "step_version": "1",
                    "worker_id": "test.undo",
                    "worker_version": "1",
                },
            ),
        )
    graph = HarnessGraphSpec(
            graph_id="parallel-compensation-graph",
            root=ParallelAll(
                "fork",
                "join",
                (
                    ParallelBranch("publish-branch", StepRef("publish"), "parallel.publish"),
                    ParallelBranch("fail-branch", StepRef("fail"), "parallel.fail"),
                ),
                failure_policy="compensate",
            ),
            compensations=(
                CompensationBinding(
                    "undo-publish",
                    "publish",
                    "undo",
                    "research.undo@1",
                    "research.undo.activity@1",
                ),
            ),
        )
    run_spec = HarnessRunSpec(
        run_id=run_id,
        graph=_graph_definition(graph, activities),
        metadata={
            "tenant_scope_ref": checksum_for({"tenant_id": "tenant-compensation"}),
            "identity_scope_ref": IDENTITY_SCOPE_REF,
            "subject_scope_ref": SUBJECT_SCOPE_REF,
        },
        budget=HarnessBudget(
            max_turns=50,
            max_replans=0,
            max_retries_per_step=max_retries_per_step,
            max_worker_calls=max_worker_calls,
        ),
    )
    control_plane = control_plane_type(
            event_port=event_port,
            side_effect_registry=side_effect_registry,
            side_effect_store=store,
            runtime_binding_authority=authority,
            graph_preflight=HarnessGraphPreflight(
                policy=HarnessGraphPreflightPolicy(
                    max_node_activations=20,
                    max_active_nodes=6,
                    max_parallelism=1,
                )
            ),
        )
    _install_local_physical_dispatcher(control_plane)
    return _ParallelRuntimeFixture(
        control_plane=control_plane,
        run_spec=run_spec,
        event_port=event_port,
        store=store,
        side_effect_handler=side_effect_handler,
        publish_worker=publish_worker,
        failing_worker=failing_worker,
        compensation_worker=compensation_worker,
        compensation_handler=compensation_handler,
    )


def _multi_effect_compensation_fixture(
    run_id: str,
    *,
    fail_first_handler: bool = False,
    max_compensations: int = 10,
) -> _MultiEffectRuntimeFixture:
    store = InMemoryHarnessSideEffectStore()
    event_port = InMemoryHarnessEventPort()
    side_effect_handler = CountingHarnessSideEffectHandler(store)
    first_worker = _CandidateWorker(worker_id="test.first")
    second_worker = _CandidateWorker(worker_id="test.second")
    failing_worker = _FailingWorker()
    undo_first_worker = _CompensationWorker(worker_id="test.undo.first")
    undo_second_worker = _CompensationWorker(worker_id="test.undo.second")
    call_order: list[str] = []
    first_handler = _CompensationHandler(
        compensation_handler_id="research.undo.first",
        fail_first=fail_first_handler,
        label="first",
        call_order=call_order,
    )
    second_handler = _CompensationHandler(
        compensation_handler_id="research.undo.second",
        label="second",
        call_order=call_order,
    )
    side_effect_registry = HarnessSideEffectRegistry(
        (
            HarnessSideEffectHandlerBinding(
                "research.prepare@1",
                "artifact",
                side_effect_handler,
            ),
        )
    )
    authority = HarnessRuntimeBindingAuthority(
        workers=(
            HarnessWorkerBinding("test.first@1", "function", first_worker),
            HarnessWorkerBinding("test.second@1", "function", second_worker),
            HarnessWorkerBinding("test.fail@1", "function", failing_worker),
            HarnessWorkerBinding(
                "test.undo.first@1",
                "function",
                undo_first_worker,
            ),
            HarnessWorkerBinding(
                "test.undo.second@1",
                "function",
                undo_second_worker,
            ),
        ),
        activities=(
            HarnessActivityContractBinding(
                "newsroom.harness-worker-activity@v1",
                _Activity("newsroom.harness-worker-activity", "v1"),
            ),
            HarnessActivityContractBinding(
                "research.undo.first.activity@1",
                _Activity("research.undo.first.activity", "1"),
            ),
            HarnessActivityContractBinding(
                "research.undo.second.activity@1",
                _Activity("research.undo.second.activity", "1"),
            ),
        ),
        compensations=(
            HarnessCompensationHandlerBinding(
                "research.undo.first@1",
                first_handler,
            ),
            HarnessCompensationHandlerBinding(
                "research.undo.second@1",
                second_handler,
            ),
        ),
        leaf_activities=(
            HarnessLeafActivityBinding(
                HarnessLeafActivityKind.FUNCTION,
                "test.first@1",
                "newsroom.harness-worker-activity@v1",
            ),
            HarnessLeafActivityBinding(
                HarnessLeafActivityKind.FUNCTION,
                "test.second@1",
                "newsroom.harness-worker-activity@v1",
            ),
            HarnessLeafActivityBinding(
                HarnessLeafActivityKind.FUNCTION,
                "test.fail@1",
                "newsroom.harness-worker-activity@v1",
            ),
            HarnessLeafActivityBinding(
                HarnessLeafActivityKind.FUNCTION,
                "test.undo.first@1",
                "research.undo.first.activity@1",
            ),
            HarnessLeafActivityBinding(
                HarnessLeafActivityKind.FUNCTION,
                "test.undo.second@1",
                "research.undo.second.activity@1",
            ),
        ),
        side_effect_registry=side_effect_registry,
    )
    activities = (
            HarnessStepSpec(
                "first",
                "function",
                output_key="first_candidate",
                side_effect_handler="research.prepare@1",
                metadata={
                    "step_version": "1",
                    "worker_id": "test.first",
                    "worker_version": "1",
                },
            ),
            HarnessStepSpec(
                "second",
                "function",
                output_key="second_candidate",
                side_effect_handler="research.prepare@1",
                metadata={
                    "step_version": "1",
                    "worker_id": "test.second",
                    "worker_version": "1",
                },
            ),
            HarnessStepSpec(
                "fail",
                "function",
                output_key="fail_output",
                metadata={
                    "step_version": "1",
                    "worker_id": "test.fail",
                    "worker_version": "1",
                },
            ),
            HarnessStepSpec(
                "undo_first",
                "function",
                output_key="undo_first_output",
                metadata={
                    "step_version": "1",
                    "worker_id": "test.undo.first",
                    "worker_version": "1",
                },
            ),
            HarnessStepSpec(
                "undo_second",
                "function",
                output_key="undo_second_output",
                metadata={
                    "step_version": "1",
                    "worker_id": "test.undo.second",
                    "worker_version": "1",
                },
            ),
        )
    graph = HarnessGraphSpec(
            graph_id="multi-effect-compensation-graph",
            root=ParallelAll(
                "fork",
                "join",
                (
                    ParallelBranch("first-branch", StepRef("first"), "parallel.first"),
                    ParallelBranch(
                        "second-branch",
                        StepRef("second"),
                        "parallel.second",
                    ),
                    ParallelBranch("fail-branch", StepRef("fail"), "parallel.fail"),
                ),
                failure_policy="compensate",
            ),
            compensations=(
                CompensationBinding(
                    "undo-first",
                    "first",
                    "undo_first",
                    "research.undo.first@1",
                    "research.undo.first.activity@1",
                ),
                CompensationBinding(
                    "undo-second",
                    "second",
                    "undo_second",
                    "research.undo.second@1",
                    "research.undo.second.activity@1",
                ),
            ),
        )
    run_spec = HarnessRunSpec(
        run_id=run_id,
        graph=_graph_definition(graph, activities),
        metadata={
            "tenant_scope_ref": checksum_for({"tenant_id": "tenant-compensation"}),
            "identity_scope_ref": IDENTITY_SCOPE_REF,
            "subject_scope_ref": SUBJECT_SCOPE_REF,
        },
        budget=HarnessBudget(
            max_turns=80,
            max_replans=0,
            max_retries_per_step=0,
            max_worker_calls=5,
        ),
    )
    control_plane = HarnessControlPlane(
        event_port=event_port,
        side_effect_registry=side_effect_registry,
        side_effect_store=store,
        runtime_binding_authority=authority,
        graph_preflight=HarnessGraphPreflight(
            policy=HarnessGraphPreflightPolicy(
                max_node_activations=30,
                max_active_nodes=8,
                max_parallelism=1,
                max_compensations=max_compensations,
            )
        ),
    )
    _install_local_physical_dispatcher(control_plane)
    return _MultiEffectRuntimeFixture(
        control_plane=control_plane,
        run_spec=run_spec,
        event_port=event_port,
        first_handler=first_handler,
        second_handler=second_handler,
        call_order=call_order,
    )


def _install_local_physical_dispatcher(control_plane: HarnessControlPlane) -> None:
    executor = HarnessGraphPhysicalActivityExecutor(
        binding_authority=control_plane.runtime_binding_authority,
        input_resolver=control_plane,
        node_output_resource=InMemoryHarnessNodeOutputResource(),
        result_committer=None,
        supervisor=AttemptSupervisor(),
    )
    control_plane.install_graph_activity_dispatcher(
        HarnessGraphPhysicalActivityDispatcher(
            executor=executor,
            graph_resolver=control_plane.graph_for_activity,
            input_resolver=control_plane,
            accept=control_plane.accept_graph_activity_for_execution,
            record_call_marker=control_plane.record_graph_activity_call_marker,
            record_result=control_plane.record_graph_activity_result_event,
            apply_result=control_plane.commit_physical_graph_result,
        )
    )


def _terminal_compensation_run_spec(run_id: str) -> HarnessRunSpec:
    activities = (
            HarnessStepSpec(
                "publish",
                "function",
                output_key="candidate",
                side_effect_handler="research.prepare@1",
                metadata={
                    "step_version": "1",
                    "worker_id": "test.publish",
                    "worker_version": "1",
                },
            ),
            HarnessStepSpec(
                "undo",
                "function",
                metadata={
                    "step_version": "1",
                    "worker_id": "test.undo",
                    "worker_version": "1",
                },
            ),
        )
    graph = HarnessGraphSpec(
            graph_id="terminal-compensation-entry-graph",
            root=StepRef("publish"),
            compensations=(
                CompensationBinding(
                    "undo-node",
                    "publish",
                    "undo",
                    "research.undo@1",
                    "research.undo.activity@1",
                ),
                CompensationBinding(
                    "undo-terminal",
                    "publish",
                    "undo",
                    "research.undo@1",
                    "research.undo.activity@1",
                    scope="terminal_run",
                ),
            ),
        )
    terminal_policy = HarnessTerminalSideEffectPolicy(
        policy_id="terminal-publication",
        version="1",
        handler="research.prepare@1",
        kind="artifact",
        requires_approval=False,
        retry_limit=1,
        not_required_evidence_ref=checksum_for(
            {"approval": "not-required", "policy": "terminal-publication@1"}
        ),
    )
    return HarnessRunSpec(
        run_id=run_id,
        graph=_graph_definition(graph, activities, terminal_policy=terminal_policy),
        metadata={
            "tenant_scope_ref": checksum_for({"tenant_id": "tenant-compensation"}),
            "identity_scope_ref": IDENTITY_SCOPE_REF,
            "subject_scope_ref": SUBJECT_SCOPE_REF,
        },
        budget=HarnessBudget(
            max_turns=20,
            max_replans=0,
            max_retries_per_step=0,
            max_worker_calls=1,
        ),
    )


def _run_spec(run_id: str) -> HarnessRunSpec:
    activities = (
            HarnessStepSpec(
                "publish",
                "function",
                output_key="candidate",
                side_effect_handler="research.prepare@1",
                metadata={
                    "step_version": "1",
                    "worker_id": "test.publish",
                    "worker_version": "1",
                },
            ),
            HarnessStepSpec(
                "undo",
                "function",
                metadata={
                    "step_version": "1",
                    "worker_id": "test.undo",
                    "worker_version": "1",
                },
            ),
        )
    graph = HarnessGraphSpec(
            graph_id="compensation-entry-durability-graph",
            root=StepRef("publish"),
            compensations=(
                CompensationBinding(
                    binding_id="undo-publish",
                    for_node_id="publish",
                    compensation_step_id="undo",
                    handler_ref="research.undo@1",
                    activity_contract_ref="research.undo.activity@1",
                ),
            ),
        )
    return HarnessRunSpec(
        run_id=run_id,
        graph=_graph_definition(graph, activities),
        metadata={
            "tenant_scope_ref": checksum_for({"tenant_id": "tenant-compensation"}),
            "identity_scope_ref": IDENTITY_SCOPE_REF,
            "subject_scope_ref": SUBJECT_SCOPE_REF,
        },
        budget=HarnessBudget(
            max_turns=10,
            max_replans=0,
            max_retries_per_step=0,
            max_worker_calls=2,
        ),
    )


def _graph_definition(
    graph: HarnessGraphSpec,
    activities: tuple[HarnessStepSpec, ...],
    *,
    terminal_policy: HarnessTerminalSideEffectPolicy | None = None,
) -> HarnessGraphDefinition:
    return HarnessGraphDefinition(
        graph_id=graph.graph_id,
        graph_version="1",
        root=graph,
        activities=activities,
        leaf_activity_bindings=tuple(
            HarnessGraphLeafBinding(
                activity_id=step.step_id,
                leaf_activity_kind=HarnessLeafActivityKind.FUNCTION,
                worker_ref=HarnessContractReference(
                    HarnessContractKind.WORKER,
                    str(step.metadata.get("worker_id", step.step_id)),
                    str(step.metadata.get("worker_version", "1")),
                ),
                activity_ref=HarnessContractReference(
                    HarnessContractKind.ACTIVITY,
                    (
                        f"research.{step.step_id.replace('_', '.')}.activity"
                        if step.step_id.startswith("undo")
                        else "newsroom.harness-worker-activity"
                    ),
                    "1" if step.step_id.startswith("undo") else "v1",
                ),
            )
            for step in activities
        ),
        task_plan_stage_bindings=(),
        committed_output_bindings=(),
        repair_bindings=(),
        terminal_side_effect_policy=terminal_policy or HarnessTerminalSideEffectPolicy(
            policy_id="research.prepare.terminal",
            version="1",
            handler="research.prepare@1",
            kind="artifact",
            requires_approval=False,
            retry_limit=1,
            not_required_evidence_ref=checksum_for("compensation-terminal-not-required"),
        ),
    )


def _origin_node(state: HarnessGraphState):
    return next(
        node for node in state.node_instances if node.identity.node_id == "publish"
    )


def _only_compensation_entry(state: HarnessGraphState):
    assert len(state.compensation_stack) == 1
    return state.compensation_stack[0]


def _step_decision(
    state: HarnessGraphState,
    graph: NormalizedHarnessGraph,
    node_instance_id: str,
    decision_type: HarnessGraphDecisionType,
) -> HarnessGraphDecision:
    node = next(
        item for item in state.node_instances if item.instance_id == node_instance_id
    )
    definition = next(
        item for item in graph.nodes if item.node_id == node.identity.node_id
    )
    assert isinstance(definition, HarnessExecutableNode)
    bindings = {
        "step": definition.step_ref.exact_ref,
        "worker": definition.worker_ref.exact_ref,
        "activity": definition.activity_ref.exact_ref,
    }
    if definition.side_effect_ref is not None:
        bindings["side_effect"] = definition.side_effect_ref.exact_ref
    return HarnessGraphDecision(
        decision_type,
        state.run_id,
        state.graph_ref,
        state.projection_checksum,
        canonical_checksum({"observation": state.projection_checksum}),
        "test_complete_effectful_node",
        node_id=definition.node_id,
        node_instance_id=node.instance_id,
        step_ref=definition.step_ref,
        attempt=node.attempt,
        binding_versions=bindings,
    )
