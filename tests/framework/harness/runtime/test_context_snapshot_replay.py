from __future__ import annotations

from framework.harness import ContextSnapshot, ContextSnapshotReplayReader


def test_context_snapshot_replay_uses_refs_without_reassembling_context() -> None:
    snapshot = ContextSnapshot(
        snapshot_id="context-snapshot://1",
        envelope_id="context://run/collect",
        refs=("source://paper#method", "artifact://context-summary"),
        token_estimate=120,
        cache_key="context:stable:abc",
        checksum="sha256:abc",
        segment_refs=("segment://evidence-memory",),
        assembled_prompt_ref="artifact://prompt",
    )

    replay = ContextSnapshotReplayReader().replay_snapshot(snapshot)

    assert replay["refs"] == ["source://paper#method", "artifact://context-summary"]
    assert replay["side_effects_replayed"] is False
