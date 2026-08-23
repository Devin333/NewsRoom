from __future__ import annotations

from dataclasses import replace

from framework.harness.context.models import ContextEnvelope, ContextSnapshot
from framework.harness.control_plane.errors import HarnessValidationError


class ContextSnapshotStore:
    def __init__(self) -> None:
        self.snapshots: dict[str, ContextSnapshot] = {}
        self.envelopes: dict[str, ContextEnvelope] = {}

    def save(self, envelope: ContextEnvelope) -> ContextSnapshot:
        _, snapshot = self.save_bound(envelope)
        return snapshot

    def save_bound(self, envelope: ContextEnvelope) -> tuple[ContextEnvelope, ContextSnapshot]:
        """Persist one immutable Graph context projection."""
        snapshot_id = f"context-snapshot://{len(self.snapshots) + 1}"
        bound_envelope = envelope.bind_snapshot_ref(snapshot_id)
        refs = _envelope_refs(bound_envelope)
        snapshot = ContextSnapshot.for_graph_envelope(
            snapshot_id=snapshot_id,
            envelope=bound_envelope,
            segment_refs=tuple(segment.content_ref for segment in bound_envelope.segments),
            assembled_prompt_ref=(
                f"artifact://assembled-context/{bound_envelope.envelope_id}"
            ),
            refs=refs,
            cache_key=(
                bound_envelope.cache_policy.cache_key
                if bound_envelope.cache_policy
                else f"context:{bound_envelope.envelope_id}"
            ),
            metadata={"payload_saved": False},
        )
        self.snapshots[snapshot.snapshot_id] = snapshot
        self.envelopes[bound_envelope.envelope_id] = bound_envelope
        return bound_envelope, snapshot

    def load(self, snapshot_id: str) -> ContextSnapshot:
        return self.snapshots[snapshot_id]

    def replay(self, snapshot_id: str) -> ContextEnvelope:
        snapshot = self.load(snapshot_id)
        envelope = self.envelopes[snapshot.envelope_id]
        return self._replay_graph(snapshot, envelope)

    @staticmethod
    def _replay_graph(
        snapshot: ContextSnapshot,
        envelope: ContextEnvelope,
    ) -> ContextEnvelope:
        if (
            snapshot.graph_identity != envelope.graph_identity
            or snapshot.task_execution_identity != envelope.task_execution_identity
            or snapshot.envelope_checksum != envelope.checksum
            or snapshot.phase != envelope.phase
        ):
            raise HarnessValidationError(
                "Graph context replay identity mismatch",
                code="context_snapshot_replay_identity_mismatch",
            )
        if snapshot.envelope_id != envelope.envelope_id:
            raise HarnessValidationError(
                "Graph context replay envelope identity mismatch",
                code="context_snapshot_replay_identity_mismatch",
            )
        # Parse the stored strict projection again so a forged mutable store entry
        # cannot bypass checksum validation.
        ContextSnapshot.from_dict(snapshot.to_dict())
        ContextEnvelope.from_dict(envelope.to_dict())
        return envelope


def _envelope_refs(envelope: ContextEnvelope) -> tuple[str, ...]:
    refs = tuple(segment.content_ref for segment in envelope.segments)
    refs += envelope.artifact_refs + envelope.memory_refs + envelope.evidence_refs
    if not refs:
        refs = (f"context://{envelope.envelope_id}",)
    return refs
__all__ = ["ContextSnapshotStore"]
