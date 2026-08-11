from __future__ import annotations

from typing import Any

import pytest

from framework.harness import (
    ArtifactWriteRequest,
    ContextCompactionActionType,
    ContextCompactionActionExecutor,
    ContextCompactionPlanner,
    ContextCompactionPlanningRequest,
    ContextCompactionPlanningStatus,
    ContextCompactionPolicy,
    ContextGroupKind,
    ContextGroupMaterializer,
    ContextMaterializationRequest,
    ContextPhysicalAdmissionEvidence,
    ContextSummaryCandidate,
    ContextSummaryClaim,
    ContextSummaryWorkerResult,
    ContextSummaryRequest,
    ContextSummaryVerificationResult,
    FakeArtifactPort,
    HarnessValidationError,
)


class _ResolvableArtifactPort(FakeArtifactPort):
    def resolve_artifact(self, ref: str):
        base = ref.split("#sha256=", 1)[0]
        return self.refs[base]


class _SummaryWorker:
    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[ContextSummaryRequest] = []

    def generate(self, request: ContextSummaryRequest) -> object:
        self.requests.append(request)
        return self.result


def _policy(*, max_summary_calls: int = 1) -> ContextCompactionPolicy:
    return ContextCompactionPolicy(
        policy_revision="policy-summary-v1",
        action_order=(ContextCompactionActionType.SUMMARIZE_GROUPS,),
        max_actions=2,
        max_summary_calls=max_summary_calls,
        max_replans=1,
        max_llm_calls=1,
        max_input_tokens=30,
        max_cost_usd=1.0,
        max_turns=2,
        keep_recent_complete_turns=1,
    )


def _snapshot(policy: ContextCompactionPolicy):
    return ContextGroupMaterializer().materialize(
        ContextMaterializationRequest(
            run_id="run-summary-1",
            step_id="step-1",
            task_binding_ref="task://summary",
            policy_revision=policy.policy_revision,
            physical_profile_revision="profile-summary-v1",
            messages=(
                {"role": "user", "content_ref": "message://u-1"},
                {"role": "assistant", "content_ref": "message://a-1"},
                {"role": "user", "content_ref": "message://u-2"},
                {"role": "assistant", "content_ref": "message://a-2"},
            ),
        )
    )


def _admission(snapshot):
    counts = {group.group_id: 10 for group in snapshot.groups}
    return ContextPhysicalAdmissionEvidence(
        source_snapshot_id=snapshot.snapshot_id,
        source_snapshot_checksum=snapshot.checksum,
        prepared_fingerprint="sha256:prepared-summary-v1",
        physical_profile_revision="profile-summary-v1",
        tokenizer_revision="tokenizer-summary-v1",
        normalizer_revision="normalizer-summary-v1",
        materialization_revision="materialization-summary-v1",
        admission_status="input_limit_exceeded",
        admitted=False,
        input_tokens=10 + sum(counts.values()),
        max_input_tokens=30,
        fixed_input_tokens=10,
        group_input_tokens=counts,
    )


def _plan_and_target(snapshot, policy):
    admission = _admission(snapshot)
    result = ContextCompactionPlanner().plan(
        ContextCompactionPlanningRequest(
            source_snapshot=snapshot,
            initial_admission=admission,
            policy=policy,
        )
    )
    assert result.status is ContextCompactionPlanningStatus.PLAN_READY
    assert result.plan is not None
    assert result.plan.actions[0].action_type is ContextCompactionActionType.SUMMARIZE_GROUPS
    return result.plan, admission


def _candidate(snapshot, plan, artifact_ref: str, *, source_refs=None):
    target_ids = plan.actions[0].target_group_ids
    groups = {group.group_id: group for group in snapshot.groups}
    refs = tuple(
        source_ref
        for group_id in target_ids
        for source_ref in groups[group_id].source_refs
    )
    claims = tuple(
        ContextSummaryClaim(supporting_refs=(groups[group_id].source_refs[0],))
        for group_id in target_ids
    )
    return ContextSummaryCandidate(
        summary_artifact_ref=artifact_ref,
        covered_group_ids=target_ids,
        source_refs=tuple(source_refs or refs),
        claims=claims,
        omitted_topics=("older detail",),
        unresolved_questions=(),
        tool_outcome_refs=(),
        loss_risk="low",
        worker_id="summary-worker",
        model_id="summary-model",
        worker_revision="worker-v1",
        model_revision="model-v1",
    )


def _summary_artifact(port: _ResolvableArtifactPort) -> str:
    ref = port.write_artifact(
        ArtifactWriteRequest(
            artifact_type="context-summary",
            payload={"summary_body": "stored outside candidate and durable records"},
        )
    )
    return f"{ref.ref}#sha256={ref.checksum.removeprefix('sha256:')}"


def test_valid_summary_candidate_replaces_only_target_groups_after_gates() -> None:
    policy = _policy()
    snapshot = _snapshot(policy)
    plan, admission = _plan_and_target(snapshot, policy)
    artifact_port = _ResolvableArtifactPort()
    candidate = _candidate(snapshot, plan, _summary_artifact(artifact_port))
    worker = _SummaryWorker(
        ContextSummaryWorkerResult(candidate=candidate, input_tokens=5, cost_usd=0.1)
    )
    executor = ContextCompactionActionExecutor(
        artifact_port,
        summary_worker=worker,
        summary_artifact_port=artifact_port,
    )

    result = executor.execute(
        plan,
        source_snapshot=snapshot,
        initial_admission=admission,
        policy=policy,
    )

    assert result.result_snapshot is not None
    assert result.status.value == "applied"
    assert result.result_snapshot.groups[0].group_kind is ContextGroupKind.MEMORY_REFERENCE
    assert result.summary_refs == (candidate.summary_artifact_ref,)
    assert worker.requests[0].target_group_ids == plan.actions[0].target_group_ids
    assert result.usage.summary_calls == 1
    assert result.usage.llm_calls == 1


