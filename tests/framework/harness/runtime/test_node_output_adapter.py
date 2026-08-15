from __future__ import annotations

from datetime import UTC, datetime

import pytest

from framework.harness.control_plane.graph_runtime import HarnessGraphActivity
from framework.harness.control_plane.graph_state import HarnessGraphReference
from framework.harness.control_plane.node_output import (
    HarnessNodeOutputCandidate,
    HarnessNodeOutputResourceIdentity,
    InMemoryHarnessNodeOutputResource,
)
from framework.harness.runtime.node_output import (
    HarnessAdmittedGraphActivityOutputAdapter,
)
from framework.harness.workflow.canonical import canonical_checksum
from framework.harness.workflow.graph import (
    HarnessContractKind,
    HarnessContractReference,
)
from framework.harness.workflow.versioning import (
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_COMPILER_VERSION,
    NORMALIZED_HARNESS_GRAPH_SCHEMA,
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


def _activity(*, fencing_generation: int = 1) -> HarnessGraphActivity:
    return HarnessGraphActivity(
        run_id="run-1",
        graph_ref=_graph_ref(),
        node_id="analyze",
        node_instance_id="hni-analyze-1",
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


def _graph_ref() -> HarnessGraphReference:
    return HarnessGraphReference(
        "graph",
        _ref(HarnessContractKind.WORKFLOW, "research", version="2"),
        NORMALIZED_HARNESS_GRAPH_SCHEMA,
        HARNESS_GRAPH_COMPILER_VERSION,
        HARNESS_CONDITION_POLICY_VERSION,
        _sha("graph"),
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
