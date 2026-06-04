from __future__ import annotations

from framework.harness import (
    ContextBudget,
    ContextCacheScope,
    ContextEnvelope,
    ContextSegment,
    ContextSegmentType,
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
