from __future__ import annotations

from datetime import UTC, datetime

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_runtime import HarnessGraphActivity
from framework.harness.graph.reference import HarnessGraphReference
from framework.harness.control_plane.node_output import (
    HarnessNodeOutputCandidate,
    HarnessNodeOutputResourceIdentity,
    InMemoryHarnessNodeOutputResource,
)
from framework.harness.runtime.node_output import (
    HarnessAdmittedGraphActivityOutputAdapter,
    HarnessCommittedNodeOutputInputResolver,
)
from framework.harness.graph.activity import HarnessStepSpec, HarnessWorkerType
from framework.harness.graph.canonical import canonical_checksum
from framework.harness.graph.definition import (
    HarnessGraphCommittedNodeOutputBinding,
    HarnessGraphDefinition,
    HarnessGraphLeafBinding,
)
from framework.harness.graph.dsl import HarnessGraphSpec, Sequence, StepRef
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
)
from framework.harness.side_effects.models import HarnessTerminalSideEffectPolicy
from framework.harness.graph.versioning import (
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
)


from framework.shared.attempts import (
    AdmissionResult,
    AttemptContext,
    AttemptLifecycleEmissionError,
    AttemptOutcome,
    AttemptState,
    AttemptSupervisor,
    DeadlineAdmissionPolicy,
    current_attempt_context,
)


_NOW = datetime(2026, 8, 15, 8, 0, tzinfo=UTC)


def test_adapter_acquires_only_after_admission_and_commits_after_terminal_fact() -> None:
    resource = InMemoryHarnessNodeOutputResource()
    activity = _activity(fencing_generation=73)
    adapter = HarnessAdmittedGraphActivityOutputAdapter(
        resource=resource,
        supervisor=AttemptSupervisor(),
        clock=lambda: _NOW,
    )

    result = adapter.run(
        lambda: _candidate("success"),
        activity=activity,
        timeout_seconds=None,
        attempt_id="physical-attempt-1",
    )

    assert result.outcome.state is AttemptState.SUCCEEDED
    assert result.admission is not None
    assert result.admission.owner_attempt_id == "physical-attempt-1"
    assert result.admission.local_attempt_no == 1
    assert result.lease is not None
    assert result.lease.generation == 1
    assert result.lease.generation != activity.fencing_generation
    assert result.commit is not None
    assert result.commit.owner_attempt_id == "physical-attempt-1"
    assert (
        resource.committed_output(HarnessNodeOutputResourceIdentity.for_activity(activity))
        == result.commit
    )


def test_deadline_rejection_never_creates_admission_or_lease() -> None:
    called = False
    resource = InMemoryHarnessNodeOutputResource()
    activity = _activity()
    attempt_clock = lambda: 10.0
    parent = AttemptContext.create(
        attempt_id="parent-attempt",
        idempotency_key="graph-run:parent",
        operation_id="graph-run:parent",
        operation_kind="graph_run",
        deadline=10.5,
        clock=attempt_clock,
    )
    adapter = HarnessAdmittedGraphActivityOutputAdapter(
        resource=resource,
        supervisor=AttemptSupervisor(clock=attempt_clock),
        clock=lambda: _NOW,
    )

    def invoke() -> HarnessNodeOutputCandidate:
        nonlocal called
        called = True
        return _candidate("must-not-run")

    result = adapter.run(
        invoke,
        activity=activity,
        timeout_seconds=1.0,
        admission_policy=DeadlineAdmissionPolicy(
            timeout_seconds=1.0,
            min_start_window_seconds=1.0,
        ),
        parent_context=parent,
    )

    identity = HarnessNodeOutputResourceIdentity.for_activity(activity)
    assert result.outcome.state is AttemptState.REJECTED
    assert called is False
    assert result.admission is None
    assert result.lease is None
    assert result.commit is None
    assert resource.current_lease(identity) is None
    assert resource.committed_output(identity) is None


def test_indeterminate_descendant_revokes_lease_and_cannot_publish_output() -> None:
    resource = InMemoryHarnessNodeOutputResource()
    activity = _activity()
    adapter = HarnessAdmittedGraphActivityOutputAdapter(
        resource=resource,
        supervisor=AttemptSupervisor(),
        clock=lambda: _NOW,
    )

    def invoke() -> HarnessNodeOutputCandidate:
        context = current_attempt_context()
        assert context is not None
        context.mark_descendant_indeterminate()
        return _candidate("indeterminate")

    result = adapter.run(
        invoke,
        activity=activity,
        timeout_seconds=None,
        attempt_id="physical-attempt-1",
    )

    identity = HarnessNodeOutputResourceIdentity.for_activity(activity)
    assert result.outcome.state is AttemptState.INDETERMINATE
    assert result.outcome.indeterminate is True
    assert result.admission is not None
    assert result.lease is not None
    assert result.commit is None
    assert resource.current_lease(identity) is None
    assert resource.committed_output(identity) is None


