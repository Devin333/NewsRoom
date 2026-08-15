from __future__ import annotations

from datetime import UTC, datetime

import pytest

from framework.events.canonical import canonical_json_bytes, checksum_for
from framework.events.errors import EventReplayMismatchError
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_application import (
    HarnessGraphControlPlaneRuntime,
)
from framework.harness.control_plane.harness import (
    HarnessControlPlane,
    InMemoryHarnessEventPort,
)
from framework.harness.control_plane.state import HarnessRunSpec
from framework.harness.runtime import (
    ArtifactClass,
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
    RetentionClass,
)
from framework.harness.graph.dsl import HarnessGraphSpec, StepRef
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.graph.activity import HarnessStepSpec
from framework.harness.workers.result import HarnessWorkerResult, HarnessWorkerStatus


NOW = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)
SCHEMA_DIGEST = checksum_for("test-graph-result-schema@1")


class _InlineResultCommitter:
    def __init__(self, port: InMemoryHarnessEventPort) -> None:
        self._runtime = HarnessGraphResultRuntime(
            HarnessGraphControlPlaneRuntime(port)
        )
        self.calls: list[dict] = []

    def commit_result(
        self,
        *,
        activity,
        graph,
        run_spec_checksum,
        worker_result,
        occurred_at,
    ):
        self.calls.append(
            {
                "activity": activity,
                "graph": graph,
                "run_spec_checksum": run_spec_checksum,
                "worker_result": worker_result,
                "occurred_at": occurred_at,
            }
        )
        binding = self._runtime.binding_for_activity(
            activity_id=activity.activity_id,
            graph=graph,
            tenant_id="tenant-test",
            tenant_scope_ref=activity.tenant_scope_ref,
            attempt_id=(
                "materialized-"
                f"{checksum_for(activity.activity_id).removeprefix('sha256:')[:16]}"
            ),
            run_spec_checksum=run_spec_checksum,
        )
        return self._runtime.accept_materialized_result(
            _inline_envelope(binding, worker_result, occurred_at=occurred_at),
            expected_binding=binding,
            activity_id=activity.activity_id,
            graph=graph,
            run_spec_checksum=run_spec_checksum,
            occurred_at=occurred_at,
        )


