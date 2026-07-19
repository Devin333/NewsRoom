from __future__ import annotations

from framework.harness import (
    ContextBudget,
    ContextCachePolicy,
    ContextCacheScope,
    ContextEnvelope,
    ContextSegment,
    ContextSegmentType,
    ContextSnapshot,
)
from framework.shared.json import stable_json_dumps


def test_context_envelope_is_serializable_with_segments_budget_and_refs() -> None:
    budget = ContextBudget.safe_default()
    segment = ContextSegment(
        segment_id="global-policy",
        segment_type=ContextSegmentType.GLOBAL_POLICY,
        content_ref="policy://harness/global",
        summary="Harness controls workflow routing and tool authorization.",
        token_estimate=64,
        provenance_refs=("policy://harness/global",),
        cache_scope=ContextCacheScope.STABLE_PREFIX,
    )
    envelope = ContextEnvelope(
        envelope_id="context://run/step",
        run_id="run-1",
        workflow_id="workflow-1",
        step_id="collect",
        phase="plan",
        worker_id="llm.collect",
        worker_type="llm",
        segments=(segment,),
        budget=budget,
        artifact_refs=("artifact://accepted-report",),
        token_estimate=64,
    )

    payload = envelope.to_dict()

    assert payload["segments"][0]["segment_type"] == "global_policy"
    assert payload["budget"]["max_input_tokens"] == budget.max_input_tokens
    assert stable_json_dumps(payload)


def test_context_envelope_and_snapshot_round_trip_from_typed_payloads() -> None:
    envelope = ContextEnvelope(
        envelope_id="context://run-persist/step",
        run_id="run-persist",
        workflow_id="workflow-persist",
        step_id="verify",
        phase="verify",
        worker_id="worker-persist",
        worker_type="script",
        segments=(
            ContextSegment(
                segment_id="current-task",
                segment_type=ContextSegmentType.CURRENT_TASK,
                content_ref="task://verify",
                summary="Verify the persisted result.",
                token_estimate=12,
                provenance_refs=("source://paper",),
            ),
        ),
        budget=ContextBudget.safe_default(),
        cache_policy=ContextCachePolicy(
            cache_enabled=True,
            stable_prefix_segments=("global-policy",),
            dynamic_tail_segments=("current-task",),
            cache_key="sha256:context-cache",
        ),
        snapshot_ref="context-snapshot://run-persist",
        stable_prefix={"policy": "bounded"},
        dynamic_tail={"task": "verify"},
        artifact_refs=("artifact://run-persist/report",),
        memory_refs=("memory://run-persist",),
        evidence_refs=("evidence://run-persist",),
        token_estimate=12,
    )
    snapshot = ContextSnapshot(
        snapshot_id="context-snapshot://run-persist",
        envelope_id=envelope.envelope_id,
        run_id="run-persist",
        step_id="verify",
        phase="verify",
        segment_refs=("current-task",),
        assembled_prompt_ref="artifact://run-persist/prompt",
        refs=("source://paper",),
        token_estimate=12,
        cache_key="sha256:context-cache",
        checksum="sha256:context-snapshot",
    )

    assert ContextEnvelope.from_dict(envelope.to_dict()).to_dict() == envelope.to_dict()
    assert ContextSnapshot.from_dict(snapshot.to_dict()).to_dict() == snapshot.to_dict()