def test_terminal_event_failure_rolls_back_staged_output_and_revokes_lease() -> None:
    resource = InMemoryHarnessNodeOutputResource()
    activity = _activity()
    adapter = HarnessAdmittedGraphActivityOutputAdapter(
        resource=resource,
        supervisor=AttemptSupervisor(),
        clock=lambda: _NOW,
    )

    with pytest.raises(AttemptLifecycleEmissionError):
        adapter.run(
            lambda: _candidate("rolled-back"),
            activity=activity,
            timeout_seconds=None,
            attempt_id="physical-attempt-1",
            event_sink=_FailingTerminalSink(),
        )

    identity = HarnessNodeOutputResourceIdentity.for_activity(activity)
    assert resource.current_lease(identity) is None
    assert resource.committed_output(identity) is None


def test_committed_output_resolver_binds_declared_resource_commit_to_payload() -> None:
    resource = InMemoryHarnessNodeOutputResource()
    activity = _activity()
    payload = {"reader_payload": "repaired"}
    output_adapter = HarnessAdmittedGraphActivityOutputAdapter(
        resource=resource,
        supervisor=AttemptSupervisor(),
        clock=lambda: _NOW,
    )
    output_adapter.run(
        lambda: _payload_candidate(payload, "first"),
        activity=activity,
        timeout_seconds=None,
        attempt_id="physical-attempt-1",
    )
    definition = _definition()
    resolver = HarnessCommittedNodeOutputInputResolver(resource=resource)

    receipt = resolver.resolve(
        definition=definition,
        binding_id="analyze-report-commit",
        producer_activity=activity,
        payload=payload,
    )
    restored = resolver.verify(
        receipt.to_dict(),
        definition=definition,
        binding_id="analyze-report-commit",
        payload=payload,
    )

    assert restored == receipt
    assert receipt.graph_definition_checksum == definition.definition_checksum
    assert receipt.output_ref == canonical_checksum(payload)
    assert receipt.resource.node_instance_id == activity.node_instance_id
    assert receipt.commit.candidate.output_refs["report"] == receipt.output_ref


def test_committed_output_resolver_fails_closed_without_commit_or_exact_payload() -> None:
    resource = InMemoryHarnessNodeOutputResource()
    activity = _activity()
    definition = _definition()
    resolver = HarnessCommittedNodeOutputInputResolver(resource=resource)

    with pytest.raises(HarnessValidationError) as missing:
        resolver.resolve(
            definition=definition,
            binding_id="analyze-report-commit",
            producer_activity=activity,
            payload={"reader_payload": "repaired"},
        )

    assert missing.value.code == "graph_committed_node_output_missing"

    with pytest.raises(HarnessValidationError) as wrong_node:
        resolver.resolve(
            definition=definition,
            binding_id="analyze-report-commit",
            producer_activity=_activity(node_id="other-node"),
            payload={"reader_payload": "repaired"},
        )

    assert wrong_node.value.code == "graph_committed_node_output_producer_mismatch"

    payload = {"reader_payload": "repaired"}
    HarnessAdmittedGraphActivityOutputAdapter(
        resource=resource,
        supervisor=AttemptSupervisor(),
        clock=lambda: _NOW,
    ).run(
        lambda: _payload_candidate(payload, "first"),
        activity=activity,
        timeout_seconds=None,
        attempt_id="physical-attempt-1",
    )
    with pytest.raises(HarnessValidationError) as mismatched:
        resolver.resolve(
            definition=definition,
            binding_id="analyze-report-commit",
            producer_activity=activity,
            payload={"reader_payload": "forged"},
        )

    assert mismatched.value.code == "graph_committed_node_output_payload_mismatch"


def test_committed_output_resolver_rejects_receipt_superseded_by_authorized_retry() -> None:
    resource = InMemoryHarnessNodeOutputResource()
    definition = _definition()
    resolver = HarnessCommittedNodeOutputInputResolver(resource=resource)
    first_activity = _activity(fencing_generation=1)
    first_payload = {"reader_payload": "first"}
    adapter = HarnessAdmittedGraphActivityOutputAdapter(
        resource=resource,
        supervisor=AttemptSupervisor(),
        clock=lambda: _NOW,
    )
    adapter.run(
        lambda: _payload_candidate(first_payload, "first"),
        activity=first_activity,
        timeout_seconds=None,
        attempt_id="physical-attempt-1",
    )
    first_receipt = resolver.resolve(
        definition=definition,
        binding_id="analyze-report-commit",
        producer_activity=first_activity,
        payload=first_payload,
    )
    second_activity = _activity(fencing_generation=2)
    second_payload = {"reader_payload": "second"}
    late_result = adapter.run(
        lambda: _payload_candidate(second_payload, "second"),
        activity=second_activity,
        timeout_seconds=None,
        attempt_id="physical-attempt-2",
    )

    with pytest.raises(HarnessValidationError) as superseded:
        resolver.verify(
            first_receipt,
            definition=definition,
            binding_id="analyze-report-commit",
            payload=first_payload,
        )
    current_receipt = resolver.resolve(
        definition=definition,
        binding_id="analyze-report-commit",
        producer_activity=second_activity,
        payload=second_payload,
    )

    assert superseded.value.code == "graph_committed_node_output_commit_mismatch"
    assert late_result.outcome.state is AttemptState.SUCCEEDED
    assert late_result.commit is not None
    assert current_receipt.commit == late_result.commit
    assert (
        resource.committed_output(current_receipt.resource)
        == current_receipt.commit
    )


