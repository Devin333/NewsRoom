from __future__ import annotations

import hashlib

from framework.harness.context.models import ContextCompressionSummary, ContextEnvelope, ContextSnapshot
from framework.shared.json import stable_json_dumps


class FakeContextAssembler:
    def __init__(self, *, token_limit: int = 4096) -> None:
        self.token_limit = token_limit
        self.requests: list[dict] = []

    def assemble(self, context_request: dict) -> ContextEnvelope:
        self.requests.append(dict(context_request))
        token_estimate = int(context_request.get("token_estimate", 0))
        return ContextEnvelope(
            envelope_id=str(context_request.get("envelope_id", f"context://fake/{len(self.requests)}")),
            stable_prefix=dict(context_request.get("stable_prefix", {})),
            dynamic_tail=dict(context_request.get("dynamic_tail", {})),
            artifact_refs=tuple(context_request.get("artifact_refs", ())),
            memory_refs=tuple(context_request.get("memory_refs", ())),
            evidence_refs=tuple(context_request.get("evidence_refs", ())),
            token_estimate=token_estimate,
            metadata={"over_budget": token_estimate > self.token_limit, **dict(context_request.get("metadata", {}))},
        )


class FakeContextCompressor:
    def __init__(self) -> None:
        self.summaries: list[ContextCompressionSummary] = []

    def compress(self, envelope: ContextEnvelope) -> ContextCompressionSummary:
        summary = ContextCompressionSummary(
            summary_id=f"compression://fake/{len(self.summaries) + 1}",
            source_envelope_id=envelope.envelope_id,
            summary_ref=f"artifact://context-summary/{envelope.envelope_id}",
            token_estimate_before=envelope.token_estimate,
            token_estimate_after=max(envelope.token_estimate // 2, 0),
            metadata={"compression": "fake"},
        )
        self.summaries.append(summary)
        return summary


class FakeContextSnapshotStore:
    def __init__(self) -> None:
        self.snapshots: dict[str, ContextSnapshot] = {}

    def save(self, envelope: ContextEnvelope) -> ContextSnapshot:
        refs = envelope.artifact_refs + envelope.memory_refs + envelope.evidence_refs
        if not refs:
            refs = (f"context://{envelope.envelope_id}",)
        checksum = hashlib.sha256(stable_json_dumps({"refs": refs, "tokens": envelope.token_estimate}).encode()).hexdigest()
        snapshot = ContextSnapshot(
            snapshot_id=f"snapshot://fake/{len(self.snapshots) + 1}",
            envelope_id=envelope.envelope_id,
            refs=refs,
            token_estimate=envelope.token_estimate,
            cache_key=f"context:{envelope.envelope_id}:{checksum[:12]}",
            checksum=f"sha256:{checksum}",
            metadata={"payload_saved": False},
        )
        self.snapshots[snapshot.snapshot_id] = snapshot
        return snapshot

    def load(self, snapshot_id: str) -> ContextSnapshot:
        return self.snapshots[snapshot_id]


__all__ = ["FakeContextAssembler", "FakeContextCompressor", "FakeContextSnapshotStore"]
