from __future__ import annotations

import pytest

from framework.harness import (
    CompressionRecord,
    ContextCompressor,
    ContextCompressionLossGate,
    ContextSchemaPreservationGate,
    ContextSegment,
    HarnessValidationError,
)


def test_compression_rejects_stable_control_plane_segments() -> None:
    compressor = ContextCompressor()
    segment = ContextSegment(
        segment_id="worker-contract",
        segment_type="worker_contract",
        content_ref="worker://contract",
        summary="Output schema and forbidden fields.",
        token_estimate=100,
        provenance_refs=("worker://contract",),
        cache_scope="stable_prefix",
    )

    with pytest.raises(HarnessValidationError):
        compressor.compress_segment(segment, run_id="run-1")


def test_compression_preserves_source_refs_artifact_refs_and_gate_failures() -> None:
    compressor = ContextCompressor()
    segment = ContextSegment(
        segment_id="evidence-memory",
        segment_type="evidence_memory",
        content_ref="evidence-memory://run",
        summary="Accepted evidence and failed repair memory cases with gate failures.",
        token_estimate=200,
        provenance_refs=("source://paper#section=results",),
        metadata={
            "source_refs": ["source://paper#section=results"],
            "artifact_refs": ["artifact://gate-failure"],
            "gate_failures": ["missing citation"],
        },
    )

    compressed, record = compressor.compress_segment(segment, run_id="run-1")

    assert compressed.token_estimate == 100
    assert "source://paper#section=results" in record.preserved_refs
    assert "artifact://gate-failure" in record.preserved_refs
    assert ContextCompressionLossGate().evaluate(record).passed is True


def test_schema_preservation_gate_rejects_lost_control_fields() -> None:
    record = CompressionRecord(
        compression_id="compression://bad",
        run_id="run-1",
        source_ref="worker://contract",
        source_level="c1_canonical_record",
        target_level="c2_step_summary",
        summary_ref="artifact://summary",
        lost_fields=("output_schema",),
        preserved_refs=("worker://contract",),
    )

    assert ContextSchemaPreservationGate().evaluate(record).passed is False
