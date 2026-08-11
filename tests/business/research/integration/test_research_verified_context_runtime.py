from __future__ import annotations

from dataclasses import dataclass

from framework.events.canonical import checksum_for
from framework.harness import (
    ArtifactWriteRequest,
    ContextCompactionActionExecutor,
    ContextCompactionActionType,
    ContextCompactionPlanner,
    ContextCompactionPlanningRequest,
    ContextCompactionPlanningStatus,
    ContextCompactionPolicy,
    ContextCompactionReplayReader,
    ContextCompactionRuntime,
    ContextCompactionRuntimeRequest,
    ContextCompactionRuntimeStatus,
    ContextGroupKind,
    ContextGroupMaterializer,
    ContextMaterializationRequest,
    ContextPhysicalAdmissionEvidence,
    ContextPhysicalMaterialization,
    ContextSemanticSnapshot,
    ContextSummaryCandidate,
    ContextSummaryClaim,
    ContextSummaryWorkerResult,
    ContextVerifiedArtifactStore,
    FakeArtifactPort,
    HarnessEventType,
    InMemoryHarnessEventPort,
)


class _ResolvableArtifactPort(FakeArtifactPort):
    def resolve_artifact(self, ref: str):
        return self.refs[ref.split("#sha256=", 1)[0]]


@dataclass
class _ResearchPhysicalContext:
    max_input_tokens: int

    def materialize(self, snapshot, *, deployment_id):
        group_tokens = {
            group.group_id: (
                2
                if group.group_kind is ContextGroupKind.MEMORY_REFERENCE
                else (
                    len(group.members) * 10
                    if group.group_kind is ContextGroupKind.EVIDENCE
                    else 10
                )
            )
            for group in snapshot.groups
        }
        return ContextPhysicalMaterialization(
            result_snapshot=snapshot,
            deployment_id=deployment_id,
            profile_revision="profile-research-runtime-v1",
            materialization_revision="materializer-research-runtime-v1",
            request={
                "task_binding_ref": snapshot.task_binding_ref,
                "ordered_group_ids": [group.group_id for group in snapshot.groups],
            },
            fixed_input_tokens=5,
            group_input_tokens=group_tokens,
        )

    def admit(self, materialization):
        input_tokens = materialization.fixed_input_tokens + sum(
            materialization.group_input_tokens.values()
        )
        admitted = input_tokens <= self.max_input_tokens
        return ContextPhysicalAdmissionEvidence(
            source_snapshot_id=materialization.result_snapshot.snapshot_id,
            source_snapshot_checksum=materialization.result_snapshot.checksum,
            prepared_fingerprint=checksum_for(materialization.request),
            physical_profile_revision=materialization.profile_revision,
            tokenizer_revision="tokenizer-research-runtime-v1",
            normalizer_revision="normalizer-research-runtime-v1",
            materialization_revision=materialization.materialization_revision,
            admission_status="admitted" if admitted else "input_limit_exceeded",
            admitted=admitted,
            input_tokens=input_tokens,
            max_input_tokens=self.max_input_tokens,
            fixed_input_tokens=materialization.fixed_input_tokens,
            group_input_tokens=materialization.group_input_tokens,
        )


def _runtime(physical, *, artifacts=None, events=None, executor=None):
    artifacts = artifacts or FakeArtifactPort()
    events = events or InMemoryHarnessEventPort()
    return (
        ContextCompactionRuntime(
            materializer=physical,
            admission_verifier=physical,
            artifact_port=artifacts,
            event_port=events,
            executor=executor or ContextCompactionActionExecutor(artifacts),
        ),
        artifacts,
        events,
    )


def test_research_evidence_first_compaction_is_verified_and_replayable() -> None:
    policy = ContextCompactionPolicy(
        policy_revision="policy-research-evidence-v1",
        action_order=(ContextCompactionActionType.SELECT_EVIDENCE_SPANS,),
        max_actions=1,
        max_summary_calls=0,
        max_replans=1,
        max_llm_calls=0,
        max_input_tokens=35,
        max_cost_usd=0.0,
        max_turns=2,
        keep_recent_complete_turns=0,
    )
    source = ContextGroupMaterializer().materialize(
        ContextMaterializationRequest(
            run_id="research-evidence-runtime",
            step_id="research-analysis",
            task_binding_ref="task://research/paper-analysis/evidence",
            policy_revision=policy.policy_revision,
            physical_profile_revision="profile-research-runtime-v1",
            messages=({"role": "system", "content_ref": "prompt://research"},),
            evidence_items=(
                {
                    "evidence_id": "evidence-paper-1",
                    "source_refs": ("source://paper",),
                    "span_refs": ("span://required", "span://support", "span://noise"),
                    "lineage_refs": ("lineage://paper-1",),
                    "required_span_refs": ("span://required",),
                    "selected_span_refs": ("span://required", "span://support"),
                    "required_citation_refs": ("citation://paper-1",),
                    "conflict_refs": ("conflict://paper-1",),
                },
            ),
        )
    )
    physical = _ResearchPhysicalContext(max_input_tokens=35)
    runtime, artifacts, events = _runtime(physical)

    result = runtime.run(
        ContextCompactionRuntimeRequest(
            source_snapshot=source,
            policy=policy,
            deployment_id="research-deployment",
        )
    )

    assert result.status is ContextCompactionRuntimeStatus.VERIFIED
    assert result.dispatch_authorized is True
    assert result.execution is not None
    assert result.execution.action_results[0].action.action_type is (
        ContextCompactionActionType.SELECT_EVIDENCE_SPANS
    )
    evidence = next(
        group for group in result.result_snapshot.groups
        if group.group_kind is ContextGroupKind.EVIDENCE
    )
    assert tuple(member.content_ref for member in evidence.members) == (
        "span://required",
        "span://support",
    )
    assert events.events[-1].event_type is HarnessEventType.CONTEXT_COMPACTION_VERIFIED

    report = ContextCompactionReplayReader(
        ContextVerifiedArtifactStore(artifacts)
    ).replay(result.durable_refs, activation_event=events.events[-1])
    assert report.verification_classification == "versioned_verified_evidence"
    assert report.result_snapshot_id == result.result_snapshot.snapshot_id
    assert report.side_effects_replayed is False