class _FailingTerminalSink:
    required = True

    def rejected(
        self,
        *,
        operation_id: str,
        operation_kind: str,
        idempotency_key: str,
        admission: AdmissionResult,
    ) -> None:
        raise AssertionError("this attempt must be admitted")

    def started(self, *, context: AttemptContext) -> None:
        assert context.attempt_id == "physical-attempt-1"

    def terminal(self, *, outcome: AttemptOutcome[object]) -> None:
        raise OSError("terminal event store unavailable")


def _activity(
    *,
    fencing_generation: int = 1,
    node_id: str = "analyze",
) -> HarnessGraphActivity:
    return HarnessGraphActivity(
        run_id="run-1",
        graph_ref=_graph_ref(),
        node_id=node_id,
        node_instance_id=f"hni-{node_id}-1",
        step_ref=_ref(HarnessContractKind.STEP, "research:analyze"),
        worker_ref=_ref(HarnessContractKind.WORKER, "research-worker"),
        activity_ref=_ref(HarnessContractKind.ACTIVITY, "research-activity"),
        attempt=1,
        input_ref=_sha("input"),
        causal_decision_checksum=_sha("decision"),
        causal_decision_sequence=1,
        fencing_generation=fencing_generation,
        tenant_scope_ref=_sha("tenant"),
        identity_scope_ref=_sha("identity"),
        subject_scope_ref=_sha("subject"),
    )


def _candidate(label: str) -> HarnessNodeOutputCandidate:
    return HarnessNodeOutputCandidate(
        output_refs={"report": _sha(f"report-{label}")},
        evidence_refs=(_sha(f"evidence-{label}"),),
    )


def _payload_candidate(
    payload: dict[str, str],
    label: str,
) -> HarnessNodeOutputCandidate:
    return HarnessNodeOutputCandidate(
        output_refs={"report": canonical_checksum(payload)},
        evidence_refs=(_sha(f"evidence-{label}"),),
    )


def _definition() -> HarnessGraphDefinition:
    activities = (
        HarnessStepSpec(
            step_id="analyze",
            worker_type=HarnessWorkerType.FUNCTION,
            output_key="report",
        ),
        HarnessStepSpec(
            step_id="publish",
            worker_type=HarnessWorkerType.FUNCTION,
            input_keys=("report",),
            output_key="published",
        ),
    )
    return HarnessGraphDefinition(
        graph_id="research",
        graph_version="2",
        root=HarnessGraphSpec(
            graph_id="research",
            root=Sequence((StepRef("analyze"), StepRef("publish"))),
            terminal_output_keys=("published",),
        ),
        activities=activities,
        leaf_activity_bindings=(
            HarnessGraphLeafBinding(
                activity_id="analyze",
                leaf_activity_kind="function",
                worker_ref=_ref(
                    HarnessContractKind.WORKER,
                    "research-worker",
                ),
                activity_ref=_ref(
                    HarnessContractKind.ACTIVITY,
                    "research-activity",
                ),
            ),
            HarnessGraphLeafBinding(
                activity_id="publish",
                leaf_activity_kind="function",
                worker_ref=_ref(
                    HarnessContractKind.WORKER,
                    "publish-worker",
                ),
                activity_ref=_ref(
                    HarnessContractKind.ACTIVITY,
                    "publish-activity",
                ),
            ),
        ),
        task_plan_stage_bindings=(),
        committed_output_bindings=(
            HarnessGraphCommittedNodeOutputBinding(
                binding_id="analyze-report-commit",
                producer_activity_id="analyze",
                producer_node_id="analyze",
                producer_output_key="report",
                consumer_activity_id="publish",
                consumer_node_id="publish",
                receipt_input_key="report_commit",
            ),
        ),
        repair_bindings=(),
        terminal_side_effect_policy=HarnessTerminalSideEffectPolicy(
            policy_id="test.noop",
            version="1",
            handler="test.noop@1",
            kind="noop",
            requires_approval=False,
            retry_limit=1,
            not_required_evidence_ref=_sha("not-required"),
        ),
    )


def _graph_ref() -> HarnessGraphReference:
    return HarnessGraphReference(
        graph_id="research",
        schema_version=GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
        compiler_version=HARNESS_GRAPH_ONLY_COMPILER_VERSION,
        condition_policy_version=HARNESS_CONDITION_POLICY_VERSION,
        checksum=_sha("graph"),
        graph_ref=_ref(HarnessContractKind.GRAPH, "research", version="2"),
    )


def _ref(
    kind: HarnessContractKind,
    contract_id: str,
    *,
    version: str = "1",
) -> HarnessContractReference:
    return HarnessContractReference(kind, contract_id, version)


def _sha(value: str) -> str:
    return canonical_checksum({"value": value})