class _FailOnceCommitter:
    def __init__(self, delegate: _InlineResultCommitter) -> None:
        self._delegate = delegate
        self.calls = 0

    def commit_result(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("materializer unavailable")
        return self._delegate.commit_result(**kwargs)


class _ConflictingCommitter:
    def commit_result(self, *, activity, **_kwargs):
        raise EventReplayMismatchError(
            sequence=activity.causal_decision_sequence,
            reason="materialized attempt conflicts",
        )


class _UncommittedStateCommitter:
    def __init__(self, port: InMemoryHarnessEventPort) -> None:
        self._port = port

    def commit_result(self, *, activity, **_kwargs):
        state = self._port.recover_graph(activity.run_id).state
        assert state is not None
        return state


def test_configured_committer_is_the_only_graph_success_path() -> None:
    port = InMemoryHarnessEventPort()
    committer = _InlineResultCommitter(port)
    calls: list[dict] = []

    def worker(task: dict) -> HarnessWorkerResult:
        calls.append(task)
        return HarnessWorkerResult("succeeded", output={"answer": "ready"})

    run_spec = _run_spec("run-materialized-success")
    result = HarnessControlPlane(
        event_port=port,
        worker_registry={"analyze": worker},
        graph_result_committer=committer,
    ).run(run_spec)

    assert result.succeeded is True
    assert len(calls) == 1
    assert len(committer.calls) == 1
    recorded = port.recover_graph(run_spec.run_id).activity_result_commits
    assert len(recorded) == 1
    assert recorded[0].result.result_lineage is not None
    assert recorded[0].result.payload_ref == (
        recorded[0].result.result_lineage.envelope_checksum
    )


def test_committer_failure_preserves_worker_result_for_worker_free_restart() -> None:
    port = InMemoryHarnessEventPort()
    delegate = _InlineResultCommitter(port)
    committer = _FailOnceCommitter(delegate)
    worker_calls = 0

    def worker(_task: dict) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return HarnessWorkerResult("succeeded", output={"answer": "durable"})

    run_spec = _run_spec("run-materialized-restart")
    with pytest.raises(RuntimeError, match="materializer unavailable"):
        HarnessControlPlane(
            event_port=port,
            worker_registry={"analyze": worker},
            graph_result_committer=committer,
        ).run(run_spec)

    interrupted = port.recover_graph(run_spec.run_id)
    assert interrupted.activity_result_commits == ()
    assert len(interrupted.state.active_activities) == 1
    assert worker_calls == 1

    recovered = HarnessControlPlane(
        event_port=port,
        worker_registry={"analyze": worker},
        graph_result_committer=committer,
    ).recover_and_run(run_spec)

    assert recovered.succeeded is True
    assert worker_calls == 1
    assert committer.calls == 2
    assert len(delegate.calls) == 1
    cause = port.recover_graph(run_spec.run_id).activity_result_commits[0]
    assert cause.result.result_lineage is not None


def test_committer_conflict_never_falls_back_to_payload_only_success() -> None:
    port = InMemoryHarnessEventPort()
    worker_calls = 0

    def worker(_task: dict) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return HarnessWorkerResult("succeeded", output={"answer": "conflict"})

    run_spec = _run_spec("run-materialized-conflict")
    with pytest.raises(EventReplayMismatchError, match="materialized attempt conflicts"):
        HarnessControlPlane(
            event_port=port,
            worker_registry={"analyze": worker},
            graph_result_committer=_ConflictingCommitter(),
        ).run(run_spec)

    recovery = port.recover_graph(run_spec.run_id)
    assert recovery.activity_result_commits == ()
    assert len(recovery.state.active_activities) == 1
    assert worker_calls == 1


def test_committer_must_return_a_durable_lineage_projection() -> None:
    port = InMemoryHarnessEventPort()
    run_spec = _run_spec("run-materialized-incomplete")

    with pytest.raises(HarnessValidationError) as captured:
        HarnessControlPlane(
            event_port=port,
            worker_registry={
                "analyze": lambda _task: HarnessWorkerResult("succeeded")
            },
            graph_result_committer=_UncommittedStateCommitter(port),
        ).run(run_spec)

    assert captured.value.code == "graph_result_committer_lineage_missing"
    assert port.recover_graph(run_spec.run_id).activity_result_commits == ()


def test_legacy_path_remains_readable_when_committer_is_not_configured() -> None:
    port = InMemoryHarnessEventPort()
    run_spec = _run_spec("run-legacy-result-path")

    result = HarnessControlPlane(
        event_port=port,
        worker_registry={
            "analyze": lambda _task: HarnessWorkerResult("succeeded")
        },
    ).run(run_spec)

    assert result.succeeded is True
    cause = port.recover_graph(run_spec.run_id).activity_result_commits[0]
    assert cause.result.result_lineage is None


def _run_spec(run_id: str) -> HarnessRunSpec:
    step = HarnessStepSpec(
        "analyze",
        "script",
        metadata={"step_version": "1", "worker_version": "1"},
    )
    return HarnessRunSpec(
        run_id=run_id,
        workflow=HarnessWorkflowSpec(
            workflow_id=f"workflow-{run_id}",
            workflow_version="2",
            steps=(step,),
            entry_step_id="analyze",
            graph=HarnessGraphSpec(
                graph_id=f"graph-{run_id}",
                root=StepRef("analyze"),
            ),
        ),
        metadata={
            "tenant_scope_ref": checksum_for(f"tenant-{run_id}"),
            "identity_scope_ref": checksum_for(f"identity-{run_id}"),
            "subject_scope_ref": checksum_for(f"subject-{run_id}"),
        },
        created_at=NOW,
    )


def _inline_envelope(binding, worker_result, *, occurred_at) -> NodeResultEnvelope:
    candidate = worker_result.to_dict()
    candidate_bytes = len(canonical_json_bytes(candidate))
    summary = BoundedSummary.from_text(
        f"{worker_result.status.value} worker result"
    )
    projection = {"status": worker_result.status.value}
    status = (
        NodeResultStatus.SUCCEEDED
        if worker_result.status is HarnessWorkerStatus.SUCCEEDED
        else NodeResultStatus.FAILED
        if worker_result.status is HarnessWorkerStatus.FAILED
        else NodeResultStatus.HALTED
    )
    return NodeResultEnvelope(
        binding=binding,
        status=status,
        output_schema_ref="test-graph-result@1",
        output_schema_digest=SCHEMA_DIGEST,
        candidate_checksum=checksum_for(candidate),
        summary=summary,
        inline_projection=projection,
        materialized_refs=(),
        cache_refs=(),
        provenance=ResultProvenance(
            producer_ref="test-worker@1",
            producer_revision="test-worker-revision@1",
        ),
        persistence_decision=PersistenceDecision(
            mode=PersistenceMode.INLINE,
            reason=PersistenceReason.BELOW_INLINE_THRESHOLD,
            artifact_class=ArtifactClass.CONTROL,
            retention_class=RetentionClass.RUN,
            estimated_bytes=candidate_bytes,
            reserved_bytes=0,
            context_policy=ContextPolicy.SUMMARY_ONLY,
            required=False,
            policy_version="graph-artifact-policy@1",
        ),
        metrics=ResultMetrics(
            candidate_bytes=candidate_bytes,
            candidate_tokens=(candidate_bytes + 3) // 4,
            summary_bytes=summary.byte_size,
            inline_bytes=len(canonical_json_bytes(projection)),
        ),
        created_at=occurred_at,
    )