class _SummaryWorker:
    def __init__(self, result: ContextSummaryWorkerResult) -> None:
        self.result = result

    def generate(self, request):
        del request
        return self.result


def test_research_verified_summary_replacement_replays_without_worker_call() -> None:
    policy = ContextCompactionPolicy(
        policy_revision="policy-research-summary-v1",
        action_order=(ContextCompactionActionType.SUMMARIZE_GROUPS,),
        max_actions=1,
        max_summary_calls=1,
        max_replans=1,
        max_llm_calls=1,
        max_input_tokens=30,
        max_cost_usd=1.0,
        max_turns=2,
        keep_recent_complete_turns=1,
    )
    source = ContextGroupMaterializer().materialize(
        ContextMaterializationRequest(
            run_id="research-summary-runtime",
            step_id="research-analysis",
            task_binding_ref="task://research/paper-analysis/summary",
            policy_revision=policy.policy_revision,
            physical_profile_revision="profile-research-runtime-v1",
            messages=(
                {"role": "user", "content_ref": "message://u-1"},
                {"role": "assistant", "content_ref": "message://a-1"},
                {"role": "user", "content_ref": "message://u-2"},
                {"role": "assistant", "content_ref": "message://a-2"},
            ),
        )
    )
    physical = _ResearchPhysicalContext(max_input_tokens=30)
    initial = physical.admit(
        physical.materialize(source, deployment_id="research-deployment")
    )
    plan_result = ContextCompactionPlanner().plan(
        ContextCompactionPlanningRequest(
            source_snapshot=source,
            initial_admission=initial,
            policy=policy,
        )
    )
    assert plan_result.status is ContextCompactionPlanningStatus.PLAN_READY
    assert plan_result.plan is not None
    target_ids = plan_result.plan.actions[0].target_group_ids
    groups = {group.group_id: group for group in source.groups}

    artifacts = _ResolvableArtifactPort()
    summary = artifacts.write_artifact(
        ArtifactWriteRequest(
            artifact_type="context-summary-candidate",
            payload={"summary_body": "research summary candidate"},
        )
    )
    summary_ref = f"{summary.ref}#sha256={summary.checksum.removeprefix('sha256:')}"
    candidate = ContextSummaryCandidate(
        summary_artifact_ref=summary_ref,
        covered_group_ids=target_ids,
        source_refs=tuple(
            ref for group_id in target_ids for ref in groups[group_id].source_refs
        ),
        claims=tuple(
            ContextSummaryClaim(supporting_refs=(groups[group_id].source_refs[0],))
            for group_id in target_ids
        ),
        omitted_topics=("older research discussion",),
        unresolved_questions=(),
        tool_outcome_refs=(),
        loss_risk="low",
        worker_id="research-summary-worker",
        model_id="research-model",
        worker_revision="research-worker-v1",
        model_revision="research-model-v1",
    )
    worker = _SummaryWorker(
        ContextSummaryWorkerResult(candidate=candidate, input_tokens=5, cost_usd=0.1)
    )
    executor = ContextCompactionActionExecutor(
        artifacts,
        summary_worker=worker,
        summary_artifact_port=artifacts,
    )
    runtime, artifacts, events = _runtime(
        physical,
        artifacts=artifacts,
        executor=executor,
    )

    result = runtime.run(
        ContextCompactionRuntimeRequest(
            source_snapshot=source,
            policy=policy,
            deployment_id="research-deployment",
        )
    )

    assert result.status is ContextCompactionRuntimeStatus.VERIFIED
    assert result.dispatch_authorized is True
    assert result.result_snapshot is not None
    assert result.result_snapshot.groups[0].group_kind is ContextGroupKind.MEMORY_REFERENCE
    assert events.events[-1].event_type is HarnessEventType.CONTEXT_COMPACTION_VERIFIED
    report = ContextCompactionReplayReader(
        ContextVerifiedArtifactStore(artifacts)
    ).replay(result.durable_refs, activation_event=events.events[-1])
    assert report.verification_classification == "versioned_verified_evidence"
    assert report.result_snapshot_id == result.result_snapshot.snapshot_id
