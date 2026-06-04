from __future__ import annotations

from framework.harness import (
    ContextAssembler,
    ContextBudget,
    ContextBudgetGate,
    ContextCompressionLevel,
    ContextEnvelope,
    ContextSegment,
)


def test_context_budget_gate_detects_over_budget_envelope() -> None:
    envelope = ContextEnvelope(
        envelope_id="context://over-budget",
        budget=ContextBudget(
            max_input_tokens=100,
            max_output_tokens=100,
            max_context_segments=6,
            max_evidence_items=8,
            max_memory_items=6,
            max_artifact_refs=12,
        ),
        segments=(
            ContextSegment(
                segment_id="global-policy",
                segment_type="global_policy",
                content_ref="policy://global",
                summary="Harness controls workflow.",
                token_estimate=120,
                provenance_refs=("policy://global",),
                cache_scope="stable_prefix",
            ),
        ),
        token_estimate=120,
    )

    result = ContextBudgetGate().evaluate(envelope)

    assert result.passed is False
    assert "input_tokens" in result.details["violations"]


def test_context_assembler_compresses_dynamic_tail_when_budget_exceeded() -> None:
    assembler = ContextAssembler()
    envelope = assembler.assemble(
        {
            "run_id": "run-budget",
            "budget": ContextBudget(
                max_input_tokens=250,
                max_output_tokens=100,
                max_context_segments=6,
                max_evidence_items=8,
                max_memory_items=6,
                max_artifact_refs=12,
            ),
            "evidence_memory_tokens": 300,
            "current_task_tokens": 200,
        }
    )

    dynamic_levels = [segment.compression_level for segment in envelope.segments[3:]]
    assert dynamic_levels == [ContextCompressionLevel.C2_STEP_SUMMARY] * 3
    assert any(event["event_type"] == "context_compression_recorded" for event in assembler.events)