def test_invented_source_ref_rejects_candidate_without_changing_source() -> None:
    policy = _policy()
    snapshot = _snapshot(policy)
    plan, admission = _plan_and_target(snapshot, policy)
    artifact_port = _ResolvableArtifactPort()
    candidate = _candidate(
        snapshot,
        plan,
        _summary_artifact(artifact_port),
        source_refs=("source://invented",),
    )
    worker = _SummaryWorker(
        ContextSummaryWorkerResult(candidate=candidate, input_tokens=5, cost_usd=0.1)
    )
    result = ContextCompactionActionExecutor(
        artifact_port,
        summary_worker=worker,
        summary_artifact_port=artifact_port,
    ).execute(
        plan,
        source_snapshot=snapshot,
        initial_admission=admission,
        policy=policy,
    )

    assert result.result_snapshot is None
    assert result.outcome.value == "summary_rejected"
    assert result.source_snapshot_id == snapshot.snapshot_id
    assert len(worker.requests) == 1
    assert tuple(group.group_id for group in snapshot.groups) == tuple(
        group.group_id for group in snapshot.groups
    )


def test_required_evidence_and_conflict_refs_must_be_supported() -> None:
    policy = ContextCompactionPolicy(
        policy_revision="policy-summary-evidence-v1",
        action_order=(ContextCompactionActionType.SUMMARIZE_GROUPS,),
        max_actions=2,
        max_summary_calls=1,
        max_replans=1,
        max_llm_calls=1,
        max_input_tokens=30,
        max_cost_usd=1.0,
        max_turns=2,
        keep_recent_complete_turns=0,
    )
    snapshot = ContextGroupMaterializer().materialize(
        ContextMaterializationRequest(
            run_id="run-summary-evidence",
            task_binding_ref="task://summary-evidence",
            policy_revision=policy.policy_revision,
            physical_profile_revision="profile-summary-v1",
            messages=(),
            evidence_items=(
                {
                    "evidence_id": "evidence-required",
                    "source_refs": ("source://paper",),
                    "span_refs": ("span://1",),
                    "lineage_refs": ("lineage://1",),
                    "required_span_refs": ("span://1",),
                    "selected_span_refs": ("span://1",),
                    "required_citation_refs": ("citation://required",),
                    "conflict_refs": ("conflict://1",),
                },
            ),
        )
    )
    groups = snapshot.groups
    port = _ResolvableArtifactPort()
    artifact_ref = _summary_artifact(port)
    candidate = ContextSummaryCandidate(
        summary_artifact_ref=artifact_ref,
        covered_group_ids=(groups[0].group_id,),
        source_refs=("source://paper",),
        claims=(ContextSummaryClaim(supporting_refs=("source://paper",)),),
        omitted_topics=(),
        unresolved_questions=(),
        tool_outcome_refs=(),
        loss_risk="low",
        worker_id="summary-worker",
        model_id="summary-model",
        worker_revision="worker-v1",
        model_revision="model-v1",
    )
    from framework.harness import ContextSummaryCandidateVerifier

    with pytest.raises(HarnessValidationError, match="required evidence"):
        ContextSummaryCandidateVerifier().verify(
            candidate,
            source_snapshot=snapshot,
            target_group_ids=(groups[0].group_id,),
            policy=policy,
            artifact_port=port,
        )


def test_candidate_authority_fields_and_free_text_worker_output_are_rejected() -> None:
    policy = _policy()
    snapshot = _snapshot(policy)
    plan, admission = _plan_and_target(snapshot, policy)
    port = _ResolvableArtifactPort()
    candidate = _candidate(snapshot, plan, _summary_artifact(port))
    with pytest.raises(HarnessValidationError, match="unsupported fields"):
        from framework.harness import ContextSummaryCandidateVerifier

        ContextSummaryCandidateVerifier().verify(
            {**candidate.to_dict(), "verified": True},
            source_snapshot=snapshot,
            target_group_ids=plan.actions[0].target_group_ids,
            policy=policy,
            artifact_port=port,
        )
    worker = _SummaryWorker({"summary": "free text only"})
    result = ContextCompactionActionExecutor(
        port,
        summary_worker=worker,
        summary_artifact_port=port,
    ).execute(
        plan,
        source_snapshot=snapshot,
        initial_admission=admission,
        policy=policy,
    )

    assert result.outcome.value == "summary_rejected"
    assert result.result_snapshot is None
    assert len(worker.requests) == 1


def test_zero_summary_budget_is_rejected_before_worker_call() -> None:
    policy = _policy(max_summary_calls=0)
    snapshot = _snapshot(policy)
    admission = _admission(snapshot)
    result = ContextCompactionPlanner().plan(
        ContextCompactionPlanningRequest(
            source_snapshot=snapshot,
            initial_admission=admission,
            policy=policy,
        )
    )

    assert result.status is ContextCompactionPlanningStatus.NO_ALLOWED_COMPACTION
