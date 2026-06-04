from __future__ import annotations

import hashlib

from framework.harness.context.assembler import ContextAssembler
from framework.harness.context.budget import ContextBudgetEstimator
from framework.harness.context.cache import ContextCachePolicyBuilder
from framework.harness.context.compression import ContextCompressor
from framework.harness.context.gates import (
    ContextBudgetGate,
    ContextCacheKeyGate,
    ContextCompressionLossGate,
    ContextPrivacyGate,
    ContextProvenanceGate,
    ContextReplayGate,
    ContextSchemaPreservationGate,
    ContextSegmentOrderGate,
    ContextStablePrefixGate,
)
from framework.harness.context.models import ContextBudget, ContextCompressionSummary, ContextEnvelope, ContextSnapshot
from framework.harness.context.snapshot import ContextSnapshotStore
from framework.shared.json import stable_json_dumps


class FakeContextAssembler(ContextAssembler):
    def __init__(self, *, token_limit: int = 4096) -> None:
        super().__init__()
        self.token_limit = token_limit

    def assemble(self, context_request: dict) -> ContextEnvelope:
        request = {"budget": ContextBudget.safe_default(), **dict(context_request)}
        if "segments" not in request and ("stable_prefix" in request or "dynamic_tail" in request):
            token_estimate = int(request.get("token_estimate", 0))
            envelope = ContextEnvelope(
                envelope_id=str(request.get("envelope_id", f"context://fake/{len(self.events) + 1}")),
                stable_prefix=dict(request.get("stable_prefix", {})),
                dynamic_tail=dict(request.get("dynamic_tail", {})),
                artifact_refs=tuple(request.get("artifact_refs", ())),
                memory_refs=tuple(request.get("memory_refs", ())),
                evidence_refs=tuple(request.get("evidence_refs", ())),
                token_estimate=token_estimate,
                metadata={"over_budget": token_estimate > self.token_limit, **dict(request.get("metadata", {}))},
            )
            return envelope
        envelope = super().assemble(request)
        return envelope


class FakeContextCompressor:
    def __init__(self) -> None:
        self.summaries: list[ContextCompressionSummary] = []
        self.compressor = ContextCompressor()

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


class FakeContextBudgetEstimator(ContextBudgetEstimator):
    pass


class FakeContextCachePolicyBuilder(ContextCachePolicyBuilder):
    pass


class FakeContextGateSuite:
    def __init__(self) -> None:
        self.segment_order = ContextSegmentOrderGate()
        self.stable_prefix = ContextStablePrefixGate()
        self.schema_preservation = ContextSchemaPreservationGate()
        self.budget = ContextBudgetGate()
        self.provenance = ContextProvenanceGate()
        self.privacy = ContextPrivacyGate()
        self.compression_loss = ContextCompressionLossGate()
        self.replay = ContextReplayGate()
        self.cache_key = ContextCacheKeyGate()


class FakeContextRuntime:
    def __init__(self) -> None:
        self.snapshot_store = ContextSnapshotStore()
        self.assembler = ContextAssembler(snapshot_store=self.snapshot_store)

    def assemble(self, request: dict) -> ContextEnvelope:
        return self.assembler.assemble(request)

    def replay(self, snapshot_ref: str) -> ContextEnvelope:
        return self.snapshot_store.replay(snapshot_ref)


__all__ = [
    "FakeContextAssembler",
    "FakeContextBudgetEstimator",
    "FakeContextCachePolicyBuilder",
    "FakeContextCompressor",
    "FakeContextGateSuite",
    "FakeContextRuntime",
    "FakeContextSnapshotStore",
]
