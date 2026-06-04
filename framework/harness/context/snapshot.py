from __future__ import annotations

import hashlib

from framework.harness.context.models import ContextEnvelope, ContextSnapshot
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import stable_json_dumps


class ContextSnapshotStore:
    def __init__(self) -> None:
        self.snapshots: dict[str, ContextSnapshot] = {}
        self.envelopes: dict[str, ContextEnvelope] = {}

    def save(self, envelope: ContextEnvelope) -> ContextSnapshot:
        refs = _envelope_refs(envelope)
        checksum = _checksum(envelope)
        snapshot = ContextSnapshot(
            snapshot_id=f"context-snapshot://{len(self.snapshots) + 1}",
            envelope_id=envelope.envelope_id,
            run_id=envelope.run_id,
            step_id=envelope.step_id,
            phase=envelope.phase,
            segment_refs=tuple(segment.content_ref for segment in envelope.segments),
            assembled_prompt_ref=f"artifact://assembled-context/{envelope.envelope_id}",
            refs=refs,
            token_estimate=envelope.token_estimate,
            cache_key=envelope.cache_policy.cache_key if envelope.cache_policy else f"context:{envelope.envelope_id}",
            checksum=checksum,
            metadata={"payload_saved": False},
        )
        self.snapshots[snapshot.snapshot_id] = snapshot
        self.envelopes[envelope.envelope_id] = envelope
        return snapshot

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
