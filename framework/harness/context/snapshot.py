from __future__ import annotations

import hashlib
from dataclasses import replace

from framework.harness.context.models import ContextEnvelope, ContextSnapshot
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import stable_json_dumps


class ContextSnapshotStore:
    def __init__(self) -> None:
        self.snapshots: dict[str, ContextSnapshot] = {}
        self.envelopes: dict[str, ContextEnvelope] = {}

    def save(self, envelope: ContextEnvelope) -> ContextSnapshot:
        _, snapshot = self.save_bound(envelope)
        return snapshot

    def save_bound(self, envelope: ContextEnvelope) -> tuple[ContextEnvelope, ContextSnapshot]:
        """Persist one immutable legacy projection without mutating it after save."""
        snapshot_id = f"context-snapshot://{len(self.snapshots) + 1}"
        bound_envelope = replace(envelope, snapshot_ref=snapshot_id)
        refs = _envelope_refs(bound_envelope)
        checksum = _checksum(bound_envelope)
        snapshot = ContextSnapshot(
            snapshot_id=snapshot_id,
            envelope_id=bound_envelope.envelope_id,
            run_id=bound_envelope.run_id,
            step_id=bound_envelope.step_id,
            phase=bound_envelope.phase,
            segment_refs=tuple(segment.content_ref for segment in bound_envelope.segments),
            assembled_prompt_ref=f"artifact://assembled-context/{bound_envelope.envelope_id}",
            refs=refs,
            token_estimate=bound_envelope.token_estimate,
            cache_key=bound_envelope.cache_policy.cache_key if bound_envelope.cache_policy else f"context:{bound_envelope.envelope_id}",
            checksum=checksum,
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
        if _checksum(envelope) != snapshot.checksum:
            raise HarnessValidationError("context replay checksum mismatch")
        return envelope


def _envelope_refs(envelope: ContextEnvelope) -> tuple[str, ...]:
    refs = tuple(segment.content_ref for segment in envelope.segments)
    refs += envelope.artifact_refs + envelope.memory_refs + envelope.evidence_refs
    if not refs:
        refs = (f"context://{envelope.envelope_id}",)
    return refs


def _checksum(envelope: ContextEnvelope) -> str:
    payload = {
        "envelope_id": envelope.envelope_id,
        "segments": [segment.to_dict() for segment in envelope.segments],
        "refs": _envelope_refs(envelope),
        "token_estimate": envelope.token_estimate,
        "cache_key": envelope.cache_policy.cache_key if envelope.cache_policy else None,
    }
    digest = hashlib.sha256(stable_json_dumps(payload).encode()).hexdigest()
    return f"sha256:{digest}"


__all__ = ["ContextSnapshotStore"]
