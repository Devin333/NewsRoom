from __future__ import annotations

from framework.harness import CompressionRecord, CompressionRecordReplayReader, ContextCompressionLevel


def test_compression_record_replay_requires_preserved_refs() -> None:
    record = CompressionRecord(
        compression_id="compression://1",
        run_id="run-context",
        source_ref="context-segment://evidence-memory",
        source_level=ContextCompressionLevel.C1_CANONICAL_RECORD,
        target_level=ContextCompressionLevel.C2_STEP_SUMMARY,
        summary_ref="artifact://compression-summary",
        preserved_refs=("source://paper#method",),
        metadata={"checksum": "sha256:abc"},
    )

    replay = CompressionRecordReplayReader().replay_record(record)

    assert replay["preserved_refs"] == ["source://paper#method"]
    assert replay["side_effects_replayed"] is False


def test_compression_record_replay_rejects_missing_preserved_refs() -> None:
    record = CompressionRecord(
        compression_id="compression://bad",
        run_id="run-context",
        source_ref="context-segment://evidence-memory",
        source_level=ContextCompressionLevel.C1_CANONICAL_RECORD,
        target_level=ContextCompressionLevel.C2_STEP_SUMMARY,
        summary_ref="artifact://compression-summary",
    )

    try:
        CompressionRecordReplayReader().replay_record(record)
    except Exception as exc:
        assert exc.__class__.__name__ == "HarnessValidationError"
    else:
        raise AssertionError("expected HarnessValidationError")
